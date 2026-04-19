import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Business, BusinessMembership, WorkShift, TimeClock

User = get_user_model()


# Shared helpers — mirrors the pattern used in other test modules
def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password='testpass123', **kwargs)


def make_business(name='Test Branch'):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)


# Default shift straddles "now" so clock-in tests have an active shift without extra setup
def make_shift(business, user, start=None, end=None):
    now = timezone.now()
    start = start or (now - timedelta(hours=1))
    end = end or (now + timedelta(hours=1))
    return WorkShift.objects.create(business=business, user=user, start=start, end=end)


# ---------------------------------------------------------------------------
# QR code generation
# ---------------------------------------------------------------------------

# Verifies the my_qr_code view returns a valid PNG image, not HTML or an error
class MyQRCodeViewTests(TestCase):

    def setUp(self):
        self.employee = make_user('emp1')
        self.business = make_business()
        self.membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_qr_code_returns_png_for_employee(self):
        self.client.login(username='emp1', password='testpass123')
        response = self.client.get(reverse('my_qr_code', args=[self.business.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')


# The scanner page is only for staff who can clock others in — employees use their
# own QR code and must not be able to reach the scanning interface
class QRScannerViewTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.supervisor = make_user('sup1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_owner_can_access_scanner(self):
        self.client.login(username='owner1', password='testpass123')
        self.assertEqual(self.client.get(reverse('qr_scanner', args=[self.business.id])).status_code, 200)

    def test_supervisor_can_access_scanner(self):
        self.client.login(username='sup1', password='testpass123')
        self.assertEqual(self.client.get(reverse('qr_scanner', args=[self.business.id])).status_code, 200)

    def test_employee_cannot_access_scanner(self):
        self.client.login(username='emp1', password='testpass123')
        self.assertEqual(self.client.get(reverse('qr_scanner', args=[self.business.id])).status_code, 403)


# Happy-path and guard tests for QR clock-in; setUp has an active shift so
# the scan should succeed without extra arrangement
class ProcessQRScanClockInTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)
        self.client.login(username='owner1', password='testpass123')

    def _scan(self, token):
        return self.client.post(reverse('process_qr_scan', args=[token]),
                                content_type='application/json')

    def test_successful_clock_in(self):
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['action'], 'clocked_in')

    def test_clock_in_creates_timeclock_record(self):
        # An open TimeClock (clock_out=None) must exist after a successful scan
        self._scan(self.emp_membership.qr_token)
        self.assertTrue(TimeClock.objects.filter(
            business=self.business, user=self.employee, clock_out__isnull=True
        ).exists())

    def test_token_regenerates_after_clock_in(self):
        # Token rotation prevents the same QR code being reused for a second clock-in
        old_token = self.emp_membership.qr_token
        self._scan(old_token)
        self.emp_membership.refresh_from_db()
        self.assertNotEqual(self.emp_membership.qr_token, old_token)

    def test_clock_in_requires_active_shift(self):
        # Without a scheduled shift the scan must fail with a clear error, not silently succeed
        self.shift.delete()
        self.emp_membership.refresh_from_db()
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no active shift', response.json()['error'].lower())


# setUp pre-creates an open TimeClock so the scan resolves as a clock-out, not clock-in
class ProcessQRScanClockOutTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)
        TimeClock.objects.create(
            business=self.business, user=self.employee, shift=self.shift,
            clock_in=timezone.now() - timedelta(minutes=30),
        )
        self.client.login(username='owner1', password='testpass123')

    def _scan(self, token):
        return self.client.post(reverse('process_qr_scan', args=[token]),
                                content_type='application/json')

    def test_successful_clock_out(self):
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['action'], 'clocked_out')

    def test_clock_out_closes_timeclock_record(self):
        # After clock-out there must be no open TimeClock (clock_out should be set)
        self._scan(self.emp_membership.qr_token)
        self.assertFalse(TimeClock.objects.filter(
            business=self.business, user=self.employee, clock_out__isnull=True
        ).exists())


