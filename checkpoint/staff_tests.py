from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Business, BusinessMembership, WorkShift, TimeClock

User = get_user_model()

#Staff tests

class StaffScheduleTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='ownerpass')
        self.employee = User.objects.create_user(username='employee', password='employeepass')

        self.business = Business.objects.create(name='Test Business')

        BusinessMembership.objects.create(
            user=self.owner, 
            business=self.business, 
            role=BusinessMembership.OWNER)
        
        BusinessMembership.objects.create(
            user=self.employee, 
            business=self.business, 
            role=BusinessMembership.EMPLOYEE)
        
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        end = start + timedelta(hours=8)

        self.shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=start,
            end=end,
            created_by=self.owner,
            notes="Test shift"
        )


    def test_employee_can_fetch_staff_shifts_json(self):
        self.client.force_login(self.employee)

        url = reverse("staff_branch_shifts_json", args=[self.business.id])
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 1)

        ids = {str(item.get("id")) for item in payload if item.get("id") is not None}
        if ids:
            self.assertIn(str(self.shift.id), ids)

    def test_employee_cannot_fetch_owner_shifts_json(self):
        self.client.force_login(self.employee)

        url = reverse("branch_shifts_json", args=[self.business.id])
        resp = self.client.get(url)

        self.assertIn(resp.status_code, (302, 403))

    def test_owner_can_fetch_owner_shifts_json(self):
        self.client.force_login(self.owner)

        url = reverse("branch_shifts_json", args=[self.business.id])
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_delete_shift(self):
        self.client.force_login(self.employee)

        url = f"/branches/{self.business.id}/schedule/shifts/{self.shift.id}/delete/"
        resp = self.client.get(url)

        self.assertIn(resp.status_code, (302, 403))

    def test_staff_dashboard_contains_calendar(self):
        self.client.force_login(self.employee)

        url = reverse("dashboard")  
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        html = resp.content.decode("utf-8")
        self.assertIn('id="calendar"', html)

        events_url = reverse("staff_branch_shifts_json", args=[self.business.id])
        self.assertIn(events_url, html)

@override_settings(TIME_ZONE="Europe/Dublin", USE_TZ=True)
class MyHoursTest(TestCase):
    def setUp(self):
        # Create business
        self.business = Business.objects.create(name="Luigi's")

        # Create users
        self.employee = User.objects.create_user(username="staff1", password="pass123")
        self.other_employee = User.objects.create_user(username="staff2", password="pass123")
        self.stranger = User.objects.create_user(username="stranger", password="pass123")

        # Memberships
        BusinessMembership.objects.create(
            user=self.employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        BusinessMembership.objects.create(
            user=self.other_employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )

        self.url = reverse("my_hours", args=[self.business.id])

        # Ensure TZ active during tests
        timezone.activate(timezone.get_default_timezone())

    def _aware(self, y, m, d, hh, mm=0):
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime(y, m, d, hh, mm), tz)
    
    @patch("checkpoint.views.timezone.localdate")
    def test_my_hours_totals_week_and_month(self, mock_localdate):

        mock_localdate.return_value = datetime(2026, 2, 27).date()

        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            clock_in=self._aware(2026, 2, 24, 9, 0),
            clock_out=self._aware(2026, 2, 24, 17, 0),
        )

        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            clock_in=self._aware(2026, 2, 26, 10, 0),
            clock_out=self._aware(2026, 2, 26, 14, 30),
        )

        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            clock_in=self._aware(2026, 3, 2, 9, 0),
            clock_out=self._aware(2026, 3, 2, 12, 0),
        )

        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            clock_in=self._aware(2026, 2, 27, 9, 0),
            clock_out=None,
        )

        TimeClock.objects.create(
            business=self.business,
            user=self.other_employee,
            clock_in=self._aware(2026, 2, 24, 9, 0),
            clock_out=self._aware(2026, 2, 24, 17, 0),
        )

        WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=self._aware(2026, 2, 24, 9, 0),
            end=self._aware(2026, 2, 24, 17, 0),
            created_by=self.employee,
        )

        WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=self._aware(2026, 2, 26, 10, 0),
            end=self._aware(2026, 2, 26, 14, 30),
            created_by=self.employee,
        )

        WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=self._aware(2026, 2, 28, 23, 0),
            end=self._aware(2026, 3, 1, 2, 0),
            created_by=self.employee,
        )

        WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=self._aware(2026, 3, 2, 9, 0),
            end=self._aware(2026, 3, 2, 12, 0),
            created_by=self.employee,
        )

        WorkShift.objects.create(
            business=self.business,
            user=self.other_employee,
            start=self._aware(2026, 2, 24, 9, 0),
            end=self._aware(2026, 2, 24, 17, 0),
            created_by=self.other_employee,
        )

        self.client.login(username="staff1", password="pass123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(resp.context["week_hours"], 12)
        self.assertEqual(resp.context["week_minutes"], 30)

        self.assertEqual(resp.context["month_hours"], 12)
        self.assertEqual(resp.context["month_minutes"], 30)

        self.assertEqual(resp.context["week_sched_hours"], 15)
        self.assertEqual(resp.context["week_sched_minutes"], 30)

        self.assertEqual(resp.context["month_sched_hours"], 13)
        self.assertEqual(resp.context["month_sched_minutes"], 30)

        self.assertEqual(str(resp.context["week_start"]), "2026-02-23")
        self.assertEqual(str(resp.context["week_end"]), "2026-03-01")
        self.assertEqual(str(resp.context["month_start"]), "2026-02-01")
        self.assertEqual(str(resp.context["month_end"]), "2026-02-28")

    def test_my_hours_requires_membership(self):
        self.client.login(username="stranger", password="pass123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    @patch("checkpoint.views.timezone.localdate")
    def test_my_hours_zero_when_no_clocks(self, mock_localdate):
        mock_localdate.return_value = datetime(2026, 2, 27).date()

        self.client.login(username="staff1", password="pass123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(resp.context["week_hours"], 0)
        self.assertEqual(resp.context["week_minutes"], 0)
        self.assertEqual(resp.context["month_hours"], 0)
        self.assertEqual(resp.context["month_minutes"], 0)