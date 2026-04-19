from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, TimeClock, StaffProfile

User = get_user_model()

# Shared helpers — mirrors the pattern used across other test modules
def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password='testpass123', **kwargs)


def make_business(name='Test Branch'):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)


# Default shift straddles "now" so it counts as active without extra arrangement
def make_shift(business, user, start=None, end=None):
    now = timezone.now()
    start = start or (now - timedelta(hours=1))
    end = end or (now + timedelta(hours=1))
    return WorkShift.objects.create(business=business, user=user, start=start, end=end)

# Tests for schedule read access — employees may view their own shifts but must
# not be able to read the full branch calendar or modify any shift records
class StaffScheduleTest(TestCase):

    def setUp(self):
        self.owner = make_user('owner')
        self.employee = make_user('employee')
        self.business = make_business()

        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

        # Tomorrow's shift so it's clearly upcoming and won't be filtered by active-shift logic
        start = timezone.now() + timedelta(days=1)
        self.shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=start,
            end=start + timedelta(hours=8),
            created_by=self.owner,
            notes='Test shift',
        )

    def test_employee_can_fetch_own_shifts_json(self):
        # The staff-specific endpoint must return the employee's own shifts
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('staff_branch_shifts_json', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)
        ids = [item.get('id') for item in resp.json()]
        self.assertIn(self.shift.id, ids)

    def test_employee_only_sees_own_shifts(self):
        # The response must not leak another employee's shift IDs
        other = make_user('other_emp')
        make_membership(other, self.business, BusinessMembership.EMPLOYEE)
        other_shift = make_shift(self.business, other)
        self.client.force_login(self.employee)
        ids = [item.get('id') for item in self.client.get(
            reverse('staff_branch_shifts_json', args=[self.business.id])
        ).json()]
        self.assertIn(self.shift.id, ids)
        self.assertNotIn(other_shift.id, ids)

    def test_employee_cannot_fetch_all_branch_shifts_json(self):
        # The owner/supervisor full-calendar endpoint must be blocked for plain employees
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('branch_shifts_json', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_employee_cannot_delete_shift(self):
        # Shift deletion is owner/supervisor-only; the record must survive the attempt
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('delete_shift', args=[self.business.id, self.shift.id]))
        self.assertIn(resp.status_code, (302, 403))
        self.assertTrue(WorkShift.objects.filter(id=self.shift.id).exists())

    def test_staff_dashboard_shows_pin_code(self):
        # The PIN code must be visible on the dashboard so the employee can use it at the scanner
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        self.assertIn(self.emp_membership.pin_code, resp.content.decode())

# Tests for self-service clock-in and clock-out via the dashboard buttons;
# the active-shift gate must be enforced and non-members must be rejected
class StaffClockTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_employee_can_clock_in_during_active_shift(self):
        # Successful clock-in must redirect to dashboard and leave an open TimeClock
        now = timezone.now()
        WorkShift.objects.create(
            business=self.business, user=self.employee,
            start=now - timedelta(minutes=5), end=now + timedelta(hours=4),
            created_by=self.owner,
        )
        self.client.force_login(self.employee)
        self.assertRedirects(self.client.post(reverse('clock_in', args=[self.business.id])), reverse('dashboard'))
        self.assertTrue(TimeClock.objects.filter(user=self.employee, clock_out__isnull=True).exists())

    def test_employee_cannot_clock_in_without_active_shift(self):
        # No shift scheduled → clock-in must be rejected with no TimeClock created
        self.client.force_login(self.employee)
        self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertFalse(TimeClock.objects.filter(user=self.employee).exists())

    def test_employee_can_clock_out(self):
        # Pre-existing open TimeClock must be closed; no open record should remain afterwards
        TimeClock.objects.create(
            business=self.business, user=self.employee,
            clock_in=timezone.now() - timedelta(hours=1), clock_out=None,
        )
        self.client.force_login(self.employee)
        self.assertRedirects(self.client.post(reverse('clock_out', args=[self.business.id])), reverse('dashboard'))
        self.assertFalse(TimeClock.objects.filter(user=self.employee, clock_out__isnull=True).exists())

    def test_non_member_cannot_clock_in(self):
        # A user with no membership in this branch must be blocked and produce no TimeClock
        stranger = make_user('stranger')
        self.client.force_login(stranger)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(TimeClock.objects.filter(user=stranger).exists())


# my_hours is member-only; a user with no membership must be refused so they
# cannot infer worked hours for employees at branches they don't belong to
class MyHoursAccessTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        self.stranger = make_user('stranger')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('my_hours', args=[self.business.id])

    def test_non_member_gets_403(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 403)


# Verifies the my_qr_code view returns a valid PNG — duplicates the check in
# test_qr.py at the staff level to catch regressions from permission changes
class MyQRCodeTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_employee_gets_qr_code_png(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('my_qr_code', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')


# Employees must not be able to schedule shifts — shift creation is restricted
# to owners and supervisors so that staff cannot manipulate their own roster
class StaffScheduleBlockTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_employee_cannot_create_shift(self):
        # The shift must not exist after a blocked attempt; created_by is a safe proxy for that
        self.client.force_login(self.employee)
        start = timezone.now() + timedelta(days=2)
        resp = self.client.post(reverse('create_shift', args=[self.business.id]), {
            'user': self.employee.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': (start + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(WorkShift.objects.filter(created_by=self.employee).exists())


# Employees must not reach owner-only management pages such as invite_staff or
# assign_roles — these tests catch permission regressions at the view layer
class StaffPageBlockTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.emp_mem = BusinessMembership.objects.get(user=self.employee, business=self.business)

    def test_employee_cannot_access_invite_staff(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('invite_staff', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_employee_cannot_assign_roles(self):
        # No StaffProfile must be created as a side-effect of the blocked POST
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('assign_roles', args=[self.business.id]),
                                {f'position_{self.emp_mem.id}': 'Kitchen'})
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(StaffProfile.objects.filter(membership=self.emp_mem).exists())


# Employees may only read their own hours JSON; fetching another employee's
# hours must be refused to prevent cross-staff data leakage
class StaffHoursAccessTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('staff_hours_json', args=[self.business.id, self.employee.id])

    def test_employee_can_view_own_hours(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_employee_cannot_view_other_employee_hours(self):
        other = make_user('other')
        make_membership(other, self.business, BusinessMembership.EMPLOYEE)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
