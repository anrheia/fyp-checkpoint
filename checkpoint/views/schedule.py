from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import WorkShiftForm
from ..models import BusinessMembership, WorkShift
from ..utils import get_supervisor_membership, shift_to_dict, send_shift_batch_email, send_shift_removed_email

User = get_user_model()


@login_required
def branch_schedule(request, business_id):
    # Renders the schedule management page; also shows how many unsent shift notifications are pending
    _, business, error_response = get_supervisor_membership(request, business_id, json=True)

    if error_response:
        return error_response

    session_key = f"pending_shift_notifications_{business_id}"
    pending_ids = request.session.get(session_key, [])
    pending_count = len(pending_ids)

    pending_shifts = (
        WorkShift.objects.filter(id__in=pending_ids, business=business)
        .select_related('user')
        .order_by('user__username', 'start')
    )
    grouped = defaultdict(list)
    for shift in pending_shifts:
        grouped[shift.user].append(shift)

    form = WorkShiftForm()
    form.fields["user"].queryset = User.objects.filter(
        businessmembership__business=business,
    ).distinct().order_by('username')

    return render(request, 'dashboard/branch_schedule.html', {
        'business': business,
        'pending_count': pending_count,
        'grouped_shifts': dict(grouped),
        'form': form,
    })


@login_required
def branch_shifts_json(request, business_id):
    # JSON endpoint that feeds all branch shifts to the schedule calendar
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
    # Creates a shift and queues it in the session for notification; notification is not sent until explicitly triggered
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
        else:
            for field in form:
                for error in field.errors:
                    messages.error(request, f"{field.label}: {error}")

        return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/create_shift.html', {
        'form': form,
        'business': business
    })


@login_required
def delete_shift(request, business_id, shift_id):
    # Deletes a shift; emails the employee only if the shift had already been notified (not in pending queue)
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
        else:
            if user and user.email:
                send_shift_removed_email(user, business.name, start_local, end_local)

        shift.delete()
        return redirect('branch_schedule', business_id=business.id)

    return render(request, 'dashboard/delete_shift.html', {
        'shift': shift,
        'business': business,
        'pending_ids': request.session.get(f"pending_shift_notifications_{business_id}", []),
    })


@login_required
def pending_shift_notifications(request, business_id):
    # Shows the review page listing all shifts queued for notification, grouped by employee
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
    # Emails each employee their pending shifts in one batch, then clears the notification queue
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
