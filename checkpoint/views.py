from urllib import request
from django.contrib.auth import login, get_user_model
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.contrib.auth.views import PasswordChangeView
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from datetime import datetime, timedelta, time
from .forms import OwnerSignUpForm, InviteStaffForm, NewBranchForm, WorkShiftForm
from .models import Business, BusinessMembership, WorkShift
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
    return render(request, 'dashboard/staff_dashboard.html')

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