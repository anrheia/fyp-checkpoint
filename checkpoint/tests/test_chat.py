import time
from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, StaffProfile

User = get_user_model()

CHAT_API = 'schedule_chat_api'


def _setup_owner(username='owner'):
    owner = User.objects.create_user(username=username, password='pass',
                                     first_name='Alice', last_name='Smith')
    business = Business.objects.create(name='Cafe Nero')
    BusinessMembership.objects.create(user=owner, business=business, role=BusinessMembership.OWNER)
    return owner, business


def _add_employee(business, username, first, last):
    emp = User.objects.create_user(username=username, password='pass',
                                   first_name=first, last_name=last)
    mem = BusinessMembership.objects.create(user=emp, business=business,
                                            role=BusinessMembership.EMPLOYEE)
    return emp, mem


def _shift(business, user, date, start_h=9, end_h=17):
    tz = timezone.get_current_timezone()
    return WorkShift.objects.create(
        business=business, user=user,
        start=timezone.make_aware(datetime(date.year, date.month, date.day, start_h, 0), tz),
        end=timezone.make_aware(datetime(date.year, date.month, date.day, end_h, 0), tz),
    )

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatRateLimitTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, _ = _setup_owner()
        self.client.login(username='owner', password='pass')

    def _set_usage(self, count):
        from checkpoint.views.chat import DAILY_CHAT_LIMIT as LIMIT
        session = self.client.session
        session[f'chat_{timezone.localdate().isoformat()}'] = count
        session.save()
        return LIMIT

    def test_at_limit_returns_limit_reached(self):
        limit = self._set_usage(30)
        self._set_usage(limit)
        response = self.client.post(self.url, {'message': 'hello'})
        data = response.json()
        self.assertTrue(data.get('limit_reached'))
        self.assertIn('limit', data['answer'].lower())

    def test_usage_increments_after_successful_message(self):
        self._set_usage(0)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            self.client.post(self.url, {'message': 'something'})
        count = self.client.session.get(f'chat_{timezone.localdate().isoformat()}', 0)
        self.assertEqual(count, 1)
@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatWhoIsWorkingTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp, _ = _add_employee(self.business, 'emp', 'Bob', 'Jones')
        self.client.login(username='owner', password='pass')

    def test_specific_date_returns_scheduled_employee(self):
        today = timezone.localdate()
        _shift(self.business, self.emp, today)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': today.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working on {today}'})
        self.assertIn('Bob', response.json()['answer'])

    def test_no_shifts_returns_not_scheduled_message(self):
        today = timezone.localdate()
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': today.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working on {today}'})
        self.assertIn('No one is scheduled', response.json()['answer'])

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatWhoIsOffTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp1, _ = _add_employee(self.business, 'emp1', 'Bob', 'Jones')
        self.emp2, _ = _add_employee(self.business, 'emp2', 'Carol', 'White')
        self.client.login(username='owner', password='pass')

    def _this_monday(self):
        today = timezone.localdate()
        return today - timedelta(days=today.weekday())

    def test_unscheduled_employee_appears_in_off_list(self):
        monday = self._this_monday()
        _shift(self.business, self.emp1, monday)
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who is not working this week'})
        answer = response.json()['answer']
        self.assertIn('Carol', answer)
        self.assertNotIn('Bob', answer)

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatShiftCountTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp1, _ = _add_employee(self.business, 'emp1', 'Bob', 'Jones')
        self.emp2, _ = _add_employee(self.business, 'emp2', 'Carol', 'White')
        self.client.login(username='owner', password='pass')

    def test_shift_counts_returned_for_all_staff(self):
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        for i in range(3):
            _shift(self.business, self.emp1, monday + timedelta(days=i))
        _shift(self.business, self.emp2, monday)
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'how many shifts this week'})
        answer = response.json()['answer']
        self.assertIn('Bob', answer)
        self.assertIn('3', answer)
        self.assertIn('Carol', answer)
        self.assertIn('1', answer)

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatOverlappingShiftsTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp1, _ = _add_employee(self.business, 'emp1', 'Bob', 'Jones')
        self.emp2, _ = _add_employee(self.business, 'emp2', 'Carol', 'White')
        self.client.login(username='owner', password='pass')

    def test_overlapping_shifts_shows_both_names(self):
        target = timezone.localdate()
        _shift(self.business, self.emp1, target, start_h=9, end_h=17)
        _shift(self.business, self.emp2, target, start_h=12, end_h=20)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': target.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working at the same time on {target}'})
        answer = response.json()['answer']
        self.assertIn('Bob', answer)
        self.assertIn('Carol', answer)
        self.assertIn('↔', answer)

    def test_non_overlapping_shifts_returns_no_overlaps(self):
        target = timezone.localdate()
        _shift(self.business, self.emp1, target, start_h=9, end_h=13)
        _shift(self.business, self.emp2, target, start_h=14, end_h=18)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': target.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working at the same time on {target}'})
        self.assertIn('No overlapping', response.json()['answer'])

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatPositionTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp, self.mem = _add_employee(self.business, 'emp', 'Bob', 'Jones')
        self.client.login(username='owner', password='pass')

    def test_position_returned_when_assigned(self):
        StaffProfile.objects.create(membership=self.mem, position='Kitchen')
        with patch('checkpoint.views.chat.extract_person_schedule_query',
                   return_value={'person_name': 'Bob', 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'what position is Bob'})
        answer = response.json()['answer']
        self.assertIn('Kitchen', answer)
        self.assertIn('Bob', answer)

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatResponseTimingTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.client.login(username='owner', password='pass')

    def test_response_returns_within_one_second(self):
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': timezone.localdate().isoformat(), 'branch_name': None}):
            start = time.time()
            self.client.post(self.url, {'message': 'who is working today'})
            elapsed = time.time() - start
        self.assertLess(elapsed, 1.0, f"Response took {elapsed:.2f}s — expected under 1s")

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatErrorMessageTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, _ = _setup_owner()
        self.client.login(username='owner', password='pass')

    def test_unrecognised_query_returns_valid_json_answer(self):
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'banana'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('answer', data)
        self.assertIsInstance(data['answer'], str)
        self.assertGreater(len(data['answer']), 0)
