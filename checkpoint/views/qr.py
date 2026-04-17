import io
import json
import uuid

import qrcode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ..models import BusinessMembership, TimeClock, WorkShift, generate_pin
from ..utils import get_membership, get_supervisor_membership


@login_required
def my_qr_code(request, business_id):
    # Returns the staff member's personal QR code as a PNG image
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
    # Renders the supervisor QR scanner page; owner/supervisor access only
    membership, business, error_response = get_supervisor_membership(request, business_id)
    if error_response:
        return error_response
    from django.shortcuts import render
    return render(request, "dashboard/qr_scanner.html", {"business": business})


@require_POST
@csrf_protect
def process_qr_scan(request, token):
    # Clocks the employee in or out based on their current state; rotates QR token and PIN after every scan
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
            membership.pin_code = generate_pin()
            membership.save(update_fields=["qr_token", "pin_code"])
            return JsonResponse({"error": f"{employee.get_full_name() or employee.username} has no active shift right now."}, status=400)

        if TimeClock.objects.filter(business=business, user=employee, shift=active_shift).exists():
            membership.qr_token = uuid.uuid4()
            membership.pin_code = generate_pin()
            membership.save(update_fields=["qr_token", "pin_code"])
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
    membership.pin_code = generate_pin()
    membership.save(update_fields=["qr_token", "pin_code"])

    return JsonResponse({"action": action, "message": message})


@require_POST
@csrf_protect
def process_pin_scan(request):
    # Same clock-in/out logic as process_qr_scan but identified by PIN code instead of QR token
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)

    try:
        body = json.loads(request.body)
        pin = body.get("pin", "").strip().upper()
    except (ValueError, KeyError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    if not pin:
        return JsonResponse({"error": "No code provided."}, status=400)

    try:
        membership = BusinessMembership.objects.select_related("user", "business").get(pin_code=pin)
    except BusinessMembership.DoesNotExist:
        return JsonResponse({"error": "Invalid code — please check and try again."}, status=404)

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
            membership.pin_code = generate_pin()
            membership.save(update_fields=["qr_token", "pin_code"])
            return JsonResponse({"error": f"{employee.get_full_name() or employee.username} has no active shift right now."}, status=400)

        if TimeClock.objects.filter(business=business, user=employee, shift=active_shift).exists():
            membership.qr_token = uuid.uuid4()
            membership.pin_code = generate_pin()
            membership.save(update_fields=["qr_token", "pin_code"])
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
    membership.pin_code = generate_pin()
    membership.save(update_fields=["qr_token", "pin_code"])

    return JsonResponse({"action": action, "message": message})
