from datetime import datetime, timedelta, time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import F, DurationField, ExpressionWrapper, DateTimeField, Sum, Value
from django.db.models.functions import Coalesce, Greatest, Least
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Business, BusinessMembership, TimeClock, WorkShift
from ..utils import get_membership

User = get_user_model()


@login_required
@require_POST
def clock_in(request, business_id):
    _, business, error_response = get_membership(request, business_id)
    if error_response:
        return error_response

    now = timezone.now()

    if TimeClock.objects.filter(
        business=business,
        user=request.user,
        clock_out__isnull=True
    ).exists():
        messages.error(request, "You are already clocked in.")
        return redirect("dashboard")

    active_shift = WorkShift.objects.filter(
        business=business,
        user=request.user,
        start__lte=now,
        end__gte=now
    ).order_by("start").first()

    if not active_shift:
        messages.error(request, "You can only clock in during your scheduled shift.")
        return redirect("dashboard")

    if TimeClock.objects.filter(
        business=business,
        user=request.user,
        shift=active_shift
    ).exists():
        messages.error(request, "You have already clocked in for this shift.")
        return redirect("dashboard")

    TimeClock.objects.create(
        business=business,
        user=request.user,
        shift=active_shift,
        clock_in=now
    )

    messages.success(request, "Clocked in successfully.")
    return redirect("dashboard")


@login_required
@require_POST
def clock_out(request, business_id):
    membership, business, error_response = get_membership(request, business_id)
    if error_response:
        return error_response

    now = timezone.now()

    open_clock = TimeClock.objects.filter(
        business=business,
        user=request.user,
        clock_out__isnull=True
    ).order_by("-clock_in").first()

    if not open_clock:
        messages.error(request, "You are not clocked in.")
        return redirect("dashboard")

    open_clock.clock_out = now
    open_clock.save(update_fields=["clock_out"])

    messages.success(request, "Clocked out successfully.")
    return redirect("dashboard")


def staff_branch_shifts_json(request, business_id):
    from ..utils import shift_to_dict
    _, business, error_response = get_membership(request, business_id, json=True)

    if error_response:
        return error_response

    shifts = (
        WorkShift.objects.filter(business=business, user=request.user)
        .select_related('user')
        .order_by('start')
    )

    data = [shift_to_dict(shift) for shift in shifts]
    return JsonResponse(data, safe=False)


@login_required
def my_hours(request, business_id):
    membership, business, error_response = get_membership(request, business_id, json=True)
    if error_response:
        return error_response

    today = timezone.localdate()
    tz = timezone.get_current_timezone()

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)

    month_start = today.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    def start_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.min), tz)

    week_start_dt = start_of_day(week_start)
    week_end_dt = start_of_day(week_end)
    month_start_dt = start_of_day(month_start)
    month_end_dt = start_of_day(month_end)

    duration_expr = ExpressionWrapper(
        F('clock_out') - F('clock_in'),
        output_field=DurationField()
    )

    def worked_total_for_range(start_dt, end_dt):
        qs = TimeClock.objects.filter(
            business=business,
            user=request.user,
            clock_out__isnull=False,
            clock_in__lt=end_dt,
            clock_out__gt=start_dt,
        )
        return qs.aggregate(
            total=Coalesce(
                Sum(duration_expr),
                Value(timedelta(0)),
                output_field=DurationField(),
            )
        )["total"]

    def scheduled_total_for_range(start_dt, end_dt):
        qs = (
            WorkShift.objects
            .filter(
                business=business,
                user=request.user,
                start__lt=end_dt,
                end__gt=start_dt,
            )
            .annotate(
                overlap=ExpressionWrapper(
                    Least(F("end"), Value(end_dt, output_field=DateTimeField()))
                    - Greatest(F("start"), Value(start_dt, output_field=DateTimeField())),
                    output_field=DurationField(),
                )
            )
            .filter(overlap__gt=timedelta(0))
        )
        return qs.aggregate(
            total=Coalesce(
                Sum("overlap"),
                Value(timedelta(0)),
                output_field=DurationField(),
            )
        )["total"]

    week_worked = worked_total_for_range(week_start_dt, week_end_dt)
    month_worked = worked_total_for_range(month_start_dt, month_end_dt)
    week_scheduled = scheduled_total_for_range(week_start_dt, week_end_dt)
    month_scheduled = scheduled_total_for_range(month_start_dt, month_end_dt)

    def hours_minutes(td):
        seconds = int(td.total_seconds())
        return seconds // 3600, (seconds % 3600) // 60

    week_worked_h, week_worked_m = hours_minutes(week_worked)
    month_worked_h, month_worked_m = hours_minutes(month_worked)
    week_sched_h, week_sched_m = hours_minutes(week_scheduled)
    month_sched_h, month_sched_m = hours_minutes(month_scheduled)

    return render(request, "dashboard/my_hours.html", {
        "business": business,
        "week_start": week_start,
        "week_end": week_end - timedelta(days=1),
        "month_start": month_start,
        "month_end": month_end - timedelta(days=1),
        "week_hours": week_worked_h,
        "week_minutes": week_worked_m,
        "month_hours": month_worked_h,
        "month_minutes": month_worked_m,
        "week_sched_hours": week_sched_h,
        "week_sched_minutes": week_sched_m,
        "month_sched_hours": month_sched_h,
        "month_sched_minutes": month_sched_m,
    })


