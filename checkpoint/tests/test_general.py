import uuid
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, TimeClock, StaffProfile

User = get_user_model()


class SmokeTest(TestCase):
    def test_smoke(self):
        self.assertTrue(True)


class HomePageTest(TestCase):
    def test_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)


class AdminTest(TestCase):
    def test_admin_login_page(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)


class AuthenticationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpassword'
        )

    def test_login(self):
        login_successful = self.client.login(username='testuser', password='testpassword')
        self.assertTrue(login_successful)

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class BusinessModelTest(TestCase):
    def test_business_str(self):
        business = Business.objects.create(name='My Cafe')
        self.assertEqual(str(business), 'My Cafe')


class BusinessMembershipModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='worker', password='pass')
        self.membership = BusinessMembership.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessMembership.EMPLOYEE
        )

    def test_membership_str(self):
        self.assertIn('worker', str(self.membership))
        self.assertIn('Test Business', str(self.membership))

    def test_qr_token_is_valid_uuid(self):
        try:
            uuid.UUID(str(self.membership.qr_token))
        except ValueError:
            self.fail("qr_token is not a valid UUID")

    def test_qr_token_unique_per_membership(self):
        other_user = User.objects.create_user(username='worker2', password='pass')
        other_membership = BusinessMembership.objects.create(
            user=other_user,
            business=self.business,
            role=BusinessMembership.EMPLOYEE
        )
        self.assertNotEqual(self.membership.qr_token, other_membership.qr_token)

    def test_pin_code_generated_on_create(self):
        self.assertIsNotNone(self.membership.pin_code)
        self.assertEqual(len(self.membership.pin_code), 6)

    def test_pin_code_unique_per_membership(self):
        other_user = User.objects.create_user(username='worker3', password='pass')
        other_membership = BusinessMembership.objects.create(
            user=other_user,
            business=self.business,
            role=BusinessMembership.EMPLOYEE
        )
        self.assertNotEqual(self.membership.pin_code, other_membership.pin_code)

    def test_is_owner_property(self):
        owner_user = User.objects.create_user(username='owner', password='pass')
        owner_membership = BusinessMembership.objects.create(
            user=owner_user,
            business=self.business,
            role=BusinessMembership.OWNER
        )
        self.assertTrue(owner_membership.is_owner)
        self.assertFalse(self.membership.is_owner)

    def test_is_supervisor_property(self):
        sup_user = User.objects.create_user(username='sup', password='pass')
        sup_membership = BusinessMembership.objects.create(
            user=sup_user,
            business=self.business,
            role=BusinessMembership.SUPERVISOR
        )
        self.assertTrue(sup_membership.is_supervisor)
        self.assertFalse(self.membership.is_supervisor)

    def test_has_min_role(self):
        owner_user = User.objects.create_user(username='owner2', password='pass')
        owner_m = BusinessMembership.objects.create(
            user=owner_user, business=self.business, role=BusinessMembership.OWNER
        )
        self.assertTrue(owner_m.has_min_role(BusinessMembership.SUPERVISOR))
        self.assertTrue(owner_m.has_min_role(BusinessMembership.EMPLOYEE))
        self.assertFalse(self.membership.has_min_role(BusinessMembership.SUPERVISOR))

    def test_is_supervisor_or_above(self):
        sup_user = User.objects.create_user(username='sup2', password='pass')
        sup_m = BusinessMembership.objects.create(
            user=sup_user, business=self.business, role=BusinessMembership.SUPERVISOR
        )
        self.assertTrue(sup_m.is_supervisor_or_above())
        self.assertFalse(self.membership.is_supervisor_or_above())


class StaffProfileModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='staff', password='pass')
        self.membership = BusinessMembership.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessMembership.EMPLOYEE
        )
        self.profile = StaffProfile.objects.create(
            membership=self.membership,
            phone_number='0871234567',
            position='Kitchen',
            supervisor_notes='Reliable worker.'
        )

    def test_profile_str(self):
        self.assertIn('staff', str(self.profile))
        self.assertIn('Test Business', str(self.profile))

    def test_position_field_stored(self):
        self.assertEqual(self.profile.position, 'Kitchen')

    def test_position_defaults_to_blank(self):
        user2 = User.objects.create_user(username='staff2', password='pass')
        m2 = BusinessMembership.objects.create(
            user=user2, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        profile2 = StaffProfile.objects.create(membership=m2)
        self.assertEqual(profile2.position, '')


class WorkShiftModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='worker', password='pass')
        BusinessMembership.objects.create(
            user=self.user, business=self.business, role=BusinessMembership.EMPLOYEE
        )
        now = timezone.now()
        self.shift = WorkShift.objects.create(
            business=self.business,
            user=self.user,
            start=now,
            end=now + timedelta(hours=8),
        )

    def test_shift_str(self):
        self.assertIn('worker', str(self.shift))
        self.assertIn('Test Business', str(self.shift))


class TimeClockModelTest(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Test Business')
        self.user = User.objects.create_user(username='worker', password='pass')
        BusinessMembership.objects.create(
            user=self.user, business=self.business, role=BusinessMembership.EMPLOYEE
        )

    def test_is_open_when_no_clock_out(self):
        tc = TimeClock.objects.create(
            business=self.business,
            user=self.user,
            clock_in=timezone.now(),
        )
        self.assertTrue(tc.is_open)

    def test_is_not_open_when_clocked_out(self):
        now = timezone.now()
        tc = TimeClock.objects.create(
            business=self.business,
            user=self.user,
            clock_in=now - timedelta(hours=1),
            clock_out=now,
        )
        self.assertFalse(tc.is_open)

    def test_timeclock_str_shows_in_status(self):
        tc = TimeClock.objects.create(
            business=self.business,
            user=self.user,
            clock_in=timezone.now(),
        )
        self.assertIn('IN', str(tc))

    def test_timeclock_str_shows_out_status(self):
        now = timezone.now()
        tc = TimeClock.objects.create(
            business=self.business,
            user=self.user,
            clock_in=now - timedelta(hours=1),
            clock_out=now,
        )
        self.assertIn('OUT', str(tc))
