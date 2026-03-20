from urllib import request

from django.contrib import messages
from django.contrib.auth import login, get_user_model
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.decorators import login_required

from django.db import transaction
from django.db.models import F, DurationField, ExpressionWrapper, DateTimeField, Sum, Value
from django.db.models.functions import Coalesce, Greatest, Least

from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_GET

from datetime import datetime, timedelta, time
from .forms import (
    OwnerSignUpForm, 
    InviteStaffForm, 
    NewBranchForm, 
    WorkShiftForm, 
    StaffProfileForm)
from .models import Business, BusinessMembership, TimeClock, WorkShift, StaffProfile
from .utils import (
    get_membership,
    send_invitation_email, 
    generate_temporary_password, 
    extract_schedule_query,
    extract_weekday_request,
    next_weekday,
    get_owner_membership,
    get_supervisor_membership,
    shift_to_dict,
    compute_staff_status,
    send_shift_batch_email,
    send_shift_removed_email
    )
from datetime import datetime, time

import uuid
import qrcode
import io 
# Create your views here.

User = get_user_model()

def home(request):
    return render(request, 'home.html')

@transaction.atomic
def owner_signup(request):
    if request.method == 'POST':
        form = OwnerSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            business = Business.objects.create(name=form.cleaned_data.get('business_name'))
            BusinessMembership.objects.create(
                user=user, 
                business=business, 
                role=BusinessMembership.OWNER
            )
            login(request, user)
            return redirect('home')
    else:
        form = OwnerSignUpForm()
    return render(request, 'registration/owner_signup.html', {'form': form})

@login_required
def dashboard(request):
    owner_memberships = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).select_related("business")

    # OWNER DASHBOARD
    if owner_memberships.exists():
        branches = [m.business for m in owner_memberships]

        branches_with_status = []
        for b in branches:
            status = compute_staff_status(b)
            branches_with_status.append({
                "branch": b,
                **status
            })

        return render(request, "dashboard/owner_dashboard.html", {
            "branches_with_status": branches_with_status
        })
    
    # SUPERVISOR DASHBOARD
    supervisor_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.SUPERVISOR
    ).select_related("business").first()
    if supervisor_membership:
        business = supervisor_membership.business
        status = compute_staff_status(business)
        return render(request, "dashboard/supervisor_dashboard.html", {
            "business": business,
            **status
        })

    # STAFF DASHBOARD
    staff_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.EMPLOYEE
    ).select_related("business").first()

    return render(request, "dashboard/staff_dashboard.html", {
        "business": staff_membership.business if staff_membership else None
    })

# Owner-related views

@login_required
def invite_staff(request, business_id):
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response
    
    is_owner = membership.role == BusinessMembership.OWNER
    if request.method == 'POST':
        form = InviteStaffForm(request.POST)

        if form.is_valid():
            temp_password = generate_temporary_password()

            user = form.save(commit=False)
            user.email = form.cleaned_data['email'].lower().strip()
            user.username = form.cleaned_data['username'].strip()
            user.set_password(temp_password)
            user.save()

            requested_role = form.cleaned_data.get("role", BusinessMembership.EMPLOYEE)
            if not is_owner:
                requested_role = BusinessMembership.EMPLOYEE

            BusinessMembership.objects.create(
                user=user,
                business=business,
                role=requested_role,
                must_change_password=True
            )

            send_invitation_email(business.name, user.email, user.username, temp_password)
            return redirect('dashboard')
    else:
        form = InviteStaffForm()

    return render(request, 'dashboard/invite_staff.html', {
        'form': form,
        'business': business,
        'is_owner': is_owner
        })

@login_required
def create_branch(request):
    is_owner = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).exists()
    if not is_owner:
        return HttpResponse("You must be an owner to create a branch.", status=403)
    
    if request.method == 'POST':
        form = NewBranchForm(request.POST)

        if form.is_valid():
            branch = form.save()

            BusinessMembership.objects.create(
                user=request.user,
                business=branch,
                role=BusinessMembership.OWNER
            )
            return redirect('dashboard')
    else:
        form = NewBranchForm()

    return render(request, 'dashboard/create_branch.html', {'form': form})

