from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, TimeClock

User = get_user_model()

def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password='testpass123', **kwargs)


def make_business(name='Test Branch'):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)


def make_shift(business, user, start=None, end=None):
    now = timezone.now()
    start = start or (now - timedelta(hours=1))
    end = end or (now + timedelta(hours=1))
    return WorkShift.objects.create(business=business, user=user, start=start, end=end)

class StaffScheduleTest(TestCase):

    def setUp(self):
        self.owner = make_user('owner')
        self.employee = make_user('employee')
        self.business = make_business()

        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

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
        self.client.force_login(self.employee)
        url = reverse('staff_branch_shifts_json', args=[self.business.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIsInstance(payload, list)
        ids = [item.get('id') for item in payload]
        self.assertIn(self.shift.id, ids)

    def test_employee_only_sees_own_shifts(self):
        other = make_user('other_emp')
        make_membership(other, self.business, BusinessMembership.EMPLOYEE)
        other_shift = make_shift(self.business, other)
        self.client.force_login(self.employee)
        url = reverse('staff_branch_shifts_json', args=[self.business.id])
        resp = self.client.get(url)
        ids = [item.get('id') for item in resp.json()]
        self.assertIn(self.shift.id, ids)
        self.assertNotIn(other_shift.id, ids)

    def test_employee_cannot_fetch_all_branch_shifts_json(self):
        self.client.force_login(self.employee)
        url = reverse('branch_shifts_json', args=[self.business.id])
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (302, 403))

    def test_owner_can_fetch_all_branch_shifts_json(self):
        self.client.force_login(self.owner)
        url = reverse('branch_shifts_json', args=[self.business.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_delete_shift(self):
        self.client.force_login(self.employee)
        url = reverse('delete_shift', args=[self.business.id, self.shift.id])
        resp = self.client.post(url)
        self.assertIn(resp.status_code, (302, 403))
        self.assertTrue(WorkShift.objects.filter(id=self.shift.id).exists())

    def test_staff_dashboard_has_calendar_element(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('id="calendar"', html)

    def test_staff_dashboard_links_to_shifts_json(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        html = resp.content.decode('utf-8')
        events_url = reverse('staff_branch_shifts_json', args=[self.business.id])
        self.assertIn(events_url, html)

    def test_staff_dashboard_shows_pin_code(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.emp_membership.pin_code, resp.content.decode())

class StaffClockTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_employee_can_clock_in_during_active_shift(self):
        now = timezone.now()
        WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=now - timedelta(minutes=5),
            end=now + timedelta(hours=4),
            created_by=self.owner,
        )
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertTrue(TimeClock.objects.filter(
            user=self.employee, clock_out__isnull=True
        ).exists())

    def test_employee_cannot_clock_in_without_active_shift(self):
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertFalse(TimeClock.objects.filter(user=self.employee).exists())

    def test_employee_cannot_clock_in_when_already_clocked_in(self):
        now = timezone.now()
        shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=now - timedelta(minutes=5),
            end=now + timedelta(hours=4),
            created_by=self.owner,
        )
        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            shift=shift,
            clock_in=now - timedelta(minutes=3),
        )
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        # Only one TimeClock record should exist
        self.assertEqual(TimeClock.objects.filter(user=self.employee).count(), 1)

    def test_employee_cannot_clock_in_twice_for_same_shift(self):
        now = timezone.now()
        shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=now - timedelta(minutes=5),
            end=now + timedelta(hours=4),
            created_by=self.owner,
        )
        # Clock in once manually (simulating already clocked-out and re-clocking)
        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            shift=shift,
            clock_in=now - timedelta(minutes=3),
            clock_out=now - timedelta(minutes=1),
        )
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertEqual(TimeClock.objects.filter(user=self.employee).count(), 1)

    def test_employee_can_clock_out(self):
        now = timezone.now()
        TimeClock.objects.create(
            business=self.business,
            user=self.employee,
            clock_in=now - timedelta(hours=1),
            clock_out=None,
        )
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_out', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertFalse(TimeClock.objects.filter(
            user=self.employee, clock_out__isnull=True
        ).exists())

    def test_employee_cannot_clock_out_when_not_clocked_in(self):
        self.client.force_login(self.employee)
        resp = self.client.post(reverse('clock_out', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        # No TimeClock records created
        self.assertFalse(TimeClock.objects.filter(user=self.employee).exists())

    def test_non_member_cannot_clock_in(self):
        stranger = make_user('stranger')
        now = timezone.now()
        self.client.force_login(stranger)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(TimeClock.objects.filter(user=stranger).exists())

class MyHoursAccessTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        self.stranger = make_user('stranger')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('my_hours', args=[self.business.id])

    def test_non_member_gets_403(self):
        self.client.force_login(self.stranger)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_user_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

class MyQRCodeTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.employee = make_user('employee')
        self.stranger = make_user('stranger')
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_employee_gets_qr_code_png(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('my_qr_code', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_qr_code_requires_login(self):
        resp = self.client.get(reverse('my_qr_code', args=[self.business.id]))
        self.assertEqual(resp.status_code, 302)

    def test_non_member_cannot_get_qr_code(self):
        self.client.force_login(self.stranger)
        resp = self.client.get(reverse('my_qr_code', args=[self.business.id]))
        self.assertEqual(resp.status_code, 403)