# Employees must only be able to clock themselves in via their own QR code through
# the scanner page; scanning someone else's code must be rejected
class ProcessQRScanPermissionTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        make_shift(self.business, self.employee)

    def _scan(self, token):
        return self.client.post(reverse('process_qr_scan', args=[token]),
                                content_type='application/json')

    def test_employee_cannot_scan_another_employee(self):
        emp2 = make_user('emp2')
        make_membership(emp2, self.business, BusinessMembership.EMPLOYEE)
        self.client.login(username='emp2', password='testpass123')
        self.assertEqual(self._scan(self.emp_membership.qr_token).status_code, 403)

    def test_supervisor_of_same_branch_can_scan(self):
        # Supervisors operate the scanner on behalf of employees, so they must be allowed
        sup = make_user('sup1')
        make_membership(sup, self.business, BusinessMembership.SUPERVISOR)
        self.client.login(username='sup1', password='testpass123')
        self.assertEqual(self._scan(self.emp_membership.qr_token).status_code, 200)


# PIN clock-in mirrors the QR flow but uses a 6-character code instead of a UUID token;
# both the PIN and the QR token rotate together after each use
class ProcessPinScanClockInTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)
        self.url = reverse('process_pin_scan')
        self.client.login(username='owner1', password='testpass123')

    def _scan_pin(self, pin):
        return self.client.post(self.url, data=json.dumps({'pin': pin}),
                                content_type='application/json')

    def test_successful_pin_clock_in(self):
        response = self._scan_pin(self.emp_membership.pin_code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['action'], 'clocked_in')

    def test_pin_clock_in_creates_timeclock_record(self):
        self._scan_pin(self.emp_membership.pin_code)
        self.assertTrue(TimeClock.objects.filter(
            business=self.business, user=self.employee, clock_out__isnull=True
        ).exists())

    def test_pin_and_token_regenerate_after_pin_scan(self):
        # Both credentials rotate together so a single scan can't be replayed via either method
        old_pin = self.emp_membership.pin_code
        old_token = self.emp_membership.qr_token
        self._scan_pin(old_pin)
        self.emp_membership.refresh_from_db()
        self.assertNotEqual(self.emp_membership.pin_code, old_pin)
        self.assertNotEqual(self.emp_membership.qr_token, old_token)

    def test_pin_requires_active_shift(self):
        # PIN clock-in enforces the same active-shift requirement as QR clock-in
        self.shift.delete()
        self.emp_membership.refresh_from_db()
        response = self._scan_pin(self.emp_membership.pin_code)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no active shift', response.json()['error'].lower())


# setUp pre-creates an open TimeClock so the PIN scan resolves as clock-out
class ProcessPinScanClockOutTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)
        TimeClock.objects.create(
            business=self.business, user=self.employee, shift=self.shift,
            clock_in=timezone.now() - timedelta(minutes=30),
        )
        self.url = reverse('process_pin_scan')
        self.client.login(username='owner1', password='testpass123')

    def _scan_pin(self, pin):
        return self.client.post(self.url, data=json.dumps({'pin': pin}),
                                content_type='application/json')

    def test_successful_pin_clock_out(self):
        response = self._scan_pin(self.emp_membership.pin_code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['action'], 'clocked_out')

    def test_pin_clock_out_closes_timeclock_record(self):
        self._scan_pin(self.emp_membership.pin_code)
        self.assertFalse(TimeClock.objects.filter(
            business=self.business, user=self.employee, clock_out__isnull=True
        ).exists())


# Permission matrix for PIN scanning — same rules as QR but verified independently
# since the PIN and QR endpoints are separate views
class ProcessPinScanPermissionTests(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner1')
        self.employee = make_user('emp1')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        make_shift(self.business, self.employee)
        self.url = reverse('process_pin_scan')

    def _scan_pin(self, pin):
        return self.client.post(self.url, data=json.dumps({'pin': pin}),
                                content_type='application/json')

    def test_employee_cannot_scan_another_employee_via_pin(self):
        emp2 = make_user('emp2')
        make_membership(emp2, self.business, BusinessMembership.EMPLOYEE)
        self.client.login(username='emp2', password='testpass123')
        self.assertEqual(self._scan_pin(self.emp_membership.pin_code).status_code, 403)

    def test_supervisor_of_same_branch_can_scan_via_pin(self):
        sup = make_user('sup1')
        make_membership(sup, self.business, BusinessMembership.SUPERVISOR)
        self.client.login(username='sup1', password='testpass123')
        self.assertEqual(self._scan_pin(self.emp_membership.pin_code).status_code, 200)

    def test_owner_can_scan_via_pin(self):
        self.client.login(username='owner1', password='testpass123')
        self.assertEqual(self._scan_pin(self.emp_membership.pin_code).status_code, 200)
