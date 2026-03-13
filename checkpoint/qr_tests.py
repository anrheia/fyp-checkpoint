import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import Business, BusinessMembership, WorkShift, TimeClock

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password="testpass123", **kwargs)


def make_business(name="Test Branch"):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)


def make_shift(business, user, start=None, end=None):
    now = timezone.now()
    start = start or (now - timedelta(hours=1))
    end = end or (now + timedelta(hours=1))
    return WorkShift.objects.create(business=business, user=user, start=start, end=end)


class MyQRCodeViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.employee = make_user("emp1")
        self.business = make_business()
        self.membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_qr_code_returns_png_for_employee(self):
        self.client.login(username="emp1", password="testpass123")
        response = self.client.get(reverse("my_qr_code", args=[self.business.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_qr_code_requires_login(self):
        response = self.client.get(reverse("my_qr_code", args=[self.business.id]))
        self.assertEqual(response.status_code, 302)  # redirect to login

    def test_qr_code_denied_for_non_member(self):
        other = make_user("outsider")
        self.client.login(username="outsider", password="testpass123")
        response = self.client.get(reverse("my_qr_code", args=[self.business.id]))
        self.assertEqual(response.status_code, 403)


class QRScannerViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.owner = make_user("owner1")
        self.supervisor = make_user("sup1")
        self.employee = make_user("emp1")
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_owner_can_access_scanner(self):
        self.client.login(username="owner1", password="testpass123")
        response = self.client.get(reverse("qr_scanner", args=[self.business.id]))
        self.assertEqual(response.status_code, 200)

    def test_supervisor_can_access_scanner(self):
        self.client.login(username="sup1", password="testpass123")
        response = self.client.get(reverse("qr_scanner", args=[self.business.id]))
        self.assertEqual(response.status_code, 200)

    def test_employee_cannot_access_scanner(self):
        self.client.login(username="emp1", password="testpass123")
        response = self.client.get(reverse("qr_scanner", args=[self.business.id]))
        self.assertEqual(response.status_code, 403)

    def test_scanner_requires_login(self):
        response = self.client.get(reverse("qr_scanner", args=[self.business.id]))
        self.assertEqual(response.status_code, 302)


class ProcessQRScanClockInTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.owner = make_user("owner1")
        self.employee = make_user("emp1")
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)

    def _scan(self, token):
        return self.client.post(
            reverse("process_qr_scan", args=[token]),
            content_type="application/json",
        )

    def test_successful_clock_in(self):
        self.client.login(username="owner1", password="testpass123")
        token = self.emp_membership.qr_token
        response = self._scan(token)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action"], "clocked_in")
        self.assertIn("clocked in", data["message"].lower())

    def test_clock_in_creates_timeclock_record(self):
        self.client.login(username="owner1", password="testpass123")
        token = self.emp_membership.qr_token
        self._scan(token)
        self.assertTrue(
            TimeClock.objects.filter(
                business=self.business,
                user=self.employee,
                clock_out__isnull=True
            ).exists()
        )

    def test_token_regenerates_after_clock_in(self):
        self.client.login(username="owner1", password="testpass123")
        old_token = self.emp_membership.qr_token
        self._scan(old_token)
        self.emp_membership.refresh_from_db()
        self.assertNotEqual(self.emp_membership.qr_token, old_token)

    def test_old_token_invalid_after_scan(self):
        self.client.login(username="owner1", password="testpass123")
        old_token = self.emp_membership.qr_token
        self._scan(old_token)
        # Scan again with the old token
        response = self._scan(old_token)
        self.assertEqual(response.status_code, 404)

    def test_clock_in_requires_active_shift(self):
        self.client.login(username="owner1", password="testpass123")
        self.shift.delete()
        token = self.emp_membership.qr_token
        response = self._scan(token)
        self.assertEqual(response.status_code, 400)
        self.assertIn("no active shift", response.json()["error"].lower())

    def test_cannot_clock_in_twice_for_same_shift(self):
        self.client.login(username="owner1", password="testpass123")
        # First clock in manually
        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            shift=self.shift,
            clock_in=timezone.now()
        )
        self.emp_membership.refresh_from_db()
        token = self.emp_membership.qr_token
        response = self._scan(token)
        # Employee is already clocked in — should clock OUT
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "clocked_out")

    def test_invalid_token_returns_404(self):
        self.client.login(username="owner1", password="testpass123")
        response = self._scan(uuid.uuid4())
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_scan_returns_401(self):
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 401)


class ProcessQRScanClockOutTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.owner = make_user("owner1")
        self.employee = make_user("emp1")
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.shift = make_shift(self.business, self.employee)
        # Pre-clock the employee in
        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            shift=self.shift,
            clock_in=timezone.now() - timedelta(minutes=30)
        )

    def _scan(self, token):
        return self.client.post(
            reverse("process_qr_scan", args=[token]),
            content_type="application/json",
        )

    def test_successful_clock_out(self):
        self.client.login(username="owner1", password="testpass123")
        token = self.emp_membership.qr_token
        response = self._scan(token)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action"], "clocked_out")
        self.assertIn("clocked out", data["message"].lower())

    def test_clock_out_sets_clock_out_timestamp(self):
        self.client.login(username="owner1", password="testpass123")
        self._scan(self.emp_membership.qr_token)
        open_clock = TimeClock.objects.filter(
            business=self.business,
            user=self.employee,
            clock_out__isnull=True
        )
        self.assertFalse(open_clock.exists())

    def test_token_regenerates_after_clock_out(self):
        self.client.login(username="owner1", password="testpass123")
        old_token = self.emp_membership.qr_token
        self._scan(old_token)
        self.emp_membership.refresh_from_db()
        self.assertNotEqual(self.emp_membership.qr_token, old_token)


class ProcessQRScanPermissionTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.other_business = make_business("Other Branch")
        self.owner = make_user("owner1")
        self.employee = make_user("emp1")
        self.outsider = make_user("outsider")
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        make_shift(self.business, self.employee)

    def _scan(self, token):
        return self.client.post(
            reverse("process_qr_scan", args=[token]),
            content_type="application/json",
        )

    def test_employee_cannot_scan_another_employee(self):
        emp2 = make_user("emp2")
        make_membership(emp2, self.business, BusinessMembership.EMPLOYEE)
        self.client.login(username="emp2", password="testpass123")
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 403)

    def test_outsider_cannot_scan(self):
        self.client.login(username="outsider", password="testpass123")
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 403)

    def test_supervisor_from_different_branch_cannot_scan(self):
        sup = make_user("sup_other")
        make_membership(sup, self.other_business, BusinessMembership.SUPERVISOR)
        self.client.login(username="sup_other", password="testpass123")
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 403)

    def test_supervisor_of_same_branch_can_scan(self):
        sup = make_user("sup1")
        make_membership(sup, self.business, BusinessMembership.SUPERVISOR)
        make_shift(self.business, self.employee)
        self.client.login(username="sup1", password="testpass123")
        response = self._scan(self.emp_membership.qr_token)
        self.assertEqual(response.status_code, 200)


class QRTokenUniquenessTests(TestCase):

    def test_each_membership_gets_unique_token(self):
        business = make_business()
        users = [make_user(f"user{i}") for i in range(5)]
        memberships = [make_membership(u, business) for u in users]
        tokens = [str(m.qr_token) for m in memberships]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_token_is_valid_uuid(self):
        business = make_business()
        user = make_user("testuser")
        membership = make_membership(user, business)
        try:
            uuid.UUID(str(membership.qr_token))
        except ValueError:
            self.fail("qr_token is not a valid UUID")

    def test_token_changes_on_each_scan(self):
        client = Client()
        business = make_business()
        owner = make_user("owner1")
        employee = make_user("emp1")
        make_membership(owner, business, BusinessMembership.OWNER)
        membership = make_membership(employee, business, BusinessMembership.EMPLOYEE)

        tokens_seen = set()
        for _ in range(3):
            make_shift(business, employee)
            client.login(username="owner1", password="testpass123")
            token = membership.qr_token
            tokens_seen.add(str(token))
            client.post(reverse("process_qr_scan", args=[token]), content_type="application/json")
            membership.refresh_from_db()
            # Clock out so next scan clocks in again
            TimeClock.objects.filter(business=business, user=employee, clock_out__isnull=True).update(
                clock_out=timezone.now()
            )

        self.assertEqual(len(tokens_seen), 3, "Token should be unique on every scan")
