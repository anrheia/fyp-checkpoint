from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone 
from django.utils.crypto import get_random_string
from django.http import JsonResponse, HttpResponse

import os, json, re
from datetime import datetime, time, timedelta
from openai import OpenAI
from .models import BusinessMembership, WorkShift, TimeClock

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6
}

_client = None

def generate_temporary_password(length=12):
    return get_random_string(length)

def send_invitation_email(business_name, email, username, temp_password):
    subject = f"Invitation to join {business_name} on CheckPoint"
    message = (
        f"You have been invited to join {business_name} as a staff member.\n\n"
        f"Please use the following username: {username}\n\n"
        f"Your temporary password is: {temp_password}\n\n"
        "Please log in and change your password as soon as possible."
    )
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [email]
    send_mail(subject, message, from_email, recipient_list, fail_silently=False)

def send_shift_batch_email(user, business_name, shifts):
    lines = "\n".join(
        f"  • {start.strftime('%A %d %b %Y')}  {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        for start, end in shifts
    )
    subject = f"Your upcoming shifts at {business_name}"
    message = (
        f"Hi {user.first_name or user.username},\n\n"
        f"The following shifts have been assigned to you at {business_name}:\n\n"
        f"{lines}\n\n"
        "Please log in to CheckPoint to view your full schedule."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


def send_shift_removed_email(user, business_name, start, end):
    subject = f"Shift removed at {business_name}"
    message = (
        f"Hi {user.first_name or user.username},\n\n"
        f"The following shift at {business_name} has been removed:\n\n"
        f"  • {start.strftime('%A %d %b %Y')}  {start.strftime('%H:%M')}-{end.strftime('%H:%M')}\n\n"
        "Please log in to CheckPoint to view your updated schedule."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)

def get_owner_membership(request, business_id, *, json=False, message=None):
    owner_membership = (BusinessMembership.objects.filter(
            user=request.user, 
            role=BusinessMembership.OWNER, 
            business_id=business_id
        )
        .select_related('business')
        .first()
    )

    if owner_membership:
        return owner_membership, owner_membership.business, None
    
    msg = message or "You do not have permission to manage this business."
    if json:
        return None, None, JsonResponse({"error": msg}, status=403)
    return None, None, HttpResponse(msg, status=403)

def get_membership(request, business_id, *, json=False, message=None):
    membership = (BusinessMembership.objects.filter(
            user=request.user, 
            business_id=business_id
        )
        .select_related('business')
        .first()
    )

    if membership:
        return membership, membership.business, None
    
    msg = message or "You do not have permission to access this business."
    if json:
        return None, None, JsonResponse({"error": msg}, status=403)
    return None, None, HttpResponse(msg, status=403)

def get_supervisor_membership(request, business_id, *, json=False, message=None):
    membership = (BusinessMembership.objects.filter(
        user=request.user, 
        business_id=business_id, 
        role__in=[BusinessMembership.OWNER, BusinessMembership.SUPERVISOR]
    )
    .select_related('business')
    .first()
    )

    if membership:
        return membership, membership.business, None
    
    msg = message or "You do not have permission to manage this business."
    if json:
        return None, None, JsonResponse({"error": msg}, status=403)
    return None, None, HttpResponse(msg, status=403)

def user_display_name(user):
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name if full_name else user.username

def shift_to_dict(shift):
    user = shift.user
    return {
        "id": shift.id,
        "title": user_display_name(user) if user else "Unassigned",
        "start": shift.start.isoformat(),
        "end": shift.end.isoformat(),
        "notes": shift.notes or "",
    }

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    return _client

def compute_staff_status(business, minutes=15):
    now = timezone.localtime(timezone.now())
    today = timezone.localdate()
    tz = timezone.get_current_timezone()

    day_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(today, time.max), tz)

    grace_period = now - timedelta(minutes=minutes)

    staff_memberships = BusinessMembership.objects.filter(
        business=business,
        role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
    ).select_related("user").order_by("user__username")

    staff_users = [m.user for m in staff_memberships]

    shifts_recent = WorkShift.objects.filter(
        business=business,
        user__in=staff_users,
        start__lte=now,
        end__gte=grace_period
    ).select_related("user").order_by("start")

    shifts_by_user = {}
    for shift in shifts_recent:
        shifts_by_user.setdefault(shift.user_id, []).append(shift)

    next_shifts = WorkShift.objects.filter(
        business=business,
        user__in=staff_users,
        start__gt=now,
        start__gte=day_start,
        start__lte=day_end
    ).select_related("user").order_by("start")

    next_shift_by_user = {}
    for shift in next_shifts:
        if shift.user_id not in next_shift_by_user:
            next_shift_by_user[shift.user_id] = shift

    open_clocks = TimeClock.objects.filter(
        business=business,
        user__in=staff_users,
        clock_out__isnull=True
    ).select_related("user", "shift")

    clock_by_user = {tc.user_id: tc for tc in open_clocks}

    in_staff, late_staff, out_staff = [], [], []

    for user in staff_users:
        open_tc = clock_by_user.get(user.id)
        if open_tc:
            in_staff.append({"user": user, "clock_in": open_tc.clock_in})
            continue

        todays_recent = shifts_by_user.get(user.id, [])
        active_shift = None
        for shift in todays_recent:
            if shift.start <= now <= shift.end:
                active_shift = shift
                break

        if active_shift and now > (active_shift.start + timedelta(minutes=minutes)):
            late_staff.append({"user": user, "shift": active_shift})
        else:
            out_staff.append({
                "user": user,
                "shift": active_shift,                 
                "next_shift": next_shift_by_user.get(user.id)  
            })

    return {
        "in_staff": in_staff,
        "late_staff": late_staff,
        "out_staff": out_staff,
        "now": now
    }
