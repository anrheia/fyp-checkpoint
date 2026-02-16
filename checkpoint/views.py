from urllib import request
from django.contrib.auth import login, get_user_model
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.contrib.auth.views import PasswordChangeView
from django.utils import timezone

from .forms import OwnerSignUpForm, InviteStaffForm, NewBranchForm, WorkShiftForm
from .models import Business, BusinessMembership, WorkShift
from .utils import send_invitation_email, generate_temporary_password

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

@login_required
def branch_schedule(request, business_id):
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()

    if not owner_membership:
        return HttpResponse("You do not have access to this branch.", status=403)
    
    business = owner_membership.business

    return render(request, 'dashboard/branch_schedule.html', {
        'business': business
    })

@login_required
def branch_shifts_json(request, business_id):
    owner_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER,
        business_id=business_id
    ).select_related('business').first()

    if not owner_membership:
        return JsonResponse({"error": "You do not have access to this branch."}, status=403)
    
    business = owner_membership.business
    shifts = WorkShift.objects.filter(business=business).select_related('user').order_by('start')

    data = []
    for shift in shifts:

        user = shift.user

        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        display_name = full_name if full_name else user.username

        start_str = timezone.localtime(shift.start).strftime('%H:%M')
        end_str = timezone.localtime(shift.end).strftime('%H:%M')
        title = f"{display_name}"
        data.append({
            'id': shift.id,
            'title': title,
            'start': shift.start.isoformat(),
            'end': shift.end.isoformat(),
            'notes': shift.notes
        })
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