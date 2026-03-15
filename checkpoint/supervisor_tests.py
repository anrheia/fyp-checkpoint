from datetime import datetime, timedelta

from django.test import TestCase, Client
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Business, BusinessMembership, WorkShift, TimeClock, StaffProfile

User = get_user_model()


class SupervisorAccessTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='ownerpass')
        self.supervisor = User.objects.create_user(username='supervisor', password='supervisorpass')
        self.employee = User.objects.create_user(username='employee', password='employeepass')
        self.stranger = User.objects.create_user(username='stranger', password='strangerpass')

        self.business = Business.objects.create(name='Test Business')

        BusinessMembership.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessMembership.OWNER
        )
        BusinessMembership.objects.create(
            user=self.supervisor,
            business=self.business,
            role=BusinessMembership.SUPERVISOR
        )
        BusinessMembership.objects.create(
            user=self.employee,
            business=self.business,
            role=BusinessMembership.EMPLOYEE
        )

        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        end = start + timedelta(hours=8)

        self.shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=start,
            end=end,
            created_by=self.owner,
        )

    # --- Dashboard routing ---

    def test_supervisor_sees_supervisor_dashboard(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/supervisor_dashboard.html')

    def test_employee_does_not_see_supervisor_dashboard(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/staff_dashboard.html')

    def test_owner_does_not_see_supervisor_dashboard(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/owner_dashboard.html')

    # --- Schedule access ---

    def test_supervisor_can_view_branch_schedule(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('branch_schedule', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_view_branch_schedule(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('branch_schedule', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_supervisor_can_fetch_branch_shifts_json(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('branch_shifts_json', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_employee_cannot_fetch_branch_shifts_json(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('branch_shifts_json', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    # --- Shift management ---

    def test_supervisor_can_create_shift(self):
        self.client.force_login(self.supervisor)
        start = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
        end = start + timedelta(hours=4)
        resp = self.client.post(reverse('create_shift', args=[self.business.id]), {
            'user': self.employee.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': end.strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })
        self.assertIn(resp.status_code, (200, 302))
        self.assertTrue(WorkShift.objects.filter(created_by=self.supervisor).exists())

    def test_employee_cannot_create_shift(self):
        self.client.force_login(self.employee)
        start = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
        end = start + timedelta(hours=4)
        resp = self.client.post(reverse('create_shift', args=[self.business.id]), {
            'user': self.employee.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': end.strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(WorkShift.objects.filter(created_by=self.employee).exists())

    def test_supervisor_can_delete_shift(self):
        self.client.force_login(self.supervisor)
        url = reverse('delete_shift', args=[self.business.id, self.shift.id])
        resp = self.client.post(url)
        self.assertIn(resp.status_code, (200, 302))
        self.assertFalse(WorkShift.objects.filter(id=self.shift.id).exists())

    def test_employee_cannot_delete_shift(self):
        self.client.force_login(self.employee)
        url = reverse('delete_shift', args=[self.business.id, self.shift.id])
        resp = self.client.post(url)
        self.assertIn(resp.status_code, (302, 403))
        self.assertTrue(WorkShift.objects.filter(id=self.shift.id).exists())

    # --- Staff management ---

    def test_supervisor_can_view_staff(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('view_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_view_staff(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('view_staff', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_view_staff_excludes_owners(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('view_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)
        usernames = [m.user.username for m in resp.context['staff_memberships']]
        self.assertNotIn('owner', usernames)
        self.assertIn('employee', usernames)
        self.assertIn('supervisor', usernames)

    def test_supervisor_can_invite_staff(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('invite_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_invite_staff(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('invite_staff', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    # --- Invite role enforcement ---

    def test_supervisor_cannot_invite_another_supervisor(self):
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('invite_staff', args=[self.business.id]), {
            'first_name': 'New',
            'last_name': 'Super',
            'username': 'newsupervisor',
            'email': 'newsupervisor@test.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        # Role should be forced to EMPLOYEE regardless
        new_membership = BusinessMembership.objects.filter(
            user__username='newsupervisor'
        ).first()
        if new_membership:
            self.assertEqual(new_membership.role, BusinessMembership.EMPLOYEE)

    def test_owner_can_invite_supervisor(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse('invite_staff', args=[self.business.id]), {
            'first_name': 'New',
            'last_name': 'Super',
            'username': 'newsupervisor2',
            'email': 'newsupervisor2@test.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        new_membership = BusinessMembership.objects.filter(
            user__username='newsupervisor2'
        ).first()
        if new_membership:
            self.assertEqual(new_membership.role, BusinessMembership.SUPERVISOR)

    # --- Owner-only views blocked for supervisors ---

    def test_supervisor_cannot_create_branch(self):
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('create_branch'), {'name': 'New Branch'})
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(Business.objects.filter(name='New Branch').exists())

    def test_stranger_cannot_access_any_branch_view(self):
        self.client.force_login(self.stranger)
        for url in [
            reverse('branch_schedule', args=[self.business.id]),
            reverse('view_staff', args=[self.business.id]),
            reverse('invite_staff', args=[self.business.id]),
        ]:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (302, 403), msg=f"Expected 403 for {url}")

    # --- Clock in/out works for supervisors ---

    def test_supervisor_can_clock_in_during_shift(self):
        now = timezone.now()
        WorkShift.objects.create(
            business=self.business,
            user=self.supervisor,
            start=now - timedelta(minutes=5),
            end=now + timedelta(hours=4),
            created_by=self.owner,
        )
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertTrue(TimeClock.objects.filter(
            user=self.supervisor,
            clock_out__isnull=True
        ).exists())

    def test_supervisor_can_clock_out(self):
        now = timezone.now()
        TimeClock.objects.create(
            business=self.business,
            user=self.supervisor,
            clock_in=now - timedelta(hours=1),
            clock_out=None,
        )
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('clock_out', args=[self.business.id]))
        self.assertRedirects(resp, reverse('dashboard'))
        self.assertFalse(TimeClock.objects.filter(
            user=self.supervisor,
            clock_out__isnull=True
        ).exists())

class StaffDetailViewTests(TestCase):

    def setUp(self):
        self.client = Client()

        self.business = Business.objects.create(name="Test Branch")

        # Supervisor
        self.supervisor = User.objects.create_user(
            username="supervisor1", password="pass1234", email="sup@test.com"
        )
        self.supervisor_membership = BusinessMembership.objects.create(
            user=self.supervisor, business=self.business, role=BusinessMembership.SUPERVISOR
        )

        # Employee
        self.employee = User.objects.create_user(
            username="employee1", password="pass1234",
            email="emp@test.com", first_name="Jane", last_name="Doe"
        )
        self.employee_membership = BusinessMembership.objects.create(
            user=self.employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )

        self.url = reverse("staff_detail", args=[self.business.id, self.employee_membership.id])

    def test_staff_detail_page_loads_for_supervisor(self):
        self.client.login(username="supervisor1", password="pass1234")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jane")
        self.assertContains(response, "emp@test.com")

    def test_staff_detail_updates_profile_fields(self):
        self.client.login(username="supervisor1", password="pass1234")
        response = self.client.post(self.url, {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "emp@test.com",
            "phone_number": "0871234567",
            "supervisor_notes": "Very reliable, always on time.",
        })
        self.assertRedirects(response, reverse("view_staff", args=[self.business.id]))
        profile = StaffProfile.objects.get(membership=self.employee_membership)
        self.assertEqual(profile.phone_number, "0871234567")
        self.assertEqual(profile.supervisor_notes, "Very reliable, always on time.")

    def test_unauthenticated_user_cannot_access_staff_detail(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"/accounts/login/?next={self.url}")