from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Business, BusinessMembership, WorkShift, TimeClock

User = get_user_model()

# Create your tests here.
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

#Staff tests