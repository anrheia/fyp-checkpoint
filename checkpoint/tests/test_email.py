from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ..models import Business, BusinessMembership, WorkShift

User = get_user_model()

def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password='testpass123', **kwargs)


def make_business(name='Test Business'):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)

class InviteStaffViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.com', password='password123'
        )
        self.supervisor = User.objects.create_user(
            username='supervisor', email='supervisor@example.com', password='password123'
        )
        self.business = Business.objects.create(name='Test Business')
        BusinessMembership.objects.create(
            user=self.owner, business=self.business, role=BusinessMembership.OWNER
        )
        BusinessMembership.objects.create(
            user=self.supervisor, business=self.business, role=BusinessMembership.SUPERVISOR
        )
        self.url = reverse('invite_staff', args=[self.business.id])

    def test_redirects_if_not_logged_in(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_returns_403_if_not_member(self):
        outsider = User.objects.create_user(username='outsider', password='password123')
        self.client.force_login(outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_returns_403_if_employee(self):
        employee = User.objects.create_user(username='employee', password='password123')
        BusinessMembership.objects.create(
            user=employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        self.client.force_login(employee)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_access(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_supervisor_can_access(self):
        self.client.force_login(self.supervisor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_owner_can_invite_supervisor(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            'first_name': 'Jane', 'last_name': 'Doe',
            'username': 'janedoe', 'email': 'jane@example.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        self.assertRedirects(response, reverse('dashboard'))
        membership = BusinessMembership.objects.get(user__username='janedoe')
        self.assertEqual(membership.role, BusinessMembership.SUPERVISOR)

    def test_owner_can_invite_employee(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'John', 'last_name': 'Smith',
            'username': 'johnsmith', 'email': 'john@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        membership = BusinessMembership.objects.get(user__username='johnsmith')
        self.assertEqual(membership.role, BusinessMembership.EMPLOYEE)

    def test_supervisor_role_forced_to_employee_when_invited_by_supervisor(self):
        self.client.force_login(self.supervisor)
        self.client.post(self.url, {
            'first_name': 'Sam', 'last_name': 'Lee',
            'username': 'samlee', 'email': 'sam@example.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        membership = BusinessMembership.objects.get(user__username='samlee')
        self.assertEqual(membership.role, BusinessMembership.EMPLOYEE)

    def test_new_user_is_created(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'New', 'last_name': 'User',
            'username': 'newuser', 'email': 'newuser@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_new_user_must_change_password(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'New', 'last_name': 'User',
            'username': 'newuser', 'email': 'newuser@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        membership = BusinessMembership.objects.get(user__username='newuser')
        self.assertTrue(membership.must_change_password)

    def test_invited_user_gets_pin_code(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'New', 'last_name': 'User',
            'username': 'newuser', 'email': 'newuser@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        membership = BusinessMembership.objects.get(user__username='newuser')
        self.assertIsNotNone(membership.pin_code)
        self.assertEqual(len(membership.pin_code), 6)

    def test_invitation_email_is_sent(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'Email', 'last_name': 'Test',
            'username': 'emailtest', 'email': 'emailtest@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('emailtest@example.com', mail.outbox[0].to)
        self.assertIn('Test Business', mail.outbox[0].subject)

    def test_invitation_email_contains_username(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'Email', 'last_name': 'Test',
            'username': 'emailtest', 'email': 'emailtest@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertIn('emailtest', mail.outbox[0].body)

    def test_duplicate_email_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            'first_name': 'Dupe', 'last_name': 'Email',
            'username': 'dupeemail', 'email': 'owner@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'A user with this email already exists.')

    def test_duplicate_username_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            'first_name': 'Dupe', 'last_name': 'Username',
            'username': 'owner', 'email': 'unique@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'username', 'A user with this username already exists.')

    def test_invalid_form_does_not_create_user(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': '', 'last_name': '',
            'username': '', 'email': 'notanemail',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertFalse(User.objects.filter(email='notanemail').exists())

class ShiftNotificationTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.com', password='password123'
        )
        self.employee = User.objects.create_user(
            username='employee', email='employee@example.com', password='password123',
            first_name='Alice'
        )
        self.employee2 = User.objects.create_user(
            username='employee2', email='employee2@example.com', password='password123',
            first_name='Bob'
        )
        self.business = Business.objects.create(name='Test Business')
        BusinessMembership.objects.create(
            user=self.owner, business=self.business, role=BusinessMembership.OWNER
        )
        BusinessMembership.objects.create(
            user=self.employee, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        BusinessMembership.objects.create(
            user=self.employee2, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        self.now = timezone.now()
        self.create_shift_url = reverse('create_shift', args=[self.business.id])
        self.send_url = reverse('send_shift_notifications', args=[self.business.id])

    def _post_shift(self, user, start_offset_hours=24, duration_hours=8):
        start = self.now + timedelta(hours=start_offset_hours)
        end = start + timedelta(hours=duration_hours)
        return self.client.post(self.create_shift_url, {
            'user': user.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': end.strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })

    def test_create_shift_does_not_send_email_immediately(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.assertEqual(len(mail.outbox), 0)

    def test_create_shift_stages_shift_id_in_session(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        session_key = f'pending_shift_notifications_{self.business.id}'
        pending = self.client.session.get(session_key, [])
        self.assertEqual(len(pending), 1)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        self.assertIn(shift.id, pending)

    def test_multiple_shifts_all_staged(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee, start_offset_hours=24)
        self._post_shift(self.employee, start_offset_hours=48)
        self._post_shift(self.employee2, start_offset_hours=24)
        session_key = f'pending_shift_notifications_{self.business.id}'
        pending = self.client.session.get(session_key, [])
        self.assertEqual(len(pending), 3)

    def test_duplicate_shift_id_not_emailed_twice(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        session = self.client.session
        session_key = f'pending_shift_notifications_{self.business.id}'
        session[session_key] = [shift.id, shift.id]
        session.save()
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 1)

    def test_pending_notifications_blocked_for_employee(self):
        self.client.force_login(self.employee)
        response = self.client.get(
            reverse('pending_shift_notifications', args=[self.business.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_send_notifications_fires_one_email_per_employee(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee, start_offset_hours=24)
        self._post_shift(self.employee, start_offset_hours=48)
        self._post_shift(self.employee2, start_offset_hours=24)
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_send_notifications_email_addresses_correct(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self._post_shift(self.employee2)
        self.client.post(self.send_url)
        recipients = {email.to[0] for email in mail.outbox}
        self.assertIn(self.employee.email, recipients)
        self.assertIn(self.employee2.email, recipients)

    def test_send_notifications_email_lists_all_shifts_per_employee(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee, start_offset_hours=24)
        self._post_shift(self.employee, start_offset_hours=48)
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertEqual(body.count('•'), 2)

    def test_send_notifications_clears_session_queue(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.client.post(self.send_url)
        session_key = f'pending_shift_notifications_{self.business.id}'
        pending = self.client.session.get(session_key, [])
        self.assertEqual(pending, [])

    def test_send_notifications_with_empty_queue_sends_no_email(self):
        self.client.force_login(self.owner)
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_notifications_skips_users_without_email(self):
        no_email_user = User.objects.create_user(username='noemail', password='pass', email='')
        BusinessMembership.objects.create(
            user=no_email_user, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        self.client.force_login(self.owner)
        self._post_shift(no_email_user)
        self._post_shift(self.employee)
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.employee.email, mail.outbox[0].to)

    def test_delete_staged_shift_removes_it_from_session(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        delete_url = reverse('delete_shift', args=[self.business.id, shift.id])
        self.client.post(delete_url)
        session_key = f'pending_shift_notifications_{self.business.id}'
        pending = self.client.session.get(session_key, [])
        self.assertNotIn(shift.id, pending)

    def test_delete_staged_shift_sends_no_removal_email(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        delete_url = reverse('delete_shift', args=[self.business.id, shift.id])
        self.client.post(delete_url)
        self.assertEqual(len(mail.outbox), 0)

    def test_delete_notified_shift_sends_removal_email(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.client.post(self.send_url)
        mail.outbox.clear()
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        delete_url = reverse('delete_shift', args=[self.business.id, shift.id])
        self.client.post(delete_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.employee.email, mail.outbox[0].to)
        self.assertIn('removed', mail.outbox[0].subject.lower())

    def test_delete_shift_actually_removes_it(self):
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        delete_url = reverse('delete_shift', args=[self.business.id, shift.id])
        self.client.post(delete_url)
        self.assertFalse(WorkShift.objects.filter(id=shift.id).exists())