@login_required
def staff_hours_json(request, business_id, user_id):
    is_supervisor = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id,
        role__in=[BusinessMembership.OWNER, BusinessMembership.SUPERVISOR]
    ).exists()
    is_own_hours = str(request.user.id) == str(user_id)
    if not is_supervisor and not is_own_hours:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    target_user = get_user_model().objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({'error': 'User not found'}, status=404)

    business = Business.objects.filter(id=business_id).first()
    today = timezone.localdate()
    tz = timezone.get_current_timezone()

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    month_start = today.replace(day=1)
    month_end = month_start.replace(month=month_start.month + 1) if month_start.month < 12 else month_start.replace(year=month_start.year + 1, month=1)

    def start_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.min), tz)

    week_start_dt = start_of_day(week_start)
    week_end_dt = start_of_day(week_end)
    month_start_dt = start_of_day(month_start)
    month_end_dt = start_of_day(month_end)

    duration_expr = ExpressionWrapper(F('clock_out') - F('clock_in'), output_field=DurationField())

    def worked_total(start_dt, end_dt):
        return TimeClock.objects.filter(
            business=business, user=target_user,
            clock_out__isnull=False, clock_in__lt=end_dt, clock_out__gt=start_dt,
        ).aggregate(total=Coalesce(Sum(duration_expr), Value(timedelta(0)), output_field=DurationField()))["total"]

    def scheduled_total(start_dt, end_dt):
        qs = WorkShift.objects.filter(
            business=business, user=target_user, start__lt=end_dt, end__gt=start_dt,
        ).annotate(overlap=ExpressionWrapper(
            Least(F("end"), Value(end_dt, output_field=DateTimeField()))
            - Greatest(F("start"), Value(start_dt, output_field=DateTimeField())),
            output_field=DurationField(),
        )).filter(overlap__gt=timedelta(0))
        return qs.aggregate(total=Coalesce(Sum("overlap"), Value(timedelta(0)), output_field=DurationField()))["total"]

    def hm(td):
        s = int(td.total_seconds())
        return s // 3600, (s % 3600) // 60

    ww_h, ww_m = hm(worked_total(week_start_dt, week_end_dt))
    mw_h, mw_m = hm(worked_total(month_start_dt, month_end_dt))
    ws_h, ws_m = hm(scheduled_total(week_start_dt, week_end_dt))
    ms_h, ms_m = hm(scheduled_total(month_start_dt, month_end_dt))

    return JsonResponse({
        'name': target_user.get_full_name() or target_user.username,
        'week_start': str(week_start),
        'week_end': str(week_end - timedelta(days=1)),
        'month_start': str(month_start),
        'month_end': str(month_end - timedelta(days=1)),
        'week_worked': f"{ww_h}h {ww_m:02d}m",
        'month_worked': f"{mw_h}h {mw_m:02d}m",
        'week_scheduled': f"{ws_h}h {ws_m:02d}m",
        'month_scheduled': f"{ms_h}h {ms_m:02d}m",
    })
