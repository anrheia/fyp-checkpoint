from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import BusinessMembership
from ..utils import get_membership, compute_staff_status, send_staff_message_email
from .chat import DAILY_CHAT_LIMIT

User = get_user_model()


@login_required
def dashboard(request):
    owner_memberships = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.OWNER
    ).select_related("business")

    if owner_memberships.exists():
        branches = [m.business for m in owner_memberships]
        owned_branch_ids = [b.id for b in branches]

        branches_with_status = []
        for b in branches:
            status = compute_staff_status(b)

            staff_memberships = BusinessMembership.objects.filter(
                business=b,
                role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
            ).select_related('user', 'profile').order_by('user__username')

            messageable = staff_memberships.exclude(user__email="")

            existing_user_ids = staff_memberships.values_list('user_id', flat=True)
            assignable_staff = User.objects.filter(
                businessmembership__business_id__in=owned_branch_ids,
                businessmembership__role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
            ).exclude(id__in=existing_user_ids).distinct()

            branches_with_status.append({
                "branch": b,
                **status,
                "staff_memberships": staff_memberships,
                "messageable_members": messageable,
                "assignable_staff": assignable_staff,
            })

        chat_used = request.session.get(f'chat_{timezone.localdate().isoformat()}', 0)
        return render(request, "dashboard/owner_dashboard.html", {
            "branches_with_status": branches_with_status,
            "chat_used": chat_used,
            "chat_limit": DAILY_CHAT_LIMIT,
        })

    supervisor_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.SUPERVISOR
    ).select_related("business").first()
    if supervisor_membership:
        business = supervisor_membership.business
        status = compute_staff_status(business)
        staff_memberships = BusinessMembership.objects.filter(
            business=business,
            role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
        ).select_related('user', 'profile').order_by('user__username')

        messageable_members = BusinessMembership.objects.filter(
            business=business,
        ).select_related('user').exclude(user=request.user).exclude(user__email="").order_by('role', 'user__username')

        chat_used = request.session.get(f'chat_{timezone.localdate().isoformat()}', 0)
        return render(request, "dashboard/supervisor_dashboard.html", {
            "business": business,
            "staff_memberships": staff_memberships,
            "messageable_members": messageable_members,
            "chat_used": chat_used,
            "chat_limit": DAILY_CHAT_LIMIT,
            **status
        })

    staff_membership = BusinessMembership.objects.filter(
        user=request.user,
        role=BusinessMembership.EMPLOYEE
    ).select_related("business").first()

    if not staff_membership:
        return render(request, "dashboard/staff_dashboard.html", {"business": None})

    business = staff_membership.business

    supervisors = BusinessMembership.objects.filter(
        business=business,
        role__in=[BusinessMembership.OWNER, BusinessMembership.SUPERVISOR]
    ).select_related("user").exclude(user__email="").order_by("role", "user__username")

    return render(request, "dashboard/staff_dashboard.html", {
        "business": business,
        "supervisors": supervisors,
        "pin_code": staff_membership.pin_code,
    })


@login_required
@require_POST
def send_branch_message(request, business_id):
    _, business, error = get_membership(request, business_id)
    if error:
        return error

    recipient_id = request.POST.get("recipient_id", "").strip()
    subject = request.POST.get("subject", "").strip()
    body = request.POST.get("message", "").strip()

    if not subject or not body:
        messages.error(request, "Subject and message are required.")
        return redirect("dashboard")

    recipient_membership = BusinessMembership.objects.filter(
        business=business,
        user_id=recipient_id,
    ).select_related("user").first()

    if not recipient_membership or not recipient_membership.user.email:
        messages.error(request, "Recipient not found or has no email address.")
        return redirect("dashboard")

    send_staff_message_email(request.user, recipient_membership.user, business.name, subject, body)
    messages.success(request, "Your message has been sent.")
    return redirect("dashboard")


@login_required
@require_POST
def send_staff_message(request, business_id):
    _, business, error = get_membership(request, business_id)
    if error:
        return error

    recipient_id = request.POST.get("recipient_id", "").strip()
    subject = request.POST.get("subject", "").strip()
    body = request.POST.get("message", "").strip()

    if not subject or not body:
        messages.error(request, "Subject and message are required.")
        return redirect("dashboard")

    recipient_membership = BusinessMembership.objects.filter(
        business=business,
        user_id=recipient_id,
        role__in=[BusinessMembership.OWNER, BusinessMembership.SUPERVISOR]
    ).select_related("user").first()

    if not recipient_membership or not recipient_membership.user.email:
        messages.error(request, "Recipient not found or has no email address.")
        return redirect("dashboard")

    send_staff_message_email(request.user, recipient_membership.user, business.name, subject, body)
    messages.success(request, "Your message has been sent.")
    return redirect("dashboard")
