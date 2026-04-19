from datetime import datetime, timedelta, time, date as date_type
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from ..models import Business, BusinessMembership, WorkShift, TimeClock, StaffProfile
from ..views.reports import _build_staff_report_data

User = get_user_model()

# Named constants so a URL rename only needs fixing in one place
OWNER_REPORT = 'download_owner_report'
SUP_REPORT = 'download_supervisor_report'


# Shared fixtures — return both the user and business so callers can build on top
def _setup_owner(username='owner'):
    owner = User.objects.create_user(username=username, password='pass',
                                     first_name='Alice', last_name='Smith')
    business = Business.objects.create(name='Cafe Test')
    BusinessMembership.objects.create(user=owner, business=business, role=BusinessMembership.OWNER)
    return owner, business


def _add_employee(business, username, first, last):
    emp = User.objects.create_user(username=username, password='pass',
                                   first_name=first, last_name=last)
    mem = BusinessMembership.objects.create(user=emp, business=business,
                                            role=BusinessMembership.EMPLOYEE)
    return emp, mem


def _add_supervisor(business, username, first, last):
    sup = User.objects.create_user(username=username, password='pass',
                                   first_name=first, last_name=last)
    mem = BusinessMembership.objects.create(user=sup, business=business,
                                            role=BusinessMembership.SUPERVISOR)
    return sup, mem


# Wraps a naive datetime in the current timezone so DB comparisons are consistent
def _aware(dt):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(dt, tz)


# Creates a WorkShift on a specific date; defaults to a standard 9–17 shift
def _shift(business, user, date, start_h=9, end_h=17):
    return WorkShift.objects.create(
        business=business, user=user,
        start=_aware(datetime(date.year, date.month, date.day, start_h, 0)),
        end=_aware(datetime(date.year, date.month, date.day, end_h, 0)),
    )


# Creates a completed TimeClock entry; shift is optional so lateness can be
# tested independently of whether a WorkShift exists
def _timeclock(business, user, date, in_h, in_m, out_h, out_m, shift=None):
    return TimeClock.objects.create(
        business=business, user=user, shift=shift,
        clock_in=_aware(datetime(date.year, date.month, date.day, in_h, in_m)),
        clock_out=_aware(datetime(date.year, date.month, date.day, out_h, out_m)),
    )


# Returns a [midnight, next-midnight) window for a single day — matches how the
# report view builds its date range from the query-string parameters
def _date_range(d):
    tz = timezone.get_current_timezone()
    from_dt = timezone.make_aware(datetime.combine(d, time.min), tz)
    to_dt = timezone.make_aware(datetime.combine(d + timedelta(days=1), time.min), tz)
    return from_dt, to_dt


