from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ..models import Business, BusinessMembership, WorkShift

User = get_user_model()


# Shared helpers so each test class doesn't repeat boilerplate setup
def make_user(username, **kwargs):
    return User.objects.create_user(username=username, password='testpass123', **kwargs)


def make_business(name='Test Business'):
    return Business.objects.create(name=name)


def make_membership(user, business, role=BusinessMembership.EMPLOYEE):
    return BusinessMembership.objects.create(user=user, business=business, role=role)


# Tests for the invite_staff view — covers access control and the invitation email
class InviteStaffViewTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner', email='owner@example.com')
        self.supervisor = make_user('supervisor', email='supervisor@example.com')
        self.employee = make_user('employee', email='employee@example.com')
        self.business = make_business()
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.supervisor, self.business, BusinessMembership.SUPERVISOR)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        self.url = reverse('invite_staff', args=[self.business.id])

    def test_unauthenticated_redirects_to_login(self):
        # Guests should be bounced to login, not see a 403 or 500
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_employee_cannot_access(self):
        # invite_staff is owner-only; employees must be rejected
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_supervisor_cannot_access(self):
        # Supervisors can manage staff but cannot create new accounts
        self.client.force_login(self.supervisor)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_owner_can_access(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_owner_can_invite_employee(self):
        # Confirms the membership is created with the correct role
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'John', 'last_name': 'Smith',
            'username': 'johnsmith', 'email': 'john@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        mem = BusinessMembership.objects.get(user__username='johnsmith')
        self.assertEqual(mem.role, BusinessMembership.EMPLOYEE)

    def test_invitation_email_is_sent(self):
        # A welcome email with login credentials must be dispatched on successful invite
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'Email', 'last_name': 'Test',
            'username': 'emailtest', 'email': 'emailtest@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('emailtest@example.com', mail.outbox[0].to)

    def test_duplicate_email_rejected(self):
        # Using an email that already belongs to another account should re-render the form with an error
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {
            'first_name': 'Dupe', 'last_name': 'Email',
            'username': 'dupeemail', 'email': 'owner@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context['form'], 'email', 'A user with this email already exists.')


# Tests for the two-step shift notification flow:
# shifts are queued in the session when created, then batched into one email per
# employee when the owner explicitly sends notifications
class ShiftNotificationTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner', email='owner@example.com')
        self.employee = make_user('employee', email='employee@example.com', first_name='Alice')
        self.employee2 = make_user('employee2', email='employee2@example.com', first_name='Bob')
        self.business = make_business()
        make_membership(self.owner, self.business, BusinessMembership.OWNER)
        make_membership(self.employee, self.business, BusinessMembership.EMPLOYEE)
        make_membership(self.employee2, self.business, BusinessMembership.EMPLOYEE)
        self.now = timezone.now()
        self.create_url = reverse('create_shift', args=[self.business.id])
        self.send_url = reverse('send_shift_notifications', args=[self.business.id])

    # Helper that POSTs a single shift for a given user, offset into the future
    def _post_shift(self, user, offset_hours=24):
        start = self.now + timedelta(hours=offset_hours)
        return self.client.post(self.create_url, {
            'user': user.id,
            'start': start.strftime('%Y-%m-%dT%H:%M'),
            'end': (start + timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M'),
            'notes': '',
        })

    def test_create_shift_does_not_send_email_immediately(self):
        # Emails are batched, so no mail should go out at creation time
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.assertEqual(len(mail.outbox), 0)

    def test_create_shift_stages_shift_id_in_session(self):
        # The new shift ID must appear in the session queue for later dispatch
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        pending = self.client.session.get(f'pending_shift_notifications_{self.business.id}', [])
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        self.assertIn(shift.id, pending)

    def test_send_notifications_fires_one_email_per_employee(self):
        # Two shifts for Alice and one for Bob → two emails (one per person, not per shift)
        self.client.force_login(self.owner)
        self._post_shift(self.employee, offset_hours=24)
        self._post_shift(self.employee, offset_hours=48)
        self._post_shift(self.employee2, offset_hours=24)
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_send_notifications_clears_session_queue(self):
        # After sending, the queue must be empty so shifts aren't notified twice
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.client.post(self.send_url)
        pending = self.client.session.get(f'pending_shift_notifications_{self.business.id}', [])
        self.assertEqual(pending, [])

    def test_delete_notified_shift_sends_removal_email(self):
        # Deleting a shift that was already notified should email the employee about the cancellation
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        self.client.post(self.send_url)
        mail.outbox.clear()
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        self.client.post(reverse('delete_shift', args=[self.business.id, shift.id]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.employee.email, mail.outbox[0].to)

    def test_delete_shift_removes_it_from_db(self):
        # Sanity check that the shift record is actually gone after deletion
        self.client.force_login(self.owner)
        self._post_shift(self.employee)
        shift = WorkShift.objects.filter(user=self.employee, business=self.business).first()
        self.client.post(reverse('delete_shift', args=[self.business.id, shift.id]))
        self.assertFalse(WorkShift.objects.filter(id=shift.id).exists())
