from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

# Adjust these imports to match your project/app structure
from .utils import compute_staff_status
from .models import BusinessMembership, WorkShift, TimeClock, Business
from django.contrib.auth import get_user_model

User = get_user_model()


@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ComputeStaffStatusTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Branch 1")

        # Owner (not included in staff status)
        self.owner = User.objects.create_user(username="owner", password="x")
        BusinessMembership.objects.create(
            business=self.business,
            user=self.owner,
            role=BusinessMembership.OWNER
        )

        # Employees
        self.emp_in = User.objects.create_user(username="emp_in", password="x")
        self.emp_late = User.objects.create_user(username="emp_late", password="x")
        self.emp_out_active_within_grace = User.objects.create_user(username="emp_out_grace", password="x")
        self.emp_out_next_shift = User.objects.create_user(username="emp_out_next", password="x")
        self.emp_out_no_shifts = User.objects.create_user(username="emp_out_none", password="x")

        for u in [
            self.emp_in,
            self.emp_late,
            self.emp_out_active_within_grace,
            self.emp_out_next_shift,
            self.emp_out_no_shifts,
        ]:
            BusinessMembership.objects.create(
                business=self.business,
                user=u,
                role=BusinessMembership.EMPLOYEE
            )

    def aware(self, y, m, d, hh, mm, ss=0):
        """Convenience: build an aware datetime in current timezone."""
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime(y, m, d, hh, mm, ss), tz)

    def _run_at(self, fixed_now):
        """
        Run helper at a fixed 'now'. We patch timezone.now() because your helper uses:
        now = timezone.localtime(timezone.now())
        """
        with patch("django.utils.timezone.now", return_value=fixed_now):
            return compute_staff_status(self.business, minutes=15)

    def test_clocked_in_goes_to_in_staff(self):
        now = self.aware(2026, 3, 4, 10, 0)

        # Open time clock (clock_out is null) means "IN"
        TimeClock.objects.create(
            business=self.business,
            user=self.emp_in,
            clock_in=now - timedelta(minutes=5),
            clock_out=None
        )

        status = self._run_at(now)

        in_usernames = [x["user"].username for x in status["in_staff"]]
        self.assertIn("emp_in", in_usernames)

        # Ensure not mistakenly in late/out
        late_usernames = [x["user"].username for x in status["late_staff"]]
        out_usernames = [x["user"].username for x in status["out_staff"]]
        self.assertNotIn("emp_in", late_usernames)
        self.assertNotIn("emp_in", out_usernames)

    def test_active_shift_past_grace_goes_to_late_staff(self):
        now = self.aware(2026, 3, 4, 10, 0)

        # Shift started 20 minutes ago (grace=15) -> LATE if not clocked in
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

        # Shift started 10 minutes ago (within 15-minute grace)
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

        # Should NOT be late
        late_usernames = [x["user"].username for x in status["late_staff"]]
        self.assertNotIn("emp_out_grace", late_usernames)

    def test_out_staff_gets_next_shift_today_when_not_active(self):
        now = self.aware(2026, 3, 4, 10, 0)

        # Next shift later today, not active right now
        next_shift = WorkShift.objects.create(
            business=self.business,
            user=self.emp_out_next_shift,
            start=now + timedelta(hours=3),   # 13:00
            end=now + timedelta(hours=5),     # 15:00
        )

        status = self._run_at(now)

        out_items = [x for x in status["out_staff"] if x["user"].username == "emp_out_next"]
        self.assertEqual(len(out_items), 1)

        # Should have next_shift, and no active shift
        self.assertIsNone(out_items[0].get("shift"))
        self.assertIsNotNone(out_items[0].get("next_shift"))
        self.assertEqual(out_items[0]["next_shift"].id, next_shift.id)

    def test_out_staff_no_shifts_today_has_no_shift_and_no_next_shift(self):
        now = self.aware(2026, 3, 4, 10, 0)

        # No shifts created for emp_out_no_shifts
        status = self._run_at(now)

        out_items = [x for x in status["out_staff"] if x["user"].username == "emp_out_none"]
        self.assertEqual(len(out_items), 1)

        self.assertIsNone(out_items[0].get("shift"))
        self.assertIsNone(out_items[0].get("next_shift"))

    def test_owner_is_not_included_in_results(self):
        now = self.aware(2026, 3, 4, 10, 0)
        status = self._run_at(now)

        all_usernames = (
            [x["user"].username for x in status["in_staff"]] +
            [x["user"].username for x in status["late_staff"]] +
            [x["user"].username for x in status["out_staff"]]
        )
        self.assertNotIn("owner", all_usernames)