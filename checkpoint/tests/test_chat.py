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


# ---------------------------------------------------------------------------
# Access & rate limiting
# ---------------------------------------------------------------------------

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatAccessTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, _ = _setup_owner()
        self.client.login(username='owner', password='pass')

    def test_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.post(self.url, {'message': 'hello'})
        self.assertEqual(response.status_code, 302)

    def test_empty_message_returns_hint(self):
        response = self.client.post(self.url, {'message': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn('answer', response.json())


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

    def test_below_limit_processes_message(self):
        limit = self._set_usage(0)
        self._set_usage(limit - 1)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'something'})
        self.assertFalse(response.json().get('limit_reached', False))

    def test_usage_increments_after_successful_message(self):
        self._set_usage(0)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            self.client.post(self.url, {'message': 'something'})
        count = self.client.session.get(f'chat_{timezone.localdate().isoformat()}', 0)
        self.assertEqual(count, 1)


# ---------------------------------------------------------------------------
# Who is working
# ---------------------------------------------------------------------------

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

    def test_today_keyword_resolves_to_current_date(self):
        today = timezone.localdate()
        _shift(self.business, self.emp, today)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who is working today'})
        self.assertIn('Bob', response.json()['answer'])

    def test_tomorrow_keyword_resolves_correctly(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        _shift(self.business, self.emp, tomorrow)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who is working tomorrow'})
        self.assertIn('Bob', response.json()['answer'])

    def test_yesterday_keyword_resolves_correctly(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        _shift(self.business, self.emp, yesterday)
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': None, 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who worked yesterday'})
        self.assertIn('Bob', response.json()['answer'])

    def test_no_shifts_returns_not_scheduled_message(self):
        today = timezone.localdate()
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': today.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working on {today}'})
        self.assertIn('No one is scheduled', response.json()['answer'])


# ---------------------------------------------------------------------------
# Who is off / not scheduled
# ---------------------------------------------------------------------------

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
        _shift(self.business, self.emp1, monday)  # emp1 has a shift, emp2 does not
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who is not working this week'})
        answer = response.json()['answer']
        self.assertIn('Carol', answer)
        self.assertNotIn('Bob', answer)

    def test_everyone_scheduled_returns_confirmation(self):
        monday = self._this_monday()
        _shift(self.business, self.emp1, monday)
        _shift(self.business, self.emp2, monday)
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who has no shifts this week'})
        self.assertIn('Everyone', response.json()['answer'])

    def test_next_week_off_uses_correct_range(self):
        # No shifts for next week — both should appear
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'next', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'who is off next week'})
        answer = response.json()['answer']
        self.assertIn('Bob', answer)
        self.assertIn('Carol', answer)


# ---------------------------------------------------------------------------
# Shift count
# ---------------------------------------------------------------------------

@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class ChatShiftCountTests(TestCase):
    def setUp(self):
        self.url = reverse(CHAT_API)
        self.owner, self.business = _setup_owner()
        self.emp1, _ = _add_employee(self.business, 'emp1', 'Bob', 'Jones')
        self.emp2, _ = _add_employee(self.business, 'emp2', 'Carol', 'White')
        self.client.login(username='owner', password='pass')

    def _this_monday(self):
        today = timezone.localdate()
        return today - timedelta(days=today.weekday())

    def test_shift_counts_returned_for_all_staff(self):
        monday = self._this_monday()
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

    def test_singular_shift_label(self):
        monday = self._this_monday()
        _shift(self.business, self.emp1, monday)
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'how many shifts this week'})
        answer = response.json()['answer']
        self.assertIn('1 shift', answer)
        self.assertNotIn('1 shifts', answer)

    def test_no_shifts_returns_no_shifts_message(self):
        with patch('checkpoint.views.chat.extract_hours_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'how many shifts this week'})
        self.assertIn('No shifts', response.json()['answer'])


# ---------------------------------------------------------------------------
# Overlapping shifts
# ---------------------------------------------------------------------------

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
        _shift(self.business, self.emp1, target, start_h=9, end_h=17)   # 09:00–17:00
        _shift(self.business, self.emp2, target, start_h=12, end_h=20)  # 12:00–20:00 → overlap
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': target.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working at the same time on {target}'})
        answer = response.json()['answer']
        self.assertIn('Bob', answer)
        self.assertIn('Carol', answer)
        self.assertIn('↔', answer)

    def test_non_overlapping_shifts_returns_no_overlaps(self):
        target = timezone.localdate()
        _shift(self.business, self.emp1, target, start_h=9, end_h=13)   # 09:00–13:00
        _shift(self.business, self.emp2, target, start_h=14, end_h=18)  # 14:00–18:00 → no overlap
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': target.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who is working at the same time on {target}'})
        self.assertIn('No overlapping', response.json()['answer'])

    def test_no_shifts_on_day_returns_no_shifts_message(self):
        target = timezone.localdate()
        with patch('checkpoint.views.chat.extract_schedule_query',
                   return_value={'date': target.isoformat(), 'branch_name': None}):
            response = self.client.post(self.url, {'message': f'who overlaps on {target}'})
        self.assertIn('No shifts', response.json()['answer'])


# ---------------------------------------------------------------------------
# Position query
# ---------------------------------------------------------------------------

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

    def test_no_position_assigned_shows_fallback(self):
        StaffProfile.objects.create(membership=self.mem, position='')
        with patch('checkpoint.views.chat.extract_person_schedule_query',
                   return_value={'person_name': 'Bob', 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'what position is Bob'})
        self.assertIn('No position assigned', response.json()['answer'])

    def test_unknown_person_returns_not_found(self):
        with patch('checkpoint.views.chat.extract_person_schedule_query',
                   return_value={'person_name': 'Zara', 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'what position is Zara'})
        self.assertIn("couldn't find", response.json()['answer'].lower())

    def test_no_person_extracted_returns_hint(self):
        with patch('checkpoint.views.chat.extract_person_schedule_query',
                   return_value={'person_name': None, 'week': 'this', 'branch_name': None}):
            response = self.client.post(self.url, {'message': 'what position'})
        self.assertIn("couldn't work out", response.json()['answer'].lower())
