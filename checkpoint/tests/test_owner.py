from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..utils import compute_staff_status
from ..models import BusinessMembership, WorkShift, TimeClock, Business
from django.contrib.auth import get_user_model

User = get_user_model()


@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ComputeStaffStatusTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Branch 1")

        self.owner = User.objects.create_user(username="owner", password="x")
        BusinessMembership.objects.create(
            business=self.business,
            user=self.owner,
            role=BusinessMembership.OWNER
        )

        self.emp_in = User.objects.create_user(username="emp_in", password="x")
        self.emp_late = User.objects.create_user(username="emp_late", password="x")
        self.emp_out_active_within_grace = User.objects.create_user(username="emp_out_grace", password="x")
        self.emp_out_next_shift = User.objects.create_user(username="emp_out_next", password="x")
        self.emp_out_no_shifts = User.objects.create_user(username="emp_out_none", password="x")
        self.emp_done = User.objects.create_user(username="emp_done", password="x")
        self.emp_sup = User.objects.create_user(username="emp_sup", password="x")

        for u in [
            self.emp_in,
            self.emp_late,
            self.emp_out_active_within_grace,
            self.emp_out_next_shift,
            self.emp_out_no_shifts,
            self.emp_done,
        ]:
            BusinessMembership.objects.create(
                business=self.business,
                user=u,
                role=BusinessMembership.EMPLOYEE
            )

        BusinessMembership.objects.create(
            business=self.business,
            user=self.emp_sup,
            role=BusinessMembership.SUPERVISOR
        )

    def aware(self, y, m, d, hh, mm, ss=0):
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime(y, m, d, hh, mm, ss), tz)

    def _run_at(self, fixed_now):
        with patch("django.utils.timezone.now", return_value=fixed_now):
            return compute_staff_status(self.business, minutes=15)

    def test_clocked_in_goes_to_in_staff(self):
        now = self.aware(2026, 3, 4, 10, 0)

        TimeClock.objects.create(
            business=self.business,
            user=self.emp_in,
            clock_in=now - timedelta(minutes=5),
            clock_out=None
        )

        status = self._run_at(now)

        in_usernames = [x["user"].username for x in status["in_staff"]]
        self.assertIn("emp_in", in_usernames)

        late_usernames = [x["user"].username for x in status["late_staff"]]
        out_usernames = [x["user"].username for x in status["out_staff"]]
        self.assertNotIn("emp_in", late_usernames)
        self.assertNotIn("emp_in", out_usernames)

    def test_active_shift_past_grace_goes_to_late_staff(self):
        now = self.aware(2026, 3, 4, 10, 0)

        WorkShift.objects.create(
            business=self.business,
            user=self.emp_late,
            start=now - timedelta(minutes=20),
            end=now + timedelta(hours=2),
        )

        status = self._run_at(now)

        late_usernames = [x["user"].username for x in status["late_staff"]]
        self.assertIn("emp_late", late_usernames)

        in_usernames = [x["user"].username for x in status["in_staff"]]
        out_usernames = [x["user"].username for x in status["out_staff"]]
        self.assertNotIn("emp_late", in_usernames)
        self.assertNotIn("emp_late", out_usernames)

    def test_active_shift_within_grace_goes_to_out_staff_with_shift(self):
        now = self.aware(2026, 3, 4, 10, 0)

        shift = WorkShift.objects.create(
            business=self.business,
            user=self.emp_out_active_within_grace,
            start=now - timedelta(minutes=10),
            end=now + timedelta(hours=2),
        )

        status = self._run_at(now)

        out_items = [x for x in status["out_staff"] if x["user"].username == "emp_out_grace"]
        self.assertEqual(len(out_items), 1)
        self.assertIsNotNone(out_items[0].get("shift"))
        self.assertEqual(out_items[0]["shift"].id, shift.id)

        late_usernames = [x["user"].username for x in status["late_staff"]]
        self.assertNotIn("emp_out_grace", late_usernames)

    def test_out_staff_gets_next_shift_today_when_not_active(self):
        now = self.aware(2026, 3, 4, 10, 0)

        next_shift = WorkShift.objects.create(
            business=self.business,
            user=self.emp_out_next_shift,
            start=now + timedelta(hours=3),   # 13:00
            end=now + timedelta(hours=5),     # 15:00
        )

        status = self._run_at(now)

        out_items = [x for x in status["out_staff"] if x["user"].username == "emp_out_next"]
        self.assertEqual(len(out_items), 1)

        self.assertIsNone(out_items[0].get("shift"))
        self.assertIsNotNone(out_items[0].get("next_shift"))
        self.assertEqual(out_items[0]["next_shift"].id, next_shift.id)

    def test_out_staff_no_shifts_today_has_no_shift_and_no_next_shift(self):
        now = self.aware(2026, 3, 4, 10, 0)

        status = self._run_at(now)

        not_sched = [x for x in status["not_scheduled"] if x["user"].username == "emp_out_none"]
        self.assertEqual(len(not_sched), 1)

        out_items = [x for x in status["out_staff"] if x["user"].username == "emp_out_none"]
        self.assertEqual(len(out_items), 0)

    def test_owner_is_not_included_in_results(self):
        now = self.aware(2026, 3, 4, 10, 0)
        status = self._run_at(now)

        all_usernames = (
            [x["user"].username for x in status["in_staff"]] +
            [x["user"].username for x in status["late_staff"]] +
            [x["user"].username for x in status["out_staff"]]
        )
        self.assertNotIn("owner", all_usernames)

    def test_shift_ended_without_clocking_in_goes_to_done_staff(self):
        now = self.aware(2026, 3, 4, 14, 0)

        WorkShift.objects.create(
            business=self.business,
            user=self.emp_done,
            start=now - timedelta(hours=5),   # 09:00
            end=now - timedelta(hours=1),     # 13:00 — already finished
        )

        status = self._run_at(now)

        done_usernames = [x["user"].username for x in status["done_staff"]]
        self.assertIn("emp_done", done_usernames)

        out_usernames = [x["user"].username for x in status["out_staff"]]
        late_usernames = [x["user"].username for x in status["late_staff"]]
        self.assertNotIn("emp_done", out_usernames)
        self.assertNotIn("emp_done", late_usernames)

class OwnerCreateBranchTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.business = Business.objects.create(name='Existing Branch')
        BusinessMembership.objects.create(user=self.owner, business=self.business,
                                          role=BusinessMembership.OWNER)
        self.non_owner = User.objects.create_user(username='employee', password='pass')
        BusinessMembership.objects.create(user=self.non_owner, business=self.business,
                                          role=BusinessMembership.EMPLOYEE)

    def test_owner_can_create_branch(self):
        self.client.login(username='owner', password='pass')
        self.client.post(reverse('create_branch'), {'name': 'New Branch'})
        self.assertTrue(Business.objects.filter(name='New Branch').exists())

    def test_owner_membership_created_for_new_branch(self):
        self.client.login(username='owner', password='pass')
        self.client.post(reverse('create_branch'), {'name': 'Second Branch'})
        branch = Business.objects.get(name='Second Branch')
        self.assertTrue(BusinessMembership.objects.filter(
            user=self.owner, business=branch, role=BusinessMembership.OWNER
        ).exists())

    def test_non_owner_cannot_create_branch(self):
        self.client.login(username='employee', password='pass')
        resp = self.client.post(reverse('create_branch'), {'name': 'Blocked Branch'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Business.objects.filter(name='Blocked Branch').exists())


class OwnerDeleteBranchTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.business = Business.objects.create(name='Branch To Delete')
        BusinessMembership.objects.create(user=self.owner, business=self.business,
                                          role=BusinessMembership.OWNER)
        self.non_owner = User.objects.create_user(username='employee', password='pass')
        BusinessMembership.objects.create(user=self.non_owner, business=self.business,
                                          role=BusinessMembership.EMPLOYEE)

    def test_owner_can_delete_branch(self):
        self.client.login(username='owner', password='pass')
        self.client.post(reverse('delete_branch', args=[self.business.id]))
        self.assertFalse(Business.objects.filter(id=self.business.id).exists())

    def test_deleting_branch_removes_exclusive_staff(self):
        self.client.login(username='owner', password='pass')
        self.client.post(reverse('delete_branch', args=[self.business.id]))
        self.assertFalse(User.objects.filter(username='employee').exists())

    def test_non_owner_cannot_delete_branch(self):
        self.client.login(username='employee', password='pass')
        resp = self.client.post(reverse('delete_branch', args=[self.business.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Business.objects.filter(id=self.business.id).exists())