@login_required
def view_staff(request, business_id):
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response

    staff_memberships = BusinessMembership.objects.filter(
        business=business,
        role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
    ).select_related('user').order_by('user__username')

    return render(request, 'dashboard/view_staff.html', {
        'business': business,
        'is_owner': membership.role == BusinessMembership.OWNER,
        'staff_memberships': staff_memberships
    })

# Schedule-related views

@login_required
def branch_schedule(request, business_id):
    _, business, error_response = get_supervisor_membership(request, business_id, json=True)

    if error_response:
        return error_response
    
    session_key = f"pending_shift_notifications_{business_id}"
    pending_count = len(request.session.get(session_key, []))
    
    return render(request, 'dashboard/branch_schedule.html', {
        'business': business,
        'pending_count': pending_count
    })

@login_required
def branch_shifts_json(request, business_id):
    _, business, error_response = get_supervisor_membership(request, business_id, json=True)

    if error_response:
        return error_response

    shifts = (
        WorkShift.objects.filter(business=business)
        .select_related('user')
        .order_by('start')
    )

    data = [shift_to_dict(shift) for shift in shifts]
    return JsonResponse(data, safe=False)

@login_required
def create_shift(request, business_id):
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response
    
    form = WorkShiftForm(request.POST or None)
    form.fields["user"].queryset = User.objects.filter(
        businessmembership__business=business,
    ).distinct().order_by('username')

    if request.method == 'POST':
        if form.is_valid():
            shift = form.save(commit=False)
            shift.business = business
            shift.created_by = request.user
            shift.save()

            session_key = f"pending_shift_notifications_{business_id}"
            pending = request.session.get(session_key, [])
            if shift.id not in pending:
                pending.append(shift.id)
            request.session[session_key] = pending
            request.session.modified = True

            messages.success(request, "Shift saved. Add more or send notifications when ready.")
            return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/create_shift.html', {
        'form': form,
        'business': business
    })

@login_required
def delete_shift(request, business_id, shift_id):
    _, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response
    
    shift = WorkShift.objects.filter(
        id=shift_id, 
        business=business
    ).select_related('user').first()
    if not shift:
        return HttpResponse({"error": "Shift not found."}, status=404)

    if request.method == 'POST':
        user = shift.user
        start_local = timezone.localtime(shift.start)
        end_local = timezone.localtime(shift.end)

        session_key = f"pending_shift_notifications_{business_id}"
        pending = request.session.get(session_key, [])
        if shift.id in pending:
            pending.remove(shift.id)
            request.session[session_key] = pending
            request.session.modified = True

        shift.delete()

        if user and user.email:
            send_shift_removed_email(user, business.name, start_local, end_local)

        return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/delete_shift.html', {
        'shift': shift,
        'business': business,
        'pending_ids': request.session.get(f"pending_shift_notifications_{business_id}", [])
    })

@login_required
def pending_shift_notifications(request, business_id):  
    _, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response

    session_key = f"pending_shift_notifications_{business_id}"
    pending_ids = request.session.get(session_key, [])

    shifts = (
        WorkShift.objects.filter(id__in=pending_ids, business=business)
        .select_related('user')
        .order_by('user__username', 'start')
    )

    # Group by employee for the preview
    from collections import defaultdict
    grouped = defaultdict(list)
    for shift in shifts:
        grouped[shift.user].append(shift)

    return render(request, 'dashboard/pending_notifications.html', {
        'business': business,
        'grouped_shifts': dict(grouped),
        'pending_count': len(pending_ids),
    })

@login_required
@require_POST
def send_shift_notifications(request, business_id):
    _, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response

    session_key = f"pending_shift_notifications_{business_id}"
    pending_ids = request.session.get(session_key, [])

    if not pending_ids:
        messages.info(request, "No pending notifications to send.")
        return redirect('branch_schedule', business_id=business.id)

    shifts = (
        WorkShift.objects.filter(id__in=pending_ids, business=business)
        .select_related('user')
        .order_by('user__username', 'start')
    )

    from collections import defaultdict
    grouped = defaultdict(list)
    for shift in shifts:
        if shift.user and shift.user.email:
            grouped[shift.user].append(shift)

    sent_count = 0
    for user, user_shifts in grouped.items():
        shift_times = [
            (timezone.localtime(s.start), timezone.localtime(s.end))
            for s in user_shifts
        ]
        send_shift_batch_email(user, business.name, shift_times)
        sent_count += 1

    request.session[session_key] = []
    request.session.modified = True

    messages.success(request, f"Notifications sent to {sent_count} employee(s).")
    return redirect('branch_schedule', business_id=business.id)

