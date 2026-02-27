from datetime import timedelta

from django.test import TestCase
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