from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from unittest.mock import patch
from .models import Business, BusinessMembership

User = get_user_model()


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
        self.owner_membership = BusinessMembership.objects.create(
            user=self.owner, business=self.business, role=BusinessMembership.OWNER
        )
        self.supervisor_membership = BusinessMembership.objects.create(
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
            'first_name': 'Jane',
            'last_name': 'Doe',
            'username': 'janedoe',
            'email': 'jane@example.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        self.assertRedirects(response, reverse('dashboard'))
        membership = BusinessMembership.objects.get(user__username='janedoe')
        self.assertEqual(membership.role, BusinessMembership.SUPERVISOR)

    def test_owner_can_invite_employee(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'John',
            'last_name': 'Smith',
            'username': 'johnsmith',
            'email': 'john@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        membership = BusinessMembership.objects.get(user__username='johnsmith')
        self.assertEqual(membership.role, BusinessMembership.EMPLOYEE)

    def test_supervisor_role_forced_to_employee(self):
        """Supervisors cannot invite other supervisors — role should be forced to employee."""
        self.client.force_login(self.supervisor)
        self.client.post(self.url, {
            'first_name': 'Sam',
            'last_name': 'Lee',
            'username': 'samlee',
            'email': 'sam@example.com',
            'role': BusinessMembership.SUPERVISOR,
        })
        membership = BusinessMembership.objects.get(user__username='samlee')
        self.assertEqual(membership.role, BusinessMembership.EMPLOYEE)

    def test_new_user_is_created(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'New',
            'last_name': 'User',
            'username': 'newuser',
            'email': 'newuser@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_new_user_must_change_password(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'New',
            'last_name': 'User',
            'username': 'newuser',
            'email': 'newuser@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        membership = BusinessMembership.objects.get(user__username='newuser')
        self.assertTrue(membership.must_change_password)

    def test_invitation_email_is_sent(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'Email',
            'last_name': 'Test',
            'username': 'emailtest',
            'email': 'emailtest@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('emailtest@example.com', mail.outbox[0].to)
        self.assertIn('Test Business', mail.outbox[0].subject)

    def test_invitation_email_contains_username(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': 'Email',
            'last_name': 'Test',
            'username': 'emailtest',
            'email': 'emailtest@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertIn('emailtest', mail.outbox[0].body)

    def test_duplicate_email_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            'first_name': 'Dupe',
            'last_name': 'Email',
            'username': 'dupeemail',
            'email': 'owner@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'A user with this email already exists.')

    def test_duplicate_username_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {
            'first_name': 'Dupe',
            'last_name': 'Username',
            'username': 'owner',
            'email': 'unique@example.com',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'username', 'A user with this username already exists.')

    def test_invalid_form_does_not_create_user(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {
            'first_name': '',
            'last_name': '',
            'username': '',
            'email': 'notanemail',
            'role': BusinessMembership.EMPLOYEE,
        })
        self.assertFalse(User.objects.filter(email='notanemail').exists())