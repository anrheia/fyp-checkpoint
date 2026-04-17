import uuid
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, TimeClock, StaffProfile

User = get_user_model()

class HomePageTest(TestCase):
    def test_home_page_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

class AuthenticationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpassword')

    def test_login_with_valid_credentials(self):
        self.assertTrue(self.client.login(username='testuser', password='testpassword'))

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

class BusinessMembershipModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='worker', password='pass')
        self.membership = BusinessMembership.objects.create(
            user=self.user, business=self.business, role=BusinessMembership.EMPLOYEE
        )

    def test_qr_token_is_valid_uuid(self):
        try:
            uuid.UUID(str(self.membership.qr_token))
        except ValueError:
            self.fail("qr_token is not a valid UUID")

    def test_pin_code_generated_on_create(self):
        self.assertIsNotNone(self.membership.pin_code)
        self.assertEqual(len(self.membership.pin_code), 6)

    def test_is_owner_property(self):
        owner = User.objects.create_user(username='owner', password='pass')
        owner_mem = BusinessMembership.objects.create(
            user=owner, business=self.business, role=BusinessMembership.OWNER
        )
        self.assertTrue(owner_mem.is_owner)
        self.assertFalse(self.membership.is_owner)

    def test_is_supervisor_property(self):
        sup = User.objects.create_user(username='sup', password='pass')
        sup_mem = BusinessMembership.objects.create(
            user=sup, business=self.business, role=BusinessMembership.SUPERVISOR
        )
        self.assertTrue(sup_mem.is_supervisor)
        self.assertFalse(self.membership.is_supervisor)

class StaffProfileModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='staff', password='pass')
        self.membership = BusinessMembership.objects.create(
            user=self.user, business=self.business, role=BusinessMembership.EMPLOYEE
        )

    def test_position_field_stored(self):
        profile = StaffProfile.objects.create(membership=self.membership, position='Kitchen')
        self.assertEqual(profile.position, 'Kitchen')

    def test_position_defaults_to_blank(self):
        profile = StaffProfile.objects.create(membership=self.membership)
        self.assertEqual(profile.position, '')

class TimeClockModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='worker', password='pass')
        BusinessMembership.objects.create(
            user=self.user, business=self.business, role=BusinessMembership.EMPLOYEE
        )

    def test_is_open_when_no_clock_out(self):
        tc = TimeClock.objects.create(business=self.business, user=self.user,
                                      clock_in=timezone.now())
        self.assertTrue(tc.is_open)

    def test_is_not_open_when_clocked_out(self):
        now = timezone.now()
        tc = TimeClock.objects.create(business=self.business, user=self.user,
                                      clock_in=now - timedelta(hours=1), clock_out=now)
        self.assertFalse(tc.is_open)
