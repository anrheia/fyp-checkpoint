from datetime import datetime, time, timedelta, date as date_type

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML as WeasyHTML, CSS as WeasyCSS

from ..models import Business, BusinessMembership, TimeClock
from ..utils import get_supervisor_membership


def _build_staff_report_data(business, staff_memberships, from_dt, to_dt):
    # Builds per-staff attendance rows for the date range; marks a clock-in as late if >15 min after shift start
    LATE_THRESHOLD = timedelta(minutes=15)
    tz = timezone.get_current_timezone()
    staff_data = []

    for m in staff_memberships:
        timeclocks = (
            TimeClock.objects
            .filter(
                business=business,
                user=m.user,
                clock_in__gte=from_dt,
                clock_in__lt=to_dt,
                clock_out__isnull=False,
            )
            .select_related('shift')
            .order_by('clock_in')
        )

        entries = []
        total_seconds = 0
        late_count = 0

        for tc in timeclocks:
            duration = tc.clock_out - tc.clock_in
            total_seconds += int(duration.total_seconds())
            is_late = False
            minutes_late = 0
            if tc.shift:
                diff = tc.clock_in - tc.shift.start
                if diff > LATE_THRESHOLD:
                    is_late = True
                    minutes_late = int(diff.total_seconds() / 60)
                    late_count += 1

            dur_h = int(duration.total_seconds()) // 3600
            dur_m = (int(duration.total_seconds()) % 3600) // 60
            entries.append({
                'date': timezone.localtime(tc.clock_in, tz).strftime('%a %d %b %Y'),
                'shift_start': timezone.localtime(tc.shift.start, tz).strftime('%H:%M') if tc.shift else '—',
                'clock_in': timezone.localtime(tc.clock_in, tz).strftime('%H:%M'),
                'clock_out': timezone.localtime(tc.clock_out, tz).strftime('%H:%M'),
                'duration': f"{dur_h}h {dur_m:02d}m",
                'is_late': is_late,
                'minutes_late': minutes_late,
            })

        total_h = total_seconds // 3600
        total_m = (total_seconds % 3600) // 60
        position = ''
        try:
            position = m.profile.position
        except Exception:
            pass

        staff_data.append({
            'name': m.user.get_full_name() or m.user.username,
            'position': position,
            'role': m.get_role_display(),
            'entries': entries,
            'total_hours': f"{total_h}h {total_m:02d}m",
            'total_seconds': total_seconds,
            'late_count': late_count,
            'shift_count': len(entries),
        })

    return staff_data


@login_required
def download_supervisor_report(request, business_id):
    # Generates and streams a PDF attendance report for a single branch over the requested date range
    _, business, error = get_supervisor_membership(request, business_id)
    if error:
        return error

    from_str = request.GET.get('from', '')
    to_str = request.GET.get('to', '')
    try:
        from_date = date_type.fromisoformat(from_str)
        to_date = date_type.fromisoformat(to_str)
    except (ValueError, TypeError):
        return HttpResponse("Invalid date range.", status=400)

    if from_date > to_date:
        return HttpResponse("'From' date must be before 'to' date.", status=400)

    tz = timezone.get_current_timezone()
    from_dt = timezone.make_aware(datetime.combine(from_date, time.min), tz)
    to_dt = timezone.make_aware(datetime.combine(to_date + timedelta(days=1), time.min), tz)

    staff_memberships = (
        BusinessMembership.objects
        .filter(business=business, role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR])
        .select_related('user', 'profile')
        .order_by('user__last_name', 'user__first_name')
    )

    staff_data = _build_staff_report_data(business, staff_memberships, from_dt, to_dt)

    total_branch_seconds = sum(s['total_seconds'] for s in staff_data)
    total_branch_h = total_branch_seconds // 3600
    total_branch_m = (total_branch_seconds % 3600) // 60

    context = {
        'business': business,
        'from_date': from_date,
        'to_date': to_date,
        'staff_data': staff_data,
        'total_hours': f"{total_branch_h}h {total_branch_m:02d}m",
        'total_lates': sum(s['late_count'] for s in staff_data),
        'total_shifts': sum(s['shift_count'] for s in staff_data),
        'generated': timezone.localtime(timezone.now(), tz).strftime('%d %b %Y %H:%M'),
    }

    html_str = render_to_string('reports/supervisor_report.html', context, request=request)
    css = WeasyCSS(filename=str(django_settings.BASE_DIR / 'checkpoint' / 'static' / 'css' / 'report.css'))
    pdf = WeasyHTML(string=html_str).write_pdf(stylesheets=[css])

    filename = f"{business.name}_report_{from_date}_{to_date}.pdf".replace(' ', '_')
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def download_owner_report(request):
    # Same as the supervisor report but covers all branches the owner manages, with an overall summary
    owner_memberships = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).select_related('business')

    if not owner_memberships.exists():
        return HttpResponse("Access denied.", status=403)

    from_str = request.GET.get('from', '')
    to_str = request.GET.get('to', '')
    try:
        from_date = date_type.fromisoformat(from_str)
        to_date = date_type.fromisoformat(to_str)
    except (ValueError, TypeError):
        return HttpResponse("Invalid date range.", status=400)

    if from_date > to_date:
        return HttpResponse("'From' date must be before 'to' date.", status=400)

    tz = timezone.get_current_timezone()
    from_dt = timezone.make_aware(datetime.combine(from_date, time.min), tz)
    to_dt = timezone.make_aware(datetime.combine(to_date + timedelta(days=1), time.min), tz)

    branches_data = []
    for om in owner_memberships:
        business = om.business
        staff_memberships = (
            BusinessMembership.objects
            .filter(business=business, role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR])
            .select_related('user', 'profile')
            .order_by('user__last_name', 'user__first_name')
        )
        staff_data = _build_staff_report_data(business, staff_memberships, from_dt, to_dt)

        branch_seconds = sum(s['total_seconds'] for s in staff_data)
        branch_h = branch_seconds // 3600
        branch_m = (branch_seconds % 3600) // 60

        branches_data.append({
            'business': business,
            'staff_data': staff_data,
            'total_hours': f"{branch_h}h {branch_m:02d}m",
            'total_lates': sum(s['late_count'] for s in staff_data),
            'total_shifts': sum(s['shift_count'] for s in staff_data),
        })

    overall_seconds = sum(b['staff_data'][i]['total_seconds'] for b in branches_data for i in range(len(b['staff_data'])))
    overall_h = overall_seconds // 3600
    overall_m = (overall_seconds % 3600) // 60

    context = {
        'owner': request.user,
        'from_date': from_date,
        'to_date': to_date,
        'branches_data': branches_data,
        'overall_hours': f"{overall_h}h {overall_m:02d}m",
        'overall_lates': sum(b['total_lates'] for b in branches_data),
        'overall_shifts': sum(b['total_shifts'] for b in branches_data),
        'generated': timezone.localtime(timezone.now(), tz).strftime('%d %b %Y %H:%M'),
    }

    html_str = render_to_string('reports/owner_report.html', context, request=request)
    css = WeasyCSS(filename=str(django_settings.BASE_DIR / 'checkpoint' / 'static' / 'css' / 'report.css'))
    pdf = WeasyHTML(string=html_str).write_pdf(stylesheets=[css])

    filename = f"CheckPoint_owner_report_{from_date}_{to_date}.pdf".replace(' ', '_')
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