# AI assistant views

@login_required
def schedule_chat(request):
    return render(request, 'dashboard/schedule_chat.html')

@login_required
@require_POST
@csrf_protect
def schedule_chat_api(request):
    msg = (request.POST.get("message") or "").strip()
    if not msg:
        return JsonResponse({"answer": "Type: who’s working next Friday in Luigi’s?"})

    today = timezone.localdate().isoformat()
    extracted = extract_schedule_query(msg, today)

    iso_date = extracted.get("date")
    branch_name = extracted.get("branch_name")

    if not iso_date:
        return JsonResponse({"answer": "I couldn’t find a date. Try: who’s working on 2026-02-20 in Luigi’s?"})

    try:
        target_date = datetime.fromisoformat(iso_date).date()
    except Exception:
        return JsonResponse({"answer": "That date looked invalid. Try YYYY-MM-DD."})

    weekday_idx, qualifier = extract_weekday_request(msg)
    if weekday_idx is not None:
        today_date = timezone.localdate()

        if qualifier == "next":
            #next <weekday> = next occurrence after today
            target_date = next_weekday(today_date, weekday_idx)

        elif qualifier == "this":
            #this <weekday> = that weekday in current week if not passed; else next
            candidate = today_date + timedelta(days=(weekday_idx - today_date.weekday()))
            if candidate < today_date:
                candidate = next_weekday(today_date, weekday_idx)
            target_date = candidate

        else:
            #plain "<weekday>" = next occurrence after today
            target_date = next_weekday(today_date, weekday_idx)

    owned_ids = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).values_list("business_id", flat=True)

    if branch_name:
        branch_name = branch_name.strip()
        matches = Business.objects.filter(
            id__in=owned_ids,
            name__icontains=branch_name
        ).order_by("name")

        if matches.count() == 0:
            return JsonResponse({"answer": f"I couldn’t find a branch you own matching '{branch_name}'."})
        if matches.count() > 1:
            options = ", ".join(matches.values_list("name", flat=True)[:8])
            return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})

        business = matches.first()
    else:
        owned = Business.objects.filter(id__in=owned_ids).order_by("name")
        if owned.count() == 0:
            return JsonResponse({"answer": "You don’t seem to own any branches yet."})
        if owned.count() > 1:
            options = ", ".join(owned.values_list("name", flat=True)[:8])
            return JsonResponse({"answer": f"Which branch? You own: {options}. Ask like: who’s working Friday in Luigi’s?"})
        business = owned.first()

    # Query shifts for that date
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(target_date, time.max), tz)

    shifts = WorkShift.objects.filter(
        business=business,
        start__lte=end_dt,
        end__gte=start_dt
    ).select_related("user").order_by("start")

    if not shifts.exists():
        return JsonResponse({"answer": f"No one is scheduled at {business.name} on {target_date.strftime('%A %d %b %Y')}."})

    lines = []
    for s in shifts:
        u = s.user
        name = (f"{u.first_name} {u.last_name}".strip()) or u.username
        lines.append(f"- {name}: {timezone.localtime(s.start).strftime('%H:%M')}–{timezone.localtime(s.end).strftime('%H:%M')}")

    answer = f"Scheduled at {business.name} on {target_date.strftime('%A %d %b %Y')}:\n" + "\n".join(lines)
    return JsonResponse({"answer": answer})

#Clock-in/out related views
@login_required
@require_POST
def clock_in(request, business_id):
    membership, business, error_response = get_membership(request, business_id)
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

