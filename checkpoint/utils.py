from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone 
from django.utils.crypto import get_random_string
from django.http import JsonResponse, HttpResponse

import os, json, re
from datetime import datetime, time, timedelta
from openai import OpenAI
from .models import BusinessMembership, WorkShift, TimeClock, StaffProfile

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


def send_staff_message_email(sender_user, recipient_user, business_name, subject, message_body):
    from django.core.mail import EmailMessage
    sender_name = (sender_user.first_name + " " + sender_user.last_name).strip() or sender_user.username
    full_subject = "[" + business_name + "] " + subject
    body = (
        "Message from " + sender_name + " at " + business_name + ":\n\n" +
        message_body + "\n\n---\nReply to: " + (sender_user.email or "No email on file")
    )
    email = EmailMessage(
        subject=full_subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_user.email],
        reply_to=[sender_user.email] if sender_user.email else [],
    )
    email.send(fail_silently=False)


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

    position_by_user = {
        p.membership.user_id: p.position
        for p in StaffProfile.objects.filter(
            membership__business=business
        ).select_related("membership")
    }

    shifts_recent = WorkShift.objects.filter(
        business=business,
        user__in=staff_users,
        start__lte=day_end,
        end__gte=day_start
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

    in_staff, late_staff, out_staff, done_staff, not_scheduled = [], [], [], [], []

    for user in staff_users:
        open_tc = clock_by_user.get(user.id)
        todays_shifts = shifts_by_user.get(user.id, [])

        if not todays_shifts and not open_tc:
            not_scheduled.append({
                "user": user,
                "position": position_by_user.get(user.id, ""),
            })
            continue
        
        if open_tc:
            in_staff.append({"user": user, "clock_in": open_tc.clock_in, "position": position_by_user.get(user.id, "")})
            continue

        active_shift = None
        for shift in todays_shifts:
            if shift.start <= now <= shift.end:
                active_shift = shift
                break
        
        past_shifts = None
        for shift in todays_shifts:
            if shift.end < now:
                past_shifts = shift
                break 


        pos = position_by_user.get(user.id, "")
        if active_shift and now > (active_shift.start + timedelta(minutes=minutes)):
            late_staff.append({"user": user, "shift": active_shift, "position": pos})
        elif past_shifts and not active_shift:
            done_staff.append({"user": user, "shift": past_shifts, "position": pos})
        else:
            out_staff.append({
                "user": user,
                "shift": active_shift,
                "next_shift": next_shift_by_user.get(user.id),
                "position": pos,
            })

    return {
        "in_staff": in_staff,
        "late_staff": late_staff,
        "out_staff": out_staff,
        "done_staff": done_staff,
        "not_scheduled": not_scheduled,
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

def extract_person_schedule_query(message: str, today_iso: str) -> dict:
    msg = (message or "").strip()
    if not msg:
        return {"person_name": None, "week": "this", "branch_name": None}

    schema = {
        "name": "person_schedule_query",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "person_name": {
                    "type": ["string", "null"],
                    "description": "The staff member's name being looked up"
                },
                "week": {
                    "type": "string",
                    "enum": ["this", "next"],
                    "description": "'next' if asking about next week, 'this' for current week. Default to 'this'."
                },
                "branch_name": {
                    "type": ["string", "null"],
                    "description": "Restaurant/branch name if mentioned, else null"
                }
            },
            "required": ["person_name", "week", "branch_name"]
        }
    }

    client = _get_client()
    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=(
            f"Today is {today_iso}.\n"
            "Extract the staff member's name being asked about, which week (this or next), "
            "and the restaurant/branch name if mentioned.\n"
            "Default week to 'this' if not specified.\n"
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
            "person_name": parsed.get("person_name"),
            "week": parsed.get("week", "this"),
            "branch_name": parsed.get("branch_name"),
        }
    except Exception:
        return {"person_name": None, "week": "this", "branch_name": None}


def extract_coverage_query(message: str, today_iso: str) -> dict:
    msg = (message or "").strip()
    if not msg:
        return {"date": None, "branch_name": None, "time_of_day": None}

    schema = {
        "name": "coverage_query",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "date": {
                    "type": ["string", "null"],
                    "description": "YYYY-MM-DD of the day being asked about"
                },
                "branch_name": {
                    "type": ["string", "null"],
                    "description": "Restaurant/branch name if mentioned, else null"
                },
                "time_of_day": {
                    "type": ["string", "null"],
                    "enum": ["morning", "afternoon", "evening", "night", None],
                    "description": "Time-of-day qualifier if mentioned: morning (06-12), afternoon (12-17), evening (17-21), night (21-close). Null if the whole day is asked about."
                }
            },
            "required": ["date", "branch_name", "time_of_day"]
        }
    }

    client = _get_client()
    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=(
            f"Today is {today_iso} in Europe/Dublin.\n"
            "Extract the target date, restaurant/branch name, and time-of-day qualifier.\n"
            "Rules for weekdays: plain 'Saturday' means next Saturday after today.\n"
            "'next Saturday' means the Saturday after today.\n"
            "'this Saturday' means this week's Saturday if not passed, else next.\n"
            "time_of_day: set to 'morning', 'afternoon', 'evening', or 'night' only if explicitly mentioned. Otherwise null.\n"
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
            "time_of_day": parsed.get("time_of_day"),
        }
    except Exception:
        return {"date": None, "branch_name": None, "time_of_day": None}


