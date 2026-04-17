from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from ..forms import InviteStaffForm, NewBranchForm, StaffProfileForm
from ..models import Business, BusinessMembership, StaffProfile
from ..utils import get_supervisor_membership, send_invitation_email, generate_temporary_password

User = get_user_model()


@login_required
def invite_staff(request, business_id):
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response

    is_owner = membership.role == BusinessMembership.OWNER
    if not is_owner:
        return HttpResponse("Access denied.", status=403)
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
def delete_branch(request, business_id):
    is_owner = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id,
        role=BusinessMembership.OWNER
    ).exists()
    if not is_owner:
        return HttpResponse("You must be an owner to delete a branch.", status=403)
    if request.method == 'POST':
        staff_user_ids = BusinessMembership.objects.filter(
            business_id=business_id,
            role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
        ).values_list('user_id', flat=True)

        exclusive_user_ids = [
            uid for uid in staff_user_ids
            if not BusinessMembership.objects.filter(user_id=uid).exclude(business_id=business_id).exists()
        ]
        get_user_model().objects.filter(id__in=exclusive_user_ids).delete()

        Business.objects.filter(id=business_id).delete()
    return redirect('dashboard')


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


@login_required
def view_staff(request, business_id):
    return redirect('dashboard')


@login_required
def assign_roles(request, business_id):
    _, business, error = get_supervisor_membership(request, business_id)
    if error:
        return error
    if request.method == 'POST':
        memberships = BusinessMembership.objects.filter(
            business=business,
            role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
        )
        for m in memberships:
            position = request.POST.get(f'position_{m.id}', '').strip()
            profile, _ = StaffProfile.objects.get_or_create(membership=m)
            if profile.position != position:
                profile.position = position
                profile.save(update_fields=['position'])
        messages.success(request, "Roles updated.")
    return redirect('dashboard')


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
        is_own_profile = target_membership.id == manager_membership.id
        if target_membership.role != BusinessMembership.EMPLOYEE and not is_own_profile:
            return HttpResponse("You don't have permission to view this profile.", status=403)

    profile, _ = StaffProfile.objects.get_or_create(membership=target_membership)

    if request.method == 'POST':
        form = StaffProfileForm(request.POST, instance=profile, user=target_membership.user)
        if form.is_valid():
            form.save()
            form.save_user_fields(target_membership.user)
            messages.success(request, "Staff profile updated.")
            return redirect('staff_detail', business_id=business.id, membership_id=target_membership.id)
    else:
        form = StaffProfileForm(instance=profile, user=target_membership.user)

    return render(request, 'dashboard/staff_detail.html', {
        'form': form,
        'profile': profile,
        'target_membership': target_membership,
        'business': business,
        'is_owner': manager_membership.role == BusinessMembership.OWNER,
    })


@login_required
@require_POST
def assign_existing_staff(request, business_id):
    is_owner = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id,
        role=BusinessMembership.OWNER
    ).exists()
    if not is_owner:
        return HttpResponse("Only owners can assign staff to branches.", status=403)

    business = Business.objects.filter(id=business_id).first()
    if not business:
        return HttpResponse("Branch not found.", status=404)

    user_id = request.POST.get('user_id')

    owned_business_ids = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).values_list('business_id', flat=True)

    target_user = User.objects.filter(
        id=user_id,
        businessmembership__business_id__in=owned_business_ids,
        businessmembership__role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
    ).first()

    if not target_user:
        messages.error(request, "Staff member not found.")
        return redirect('dashboard')

    if BusinessMembership.objects.filter(user=target_user, business=business).exists():
        messages.error(request, f"{target_user.get_full_name() or target_user.username} is already in this branch.")
        return redirect('dashboard')

    new_membership = BusinessMembership.objects.create(
        user=target_user,
        business=business,
        role=BusinessMembership.EMPLOYEE
    )
    StaffProfile.objects.create(membership=new_membership)
    messages.success(request, f"{target_user.get_full_name() or target_user.username} has been added to {business.name}.")
    return redirect('dashboard')


@login_required
@require_POST
def remove_staff(request, business_id, membership_id):
    is_owner = BusinessMembership.objects.filter(
        user=request.user,
        business_id=business_id,
        role=BusinessMembership.OWNER
    ).exists()
    if not is_owner:
        return HttpResponse("Only owners can remove staff from a branch.", status=403)

    target_membership = BusinessMembership.objects.filter(
        id=membership_id,
        business_id=business_id,
        role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
    ).select_related('user', 'business').first()

    if not target_membership:
        return HttpResponse("Staff member not found.", status=404)

    target_user = target_membership.user
    display_name = target_user.get_full_name() or target_user.username
    branch_name = target_membership.business.name
    target_membership.delete()

    if not BusinessMembership.objects.filter(user=target_user).exists():
        target_user.delete()

    messages.success(request, f"{display_name} has been removed from {branch_name}.")
    return redirect('dashboard')
