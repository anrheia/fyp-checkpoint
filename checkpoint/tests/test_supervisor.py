from datetime import timedelta

from django.test import TestCase
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

class SupervisorDashboardRoutingTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_supervisor_sees_supervisor_dashboard(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/supervisor_dashboard.html')

class SupervisorScheduleTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        start = timezone.now() + timedelta(days=1)
        self.shift = WorkShift.objects.create(
            business=self.business, user=self.employee,
            start=start, end=start + timedelta(hours=8),
            created_by=self.owner,
        )

    def test_supervisor_can_view_branch_schedule(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('branch_schedule', args=[self.business.id]))
        self.assertEqual(resp.status_code, 200)

    def test_supervisor_can_create_shift(self):
        self.client.force_login(self.supervisor)
        start = timezone.now() + timedelta(days=2)
        self.client.post(reverse('create_shift', args=[self.business.id]), {
            'user': self.employee.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': (start + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })
        self.assertTrue(WorkShift.objects.filter(created_by=self.supervisor).exists())

    def test_supervisor_can_delete_shift(self):
        self.client.force_login(self.supervisor)
        self.client.post(reverse('delete_shift', args=[self.business.id, self.shift.id]))
        self.assertFalse(WorkShift.objects.filter(id=self.shift.id).exists())

class SupervisorStaffManagementTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)

    def test_supervisor_cannot_create_branch(self):
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('create_branch'), {'name': 'New Branch'})
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(Business.objects.filter(name='New Branch').exists())

class StaffDetailViewTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.supervisor = User.objects.create_user(username='supervisor', password='pass1234')
        self.employee = User.objects.create_user(username='employee', password='pass1234',
                                                  first_name='Jane', last_name='Doe',
                                                  email='emp@test.com')
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        self.emp_mem = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('staff_detail', args=[self.business.id, self.emp_mem.id])

    def test_supervisor_can_view_staff_detail(self):
        self.client.login(username='supervisor', password='pass1234')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Jane')

    def test_employee_cannot_view_other_employee_detail(self):
        other = User.objects.create_user(username='other', password='pass1234')
        make_membership(other, self.business, BusinessMembership.EMPLOYEE)
        self.client.login(username='other', password='pass1234')
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (302, 403))

class AssignRolesTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        self.emp_mem = make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('assign_roles', args=[self.business.id])

    def test_supervisor_can_assign_position(self):
        self.client.force_login(self.supervisor)
        self.client.post(self.url, {f'position_{self.emp_mem.id}': 'Bar'})
        self.assertEqual(StaffProfile.objects.get(membership=self.emp_mem).position, 'Bar')

class StaffHoursJsonTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.supervisor = make_user('supervisor')
        self.employee = make_user('employee')
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('staff_hours_json', args=[self.business.id, self.employee.id])

    def test_supervisor_can_view_staff_hours(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('week_worked', resp.json())

class SupervisorClockTest(TestCase):
    def setUp(self):
        self.business = make_business()
        self.owner = make_user('owner')
        self.supervisor = make_user('supervisor')
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)

    def test_supervisor_can_clock_in(self):
        now = timezone.now()
        WorkShift.objects.create(business=self.business, user=self.supervisor,
                                 start=now - timedelta(minutes=5),
                                 end=now + timedelta(hours=4), created_by=self.owner)
        self.client.force_login(self.supervisor)
        self.client.post(reverse('clock_in', args=[self.business.id]))
        self.assertTrue(TimeClock.objects.filter(user=self.supervisor, clock_out__isnull=True).exists())

    def test_supervisor_can_clock_out(self):
        TimeClock.objects.create(business=self.business, user=self.supervisor,
                                 clock_in=timezone.now() - timedelta(hours=1), clock_out=None)
        self.client.force_login(self.supervisor)
        self.client.post(reverse('clock_out', args=[self.business.id]))
        self.assertFalse(TimeClock.objects.filter(user=self.supervisor, clock_out__isnull=True).exists())