def extract_hours_query(message: str, today_iso: str) -> dict:
    msg = (message or "").strip()
    if not msg:
        return {"person_name": None, "week": "this", "branch_name": None}

    schema = {
        "name": "hours_query",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "person_name": {
                    "type": ["string", "null"],
                    "description": "The staff member's name if asking about a specific person, else null"
                },
                "week": {
                    "type": "string",
                    "enum": ["this", "next"],
                    "description": "'next' if asking about next week, 'this' for current/this week"
                },
                "branch_name": {
                    "type": ["string", "null"],
                    "description": "Restaurant/branch name if mentioned, else null"
                }
            },
            "required": ["person_name", "week", "branch_name"]
        }
    }

    client = _get_client()
    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=(
            f"Today is {today_iso}.\n"
            "Extract the staff member's name, which week, and the branch/restaurant name from a work-hours question.\n"
            "The message typically follows the pattern: 'how many hours does [PERSON NAME] have [this/next] week [at/in BRANCH NAME]?'\n"
            "person_name: the person whose hours are being asked about — the name that follows 'does', 'did', 'has', or 'for'. Set to null if asking about all staff.\n"
            "branch_name: the restaurant or location name that appears after 'at' or 'in'. Set to null if no branch is mentioned.\n"
            "Do NOT put a person's name in branch_name. Do NOT put a branch name in person_name.\n"
            "Example: 'how many hours does John Smith have this week at Luigi's' → person_name='John Smith', branch_name=\"Luigi's\".\n"
            "Example: 'how many hours does Papa Cookeria have this week' → person_name='Papa Cookeria', branch_name=null.\n"
            "Default week to 'this' if not specified.\n"
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
            "person_name": parsed.get("person_name"),
            "week": parsed.get("week", "this"),
            "branch_name": parsed.get("branch_name"),
        }
    except Exception:
        return {"person_name": None, "week": "this", "branch_name": None}


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
            "Relative day rules:\n"
            f"- 'today' means {today_iso}.\n"
            "- 'tomorrow' means the day after today.\n"
            "- 'yesterday' means the day before today.\n"
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


def extract_shift_creation_query(message: str, today_iso: str) -> dict:
    # Parses a natural-language scheduling request into structured fields for WorkShift creation
    msg = (message or "").strip()
    if not msg:
        return {"person_name": None, "branch_name": None, "date": None, "start_time": None, "end_time": None}

    schema = {
        "name": "shift_creation_query",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "person_name": {
                    "type": ["string", "null"],
                    "description": "Full name of the employee to schedule"
                },
                "branch_name": {
                    "type": ["string", "null"],
                    "description": "Restaurant/branch name if mentioned, else null"
                },
                "date": {
                    "type": ["string", "null"],
                    "description": "YYYY-MM-DD"
                },
                "start_time": {
                    "type": ["string", "null"],
                    "description": "HH:MM in 24-hour format"
                },
                "end_time": {
                    "type": ["string", "null"],
                    "description": "HH:MM in 24-hour format"
                }
            },
            "required": ["person_name", "branch_name", "date", "start_time", "end_time"]
        }
    }

    client = _get_client()
    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=(
            f"Today is {today_iso} in Europe/Dublin.\n"
            "Extract the employee's full name, branch name, date, start time, and end time from the scheduling request.\n"
            "The message typically follows the pattern: 'schedule [PERSON NAME] in [BRANCH NAME] for [TIME RANGE] on [DAY]'.\n"
            "person_name is the name immediately after 'schedule' and before the word 'in' (or 'at') that precedes the branch.\n"
            "branch_name is the restaurant/location name that comes after 'in' or 'at', before 'for'.\n"
            "Do NOT include 'in [branch]' as part of person_name. Do NOT include the person's name as part of branch_name.\n"
            "Names may be in any capitalisation (e.g. 'john smith', 'JOHN SMITH', 'John Smith') — extract them exactly as written.\n"
            "Example: 'schedule John Smith in Luigi's for 9-17 on Friday' → person_name='John Smith', branch_name=\"Luigi's\".\n"
            "Relative day rules:\n"
            f"- 'today' means {today_iso}.\n"
            "- 'tomorrow' means the day after today.\n"
            "- If the user says a weekday like 'Friday' with no qualifier, choose the NEXT occurrence after today.\n"
            "- 'next Friday' means the next Friday after today.\n"
            "Convert all times to 24-hour HH:MM format.\n"
            "If any field is missing or unclear, return null for that field.\n"
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
            "person_name": parsed.get("person_name"),
            "branch_name": parsed.get("branch_name"),
            "date": parsed.get("date"),
            "start_time": parsed.get("start_time"),
            "end_time": parsed.get("end_time"),
        }
    except Exception:
        return {"person_name": None, "branch_name": None, "date": None, "start_time": None, "end_time": None}