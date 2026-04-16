from datetime import datetime, timedelta

from django.test import TestCase, Client
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, TimeClock, StaffProfile

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

class SupervisorDashboardRoutingTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_supervisor_sees_supervisor_dashboard(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/supervisor_dashboard.html')

    def test_employee_sees_staff_dashboard(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/staff_dashboard.html')

    def test_owner_sees_owner_dashboard(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/owner_dashboard.html')

    def test_supervisor_dashboard_contains_staff_memberships(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('dashboard'))
        memberships = resp.context['staff_memberships']
        usernames = [m.user.username for m in memberships]
        self.assertIn('employee', usernames)
        self.assertIn('supervisor', usernames)

    def test_supervisor_dashboard_excludes_owners(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('dashboard'))
        memberships = resp.context['staff_memberships']
        usernames = [m.user.username for m in memberships]
        self.assertNotIn('owner', usernames)

class SupervisorScheduleTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        self.stranger = make_user('stranger')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

        start = timezone.now() + timedelta(days=1)
        self.shift = WorkShift.objects.create(
            business=self.business,
            user=self.employee,
            start=start,
            end=start + timedelta(hours=8),
            created_by=self.owner,
        )

    def test_supervisor_can_view_branch_schedule(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('branch_schedule', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_view_branch_schedule(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('branch_schedule', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_stranger_cannot_view_branch_schedule(self):
        self.client.force_login(self.stranger)
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

    def test_supervisor_can_create_shift(self):
        self.client.force_login(self.supervisor)
        start = timezone.now() + timedelta(days=2)
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
        start = timezone.now() + timedelta(days=2)
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

class SupervisorStaffManagementTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_view_staff_redirects_to_dashboard(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('view_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('dashboard', resp.url)

    def test_view_staff_redirects_for_employee_too(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('view_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 302)

    def test_supervisor_can_access_invite_staff(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('invite_staff', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_access_invite_staff(self):
        self.client.force_login(self.employee)
        resp = self.client.get(reverse('invite_staff', args=[self.business.id]))
        self.assertIn(resp.status_code, (302, 403))

    def test_supervisor_cannot_invite_supervisor(self):
        self.client.force_login(self.supervisor)
        self.client.post(reverse('invite_staff', args=[self.business.id]), {
            'first_name': 'New', 'last_name': 'Super',
            'username': 'newsup', 'email': 'newsup@test.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        m = BusinessMembership.objects.filter(user__username='newsup').first()
        if m:
            self.assertEqual(m.role, BusinessMembership.EMPLOYEE)

    def test_owner_can_invite_supervisor(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('invite_staff', args=[self.business.id]), {
            'first_name': 'New', 'last_name': 'Super',
            'username': 'newsup2', 'email': 'newsup2@test.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        m = BusinessMembership.objects.filter(user__username='newsup2').first()
        if m:
            self.assertEqual(m.role, BusinessMembership.SUPERVISOR)

    def test_supervisor_cannot_create_branch(self):
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('create_branch'), {'name': 'New Branch'})
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(Business.objects.filter(name='New Branch').exists())

    def test_stranger_cannot_access_branch_views(self):
        stranger = make_user('stranger')
        self.client.force_login(stranger)
        for url in [
            reverse('branch_schedule', args=[self.business.id]),
            reverse('invite_staff', args=[self.business.id]),
        ]:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (302, 403), msg=f"Expected block for {url}")

class StaffDetailViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = Business.objects.create(name='Test Branch')

        self.owner = User.objects.create_user(username='owner', password='pass1234')
        self.owner_membership = BusinessMembership.objects.create(
            user=self.owner, business=self.business, role=BusinessMembership.OWNER
        )

        self.supervisor = User.objects.create_user(
            username='supervisor', password='pass1234', email='sup@test.com'
        )
        self.supervisor_membership = BusinessMembership.objects.create(
            user=self.supervisor, business=self.business, role=BusinessMembership.SUPERVISOR
        )

        self.employee = User.objects.create_user(
            username='employee', password='pass1234',
            email='emp@test.com', first_name='Jane', last_name='Doe'
        )
        self.employee_membership = BusinessMembership.objects.create(
            user=self.employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )

        self.url = reverse('staff_detail', args=[self.business.id, self.employee_membership.id])

    def test_supervisor_can_view_staff_detail(self):
        self.client.login(username='supervisor', password='pass1234')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Jane')
        self.assertContains(resp, 'emp@test.com')

    def test_staff_detail_updates_profile_and_redirects_to_self(self):
        self.client.login(username='supervisor', password='pass1234')
        resp = self.client.post(self.url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'emp@test.com',
            'phone_number': '0871234567',
            'position': 'Kitchen',
            'supervisor_notes': 'Very reliable.',
        })
        self.assertRedirects(
            resp,
            reverse('staff_detail', args=[self.business.id, self.employee_membership.id])
        )
        profile = StaffProfile.objects.get(membership=self.employee_membership)
        self.assertEqual(profile.phone_number, '0871234567')
        self.assertEqual(profile.position, 'Kitchen')
        self.assertEqual(profile.supervisor_notes, 'Very reliable.')

    def test_owner_can_view_staff_detail(self):
        self.client.login(username='owner', password='pass1234')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_view_other_employee_detail(self):
        other = User.objects.create_user(username='other', password='pass1234')
        other_m = BusinessMembership.objects.create(
            user=other, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        self.client.login(username='other', password='pass1234')
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (302, 403))

    def test_unauthenticated_user_cannot_access_staff_detail(self):
        resp = self.client.get(self.url)
        self.assertRedirects(resp, f'/accounts/login/?next={self.url}')

class AssignRolesTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        self.sup_membership = make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        self.emp_membership = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('assign_roles', args=[self.business.id])

    def test_owner_can_assign_position(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {
            f'position_{self.emp_membership.id}': 'Floor',
        })
        self.assertIn(resp.status_code, (200, 302))
        profile = StaffProfile.objects.get(membership=self.emp_membership)
        self.assertEqual(profile.position, 'Floor')

    def test_supervisor_can_assign_position(self):
        self.client.force_login(self.supervisor)
        resp = self.client.post(self.url, {
            f'position_{self.emp_membership.id}': 'Bar',
        })
        self.assertIn(resp.status_code, (200, 302))
        profile = StaffProfile.objects.get(membership=self.emp_membership)
        self.assertEqual(profile.position, 'Bar')

    def test_employee_cannot_assign_roles(self):
        self.client.force_login(self.employee)
        resp = self.client.post(self.url, {
            f'position_{self.emp_membership.id}': 'Kitchen',
        })
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(StaffProfile.objects.filter(membership=self.emp_membership).exists())

class StaffHoursJsonTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('staff_hours_json', args=[self.business.id, self.employee.id])

    def test_supervisor_can_view_staff_hours_json(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('week_worked', data)
        self.assertIn('month_worked', data)

    def test_owner_can_view_staff_hours_json(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_employee_can_view_own_hours_json(self):
        self.client.force_login(self.employee)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_employee_cannot_view_other_employee_hours_json(self):
        other = make_user('other')
        make_membership(other, self.business, BusinessMembership.EMPLOYEE)
        self.client.force_login(other)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_hours_json_returns_correct_fields(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.url)
        data = resp.json()
        for field in ('name', 'week_start', 'week_end', 'month_start', 'month_end',
                      'week_worked', 'month_worked', 'week_scheduled', 'month_scheduled'):
            self.assertIn(field, data)

class SupervisorClockTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)

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
            user=self.supervisor, clock_out__isnull=True
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
            user=self.supervisor, clock_out__isnull=True
        ).exists())

from unittest.mock import patch
from ..utils import compute_staff_status


@override_settings(USE_TZ=True, TIME_ZONE='UTC')
class ComputeStaffStatusTest(TestCase):

    def setUp(self):
        self.business = make_business('Branch 1')
        self.owner = make_user('owner')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)

        self.emp_in = make_user('emp_in')
        self.emp_late = make_user('emp_late')
        self.emp_grace = make_user('emp_grace')
        self.emp_next = make_user('emp_next')
        self.emp_none = make_user('emp_none')

        for u in [self.emp_in, self.emp_late, self.emp_grace, self.emp_next, self.emp_none]:
            make_membership(u, self.business, BusinessMembership.EMPLOYEE)

    def _aware(self, y, m, d, hh, mm, ss=0):
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime(y, m, d, hh, mm, ss), tz)

    def _run_at(self, fixed_now):
        with patch('django.utils.timezone.now', return_value=fixed_now):
            return compute_staff_status(self.business, minutes=15)

    def test_clocked_in_employee_appears_in_in_staff(self):
        now = self._aware(2026, 3, 4, 10, 0)
        TimeClock.objects.create(
            business=self.business, user=self.emp_in,
            clock_in=now - timedelta(minutes=5), clock_out=None
        )
        status = self._run_at(now)
        in_names = [x['user'].username for x in status['in_staff']]
        self.assertIn('emp_in', in_names)
        self.assertNotIn('emp_in', [x['user'].username for x in status['late_staff']])

    def test_active_shift_past_grace_appears_as_late(self):
        now = self._aware(2026, 3, 4, 10, 0)
        WorkShift.objects.create(
            business=self.business, user=self.emp_late,
            start=now - timedelta(minutes=20), end=now + timedelta(hours=2),
        )
        status = self._run_at(now)
        late_names = [x['user'].username for x in status['late_staff']]
        self.assertIn('emp_late', late_names)

    def test_active_shift_within_grace_appears_in_out_staff(self):
        now = self._aware(2026, 3, 4, 10, 0)
        shift = WorkShift.objects.create(
            business=self.business, user=self.emp_grace,
            start=now - timedelta(minutes=10), end=now + timedelta(hours=2),
        )
        status = self._run_at(now)
        out_items = [x for x in status['out_staff'] if x['user'].username == 'emp_grace']
        self.assertEqual(len(out_items), 1)
        self.assertIsNotNone(out_items[0].get('shift'))

    def test_owner_not_included_in_any_status(self):
        now = self._aware(2026, 3, 4, 10, 0)
        status = self._run_at(now)
        all_names = (
            [x['user'].username for x in status['in_staff']] +
            [x['user'].username for x in status['late_staff']] +
            [x['user'].username for x in status['out_staff']]
        )
        self.assertNotIn('owner', all_names)