# Utility function to find the next date for a given weekday, used in schedule query parsing.

def next_weekday(start_date, target_weekday, *, include_today=False):
    days_ahead = target_weekday - start_date.weekday()
    if days_ahead < 0 or (days_ahead == 0 and not include_today):
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)

# Detecting weekday references in user messages for scheduling queries.

def extract_weekday_request(text: str):
    text = (text or "").lower()
    for name, idx in WEEKDAY_MAP.items():
        if re.search(rf"\bnext\s+{name}\b", text):
            return idx, "next"
        if re.search(rf"\bthis\s+{name}\b", text):
            return idx, "this"
        if re.search(rf"\b{name}\b", text):
            return idx, None
    
    return None, None

# For extracting date and branch name from a schedule query message using the OpenAI API.

def extract_schedule_query(message: str, today_iso: str) -> dict:
    msg = (message or "").strip()
    if not msg:
        return {"date": None, "branch_name": None}

    schema = {
        "name": "schedule_query",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "branch_name": {"type": ["string", "null"], "description": "Restaurant/branch name if mentioned, else null"}
            },
            "required": ["date", "branch_name"]
        }
    }

    client = _get_client()
    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=(
            "Extract the target date and restaurant/branch name from the message.\n"
            f"Today is {today_iso} in Europe/Dublin.\n"
            "Rules for weekdays:\n"
            "- If the user says a weekday like 'Friday' with no other qualifiers, choose the NEXT occurrence of that weekday after today.\n"
            "- If the user says 'next Friday', choose the NEXT occurrence of Friday after today.\n"
            "- If the user says 'this Friday', choose the Friday in the current week if it hasn't passed yet; otherwise the next Friday.\n"
            "If user says 'Friday 20th' without month, choose the closest future matching date.\n"
            "If no restaurant is mentioned, set branch_name to null.\n"
            "Return ONLY JSON matching the schema."
        ),
        input=msg,
        text={
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "schema": schema["schema"],
                "strict": True
            }
        },
        max_output_tokens=150
    )

    raw = (resp.output_text or "").strip()
    try:
        parsed = json.loads(raw)
        return {
            "date": parsed.get("date"),
            "branch_name": parsed.get("branch_name"),
        }
    except Exception:
        # if parsing fails, return safe nulls
        return {"date": None, "branch_name": None}