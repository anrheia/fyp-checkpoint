from urllib import request
from django.contrib import messages
from django.contrib.auth import login, get_user_model
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from datetime import datetime, timedelta, time
from .forms import OwnerSignUpForm, InviteStaffForm, NewBranchForm, WorkShiftForm
from .models import Business, BusinessMembership, TimeClock, WorkShift
from .utils import (
    send_invitation_email, 
    generate_temporary_password, 
    extract_schedule_query,
    extract_weekday_request,
    next_weekday,
    get_owner_membership,
    shift_to_dict
    )
from datetime import datetime, time
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
    is_owner = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).select_related('business')

    if is_owner.exists():
        branches = [m.business for m in is_owner]
        return render(request, 'dashboard/owner_dashboard.html', {
            'branches': branches
            })
    
    staff_memberships = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.EMPLOYEE
    ).select_related('business').first()
    return render(request, 'dashboard/staff_dashboard.html', {
        'business': staff_memberships.business if staff_memberships else None
    })

# Owner-related views

@login_required
def invite_staff(request, business_id):
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()
    if not owner_membership:
        return HttpResponse("You must be an owner to invite staff.", status=403)
    
    business = owner_membership.business

    if request.method == 'POST':
        form = InviteStaffForm(request.POST)

        if form.is_valid():
            temp_password = generate_temporary_password()

            user = form.save(commit=False)
            user.email = form.cleaned_data['email'].lower().strip()
            user.username = form.cleaned_data['username'].strip()
            user.set_password(temp_password)
            user.save()

            BusinessMembership.objects.create(
                user=user,
                business=business,
                role=BusinessMembership.EMPLOYEE,
                must_change_password=True
            )

            send_invitation_email(business.name, user.email, user.username, temp_password)

            return redirect('dashboard')
    else:
        form = InviteStaffForm()
    return render(request, 'dashboard/invite_staff.html', {
        'form': form,
        'business': business
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
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()

    if not owner_membership:
        return HttpResponse("You must be an owner to view staff.", status=403)  
    
    business = owner_membership.business

    staff_memberships = BusinessMembership.objects.filter(
        business=business,
        role=BusinessMembership.EMPLOYEE
    ).select_related('user').order_by('user__username')

    return render(request, 'dashboard/view_staff.html', {
        'business': business,
        'staff_memberships': staff_memberships
    })

# Schedule-related views

@login_required
def branch_schedule(request, business_id):
    _, business, error_response = get_owner_membership(request, business_id, json=True)

    if error_response:
        return error_response
    
    return render(request, 'dashboard/branch_schedule.html', {
        'business': business
    })

@login_required
def branch_shifts_json(request, business_id):
    _, business, error_response = get_owner_membership(request, business_id, json=True)

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
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()

    if not owner_membership:
        return HttpResponse({"error": "You do not have access to this branch."}, status=403)
    
    business = owner_membership.business

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
            return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/create_shift.html', {
        'form': form,
        'business': business
    })

def delete_shift(request, business_id, shift_id):
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()

    if not owner_membership:
        return HttpResponse({"error": "You do not have access to this branch."}, status=403)
    
    business = owner_membership.business

    shift = WorkShift.objects.filter(
        id=shift_id, 
        business=business
    ).first()
    if not shift:
        return HttpResponse({"error": "Shift not found."}, status=404)

    if request.method == 'POST':
        shift.delete()
        return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/delete_shift.html', {
        'shift': shift,
        'business': business
    })

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
    membership = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id
    ).select_related("business").first()

    if not membership:
        messages.error(request, "You do not have access to this business.")
        return redirect("dashboard")

    business = membership.business
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
    membership = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id
    ).select_related("business").first()

    if not membership:
        messages.error(request, "You do not have access to this business.")
        return redirect("dashboard")

    business = membership.business
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

def staff_status(request, business_id):
    _, business, error_response = get_owner_membership(request, business_id, json=True)
    if error_response:
        return error_response
    
    now = timezone.localtime(timezone.now())
    today = timezone.localdate()

    minutes = 15
    grace_period = now - timedelta(minutes=minutes)

    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(today, time.max), tz)

    staff_memberships = BusinessMembership.objects.filter(
        business=business,
        role=BusinessMembership.EMPLOYEE
    ).select_related('user').order_by('user__username')
    staff_users = [m.user for m in staff_memberships]

    shifts = WorkShift.objects.filter(
        business=business,
        user__in=staff_users,
        start__lte=now,
        end__gte=grace_period
    ).select_related('user').order_by('start')

    shifts_by_user = {}
    for shift in shifts:
        shifts_by_user.setdefault(shift.user_id, []).append(shift)

    open_clocks = TimeClock.objects.filter(
        business=business,
        user__in=staff_users,
        clock_out__isnull=True
    ).select_related('user', 'shift')

    clock_by_user = {tc.user_id: tc for tc in open_clocks}

    in_staff, late_staff, out_staff = [], [], []

    for user in staff_users:
        open_tc = clock_by_user.get(user.id)
        if open_tc:
            in_staff.append({
                "user": user,
                "clock_in": open_tc.clock_in
            })
            continue

        todays = shifts_by_user.get(user.id, [])
        active_shift = None
        for shift in todays:
            if shift.start <= now <= shift.end:
                active_shift = shift
                break

        if active_shift and now > (active_shift.start + minutes):
            late_staff.append({
                "user": user,
                "shift": active_shift
            })
        else:
            out_staff.append({
                "user": user,
                "shift": active_shift
            })

        return render(request, 'dashboard/staff_status.html', {
            "business": business,
            "in_staff": in_staff,
            "late_staff": late_staff,
            "out_staff": out_staff
        })
        

# Staff-related views

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