# Unit tests for _build_staff_report_data — called directly to verify the
# aggregation logic without going through the full PDF rendering pipeline
@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class BuildReportDataTests(TestCase):
    def setUp(self):
        self.owner, self.business = _setup_owner()
        self.emp, self.mem = _add_employee(self.business, 'emp', 'Bob', 'Jones')
        self.today = timezone.localdate()

    def test_hours_calculated_correctly(self):
        # An 8-hour clock record must produce the correct formatted string and raw seconds
        _timeclock(self.business, self.emp, self.today, 9, 0, 17, 0)
        from_dt, to_dt = _date_range(self.today)
        memberships = BusinessMembership.objects.filter(pk=self.mem.pk).select_related('user', 'profile')
        data = _build_staff_report_data(self.business, memberships, from_dt, to_dt)
        self.assertEqual(data[0]['total_hours'], '8h 00m')
        self.assertEqual(data[0]['total_seconds'], 8 * 3600)

    def test_multiple_timeclocks_summed(self):
        # Hours from separate days within the date range must be accumulated into one total
        yesterday = self.today - timedelta(days=1)
        _timeclock(self.business, self.emp, self.today, 9, 0, 13, 0)
        _timeclock(self.business, self.emp, yesterday, 10, 0, 14, 30)
        tz = timezone.get_current_timezone()
        from_dt = timezone.make_aware(datetime.combine(yesterday, time.min), tz)
        to_dt = timezone.make_aware(datetime.combine(self.today + timedelta(days=1), time.min), tz)
        memberships = BusinessMembership.objects.filter(pk=self.mem.pk).select_related('user', 'profile')
        data = _build_staff_report_data(self.business, memberships, from_dt, to_dt)
        self.assertEqual(data[0]['total_seconds'], (4 * 3600) + (4 * 3600 + 30 * 60))
        self.assertEqual(data[0]['shift_count'], 2)

    def test_late_detection(self):
        # Clock-in 20 minutes after shift start must set is_late=True and minutes_late=20
        ws = _shift(self.business, self.emp, self.today, start_h=9, end_h=17)
        _timeclock(self.business, self.emp, self.today, 9, 20, 17, 0, shift=ws)
        from_dt, to_dt = _date_range(self.today)
        memberships = BusinessMembership.objects.filter(pk=self.mem.pk).select_related('user', 'profile')
        data = _build_staff_report_data(self.business, memberships, from_dt, to_dt)
        self.assertEqual(data[0]['late_count'], 1)
        self.assertTrue(data[0]['entries'][0]['is_late'])
        self.assertEqual(data[0]['entries'][0]['minutes_late'], 20)

    def test_position_included_from_staff_profile(self):
        # The report must surface the position from StaffProfile, not leave it blank
        StaffProfile.objects.create(membership=self.mem, position='Barista')
        _timeclock(self.business, self.emp, self.today, 9, 0, 17, 0)
        from_dt, to_dt = _date_range(self.today)
        memberships = BusinessMembership.objects.filter(pk=self.mem.pk).select_related('user', 'profile')
        data = _build_staff_report_data(self.business, memberships, from_dt, to_dt)
        self.assertEqual(data[0]['position'], 'Barista')


# Integration tests for the owner report view — WeasyHTML is mocked so tests
# don't require a headless browser or real PDF rendering
@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class OwnerReportViewTests(TestCase):
    def setUp(self):
        self.owner, self.business = _setup_owner()
        self.emp, self.mem = _add_employee(self.business, 'emp', 'Bob', 'Jones')
        self.url = reverse(OWNER_REPORT)
        self.today = timezone.localdate()
        self.client.login(username='owner', password='pass')

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 302)

    def test_non_owner_gets_403(self):
        # Employees must not be able to download the owner-level report
        self.client.login(username='emp', password='pass')
        resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 403)

    def test_valid_request_returns_pdf(self):
        # Confirms Content-Type and Content-Disposition so the browser triggers a download
        with patch('checkpoint.views.reports.WeasyHTML') as mock_html, \
             patch('checkpoint.views.reports.WeasyCSS'):
            mock_html.return_value.write_pdf.return_value = b'%PDF-fake'
            resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment', resp['Content-Disposition'])


# Same structure as OwnerReportViewTests but for the per-branch supervisor report,
# which requires supervisor-or-above access to the specific branch
@override_settings(USE_TZ=True, TIME_ZONE="UTC")
class SupervisorReportViewTests(TestCase):
    def setUp(self):
        self.owner, self.business = _setup_owner()
        self.sup, self.sup_mem = _add_supervisor(self.business, 'sup', 'Carol', 'White')
        self.emp, self.emp_mem = _add_employee(self.business, 'emp', 'Bob', 'Jones')
        self.url = reverse(SUP_REPORT, kwargs={'business_id': self.business.pk})
        self.today = timezone.localdate()
        self.client.login(username='sup', password='pass')

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 302)

    def test_non_supervisor_gets_403(self):
        # Plain employees must not be able to download branch reports
        self.client.login(username='emp', password='pass')
        resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 403)

    def test_valid_request_returns_pdf(self):
        with patch('checkpoint.views.reports.WeasyHTML') as mock_html, \
             patch('checkpoint.views.reports.WeasyCSS'):
            mock_html.return_value.write_pdf.return_value = b'%PDF-fake'
            resp = self.client.get(self.url, {'from': str(self.today), 'to': str(self.today)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment', resp['Content-Disposition'])