# Staff-related views
def staff_branch_shifts_json(request, business_id):
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
class FirstLoginPasswordChangeView(PasswordChangeView): 
    template_name = 'dashboard/first_login_password_change.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        
        BusinessMembership.objects.filter(
            user=self.request.user,
            must_change_password=True
        ).update(must_change_password=False)

        return response
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

    week_worked = worked_total_for_range(week_start_dt, week_end_dt)
    month_worked = worked_total_for_range(month_start_dt, month_end_dt)

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
def my_qr_code(request, business_id):
    membership, business, error_response = get_membership(request, business_id)
    if error_response:
        return error_response
    
    token = str(membership.qr_token)
    scan_url = request.build_absolute_uri(f"/qr-scan/{token}/")

    img = qrcode.make(scan_url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png') 

@login_required
def qr_scanner(request, business_id):
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response
    return render(request, "dashboard/qr_scanner.html", {"business": business})

@require_POST
@csrf_protect
def process_qr_scan(request, token):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)
    
    try: 
        membership = BusinessMembership.objects.select_related("user", "business").get(
            qr_token=token)
    except BusinessMembership.DoesNotExist:
        return JsonResponse({"error": "Invalid QR code or expired QR code."}, status=404)
    
    employee = membership.user
    business = membership.business

    scanner_membership = BusinessMembership.objects.filter(
        user=request.user,
        business=business,
        role__in=[BusinessMembership.OWNER, BusinessMembership.SUPERVISOR]
    ).first()
    if not scanner_membership:
        return JsonResponse({"error": "You don't have permission to clock staff in/out here."}, status=403)
    
    now = timezone.now()

    open_clock = TimeClock.objects.filter(
        business=business,
        user=employee,
        clock_out__isnull=True
    ).order_by("-clock_in").first()

    if open_clock:
        open_clock.clock_out = now
        open_clock.save(update_fields=["clock_out"])
        action = "clocked_out"
        message = f"{employee.get_full_name() or employee.username} clocked out at {timezone.localtime(now).strftime('%H:%M')}."
    else:
        active_shift = WorkShift.objects.filter(
            business=business,
            user=employee,
            start__lte=now,
            end__gte=now
        ).order_by("start").first()

        if not active_shift:
            membership.qr_token = uuid.uuid4()
            membership.save(update_fields=["qr_token"])
            return JsonResponse({"error": f"{employee.get_full_name() or employee.username} has no active shift right now."}, status=400)

        if TimeClock.objects.filter(business=business, user=employee, shift=active_shift).exists():
            membership.qr_token = uuid.uuid4()
            membership.save(update_fields=["qr_token"])
            return JsonResponse({"error": f"{employee.get_full_name() or employee.username} already clocked in for this shift."}, status=400)

        TimeClock.objects.create(
            business=business,
            user=employee,
            shift=active_shift,
            clock_in=now
        )
        action = "clocked_in"
        message = f"{employee.get_full_name() or employee.username} clocked in at {timezone.localtime(now).strftime('%H:%M')}."

    membership.qr_token = uuid.uuid4()
    membership.save(update_fields=["qr_token"])

    return JsonResponse({"action": action, "message": message})

@login_required
def staff_detail(request, business_id, membership_id):
    manager_membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response

    target_membership = BusinessMembership.objects.filter(
        id=membership_id,
        business=business,
        role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
    ).select_related('user').first()

    if not target_membership:
        return HttpResponse("Staff member not found.", status=404)

    if manager_membership.role == BusinessMembership.SUPERVISOR:
        if target_membership.role != BusinessMembership.EMPLOYEE:
            return HttpResponse("You don't have permission to view this profile.", status=403)

    profile, _ = StaffProfile.objects.get_or_create(membership=target_membership)

    if request.method == 'POST':
        form = StaffProfileForm(request.POST, instance=profile, user=target_membership.user)
        if form.is_valid():
            form.save()
            form.save_user_fields(target_membership.user)
            messages.success(request, "Staff profile updated.")
            return redirect('view_staff', business_id=business.id)
    else:
        form = StaffProfileForm(instance=profile, user=target_membership.user)

    return render(request, 'dashboard/staff_detail.html', {
        'form': form,
        'target_membership': target_membership,
        'business': business,
        'is_owner': manager_membership.role == BusinessMembership.OWNER,
    })