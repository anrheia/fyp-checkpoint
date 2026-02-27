from django.conf import settings
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.http import JsonResponse, HttpResponse

import os, json, re
from datetime import timedelta
from openai import OpenAI
from .models import BusinessMembership

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
            role=BusinessMembership.EMPLOYEE,
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