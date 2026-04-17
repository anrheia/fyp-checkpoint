import re as _re
from collections import defaultdict
from datetime import datetime, timedelta, time

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ..models import Business, BusinessMembership, WorkShift
from ..utils import (
    extract_schedule_query,
    extract_hours_query,
    extract_coverage_query,
    extract_person_schedule_query,
    extract_weekday_request,
    next_weekday,
    compute_staff_status,
)

User = get_user_model()

DAILY_CHAT_LIMIT = 30


def _chat_usage_today(request):
    key = f'chat_{timezone.localdate().isoformat()}'
    return request.session.get(key, 0), key


def _increment_chat_usage(request):
    count, key = _chat_usage_today(request)
    request.session[key] = count + 1
    request.session.modified = True


@login_required
def schedule_chat(request):
    used, _ = _chat_usage_today(request)
    return render(request, 'dashboard/schedule_chat.html', {
        'chat_limit': DAILY_CHAT_LIMIT,
        'chat_used': used,
    })


@login_required
@require_POST
@csrf_protect
def schedule_chat_api(request):
    msg = (request.POST.get("message") or "").strip()
    if not msg:
        return JsonResponse({"answer": "Type: who's working next Friday in Luigi's?"})

    used, _ = _chat_usage_today(request)
    if used >= DAILY_CHAT_LIMIT:
        return JsonResponse({
            "answer": f"You've reached your daily limit of {DAILY_CHAT_LIMIT} questions. Check back tomorrow!",
            "limit_reached": True,
        })
    _increment_chat_usage(request)

    # --- Intent: who is late today ---
    if _re.search(r"\blate\b", msg, _re.IGNORECASE):
        today = timezone.localdate().isoformat()
        extracted = extract_schedule_query(msg, today)
        branch_name = extracted.get("branch_name")

        owned_ids = BusinessMembership.objects.filter(
            user=request.user,
            role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": f"I couldn't find a branch matching '{branch_name}'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"Which branch? You own: {options}. Ask like: who's late at Luigi's?"})
            business = owned.first()

        status = compute_staff_status(business)
        late = status["late_staff"]
        now = status["now"]

        if not late:
            return JsonResponse({"answer": f"No one is late at {business.name} right now."})

        lines = []
        for s in late:
            u = s["user"]
            name = (u.first_name + " " + u.last_name).strip() or u.username
            shift_start = timezone.localtime(s["shift"].start).strftime("%H:%M")
            minutes_late = int((now - s["shift"].start).total_seconds() // 60)
            pos = " (" + s["position"] + ")" if s.get("position") else ""
            lines.append("- " + name + pos + ": shift started " + shift_start + ", " + str(minutes_late) + " min late")

        answer = f"Late at {business.name} right now ({now.strftime('%H:%M')}):\n" + "\n".join(lines)
        return JsonResponse({"answer": answer})

    if _re.search(r"\bhours?\b", msg, _re.IGNORECASE):
        today = timezone.localdate().isoformat()
        extracted = extract_hours_query(msg, today)
        person_name = extracted.get("person_name")
        week = extracted.get("week", "this")
        branch_name = extracted.get("branch_name")

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": "I couldn't find a branch matching '" + branch_name + "'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": "That matches multiple branches: " + options + ". Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1 and not person_name:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": "Which branch? You own: " + options + ". Ask like: who has the most hours next week at Luigi's?"})
            business = owned.first()

        today_date = timezone.localdate()
        this_monday = today_date - timedelta(days=today_date.weekday())
        week_start = this_monday + timedelta(days=7) if week == "next" else this_monday
        week_end = week_start + timedelta(days=6)
        week_label = "next week" if week == "next" else "this week"

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(week_start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(week_end, time.max), tz)

        shifts = WorkShift.objects.filter(
            business=business, start__lte=end_dt, end__gte=start_dt
        ).select_related("user")

        if not shifts.exists():
            return JsonResponse({"answer": "No shifts scheduled at " + business.name + " " + week_label + "."})

        user_totals = defaultdict(timedelta)
        user_names = {}
        for s in shifts:
            if person_name and person_name.lower() not in (s.user.first_name + " " + s.user.last_name).lower() and person_name.lower() not in s.user.username.lower():
                continue
            user_totals[s.user_id] += s.end - s.start
            user_names[s.user_id] = (s.user.first_name + " " + s.user.last_name).strip() or s.user.username

        if not user_totals:
            return JsonResponse({"answer": "No shifts found for '" + person_name + "' at " + business.name + " " + week_label + "."})

        sorted_staff = sorted(user_totals.items(), key=lambda x: -x[1].total_seconds())
        lines = []
        for uid, total in sorted_staff:
            hours = total.total_seconds() / 3600
            lines.append("- " + user_names[uid] + ": " + str(round(hours, 1)) + "h")

        date_range = week_start.strftime("%d %b") + "–" + week_end.strftime("%d %b")
        answer = "Hours at " + business.name + " " + week_label + " (" + date_range + "):\n" + "\n".join(lines)
        return JsonResponse({"answer": answer})

    if _re.search(r"\bhow\s+many\s+shifts?\b|\bmost\s+shifts?\b|\bfewest\s+shifts?\b|\bshift\s+count\b", msg, _re.IGNORECASE):
        today_iso = timezone.localdate().isoformat()
        extracted = extract_hours_query(msg, today_iso)
        person_name = extracted.get("person_name")
        week = extracted.get("week", "this")
        branch_name = extracted.get("branch_name")

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": f"I couldn't find a branch matching '{branch_name}'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1 and not person_name:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"Which branch? You own: {options}."})
            business = owned.first()

        today_date = timezone.localdate()
        this_monday = today_date - timedelta(days=today_date.weekday())
        week_start = this_monday + timedelta(days=7) if week == "next" else this_monday
        week_end = week_start + timedelta(days=6)
        week_label = "next week" if week == "next" else "this week"

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(week_start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(week_end, time.max), tz)

        shifts = WorkShift.objects.filter(
            business=business, start__lte=end_dt, end__gte=start_dt
        ).select_related("user")

        if not shifts.exists():
            return JsonResponse({"answer": f"No shifts scheduled at {business.name} {week_label}."})

        user_counts = defaultdict(int)
        user_names = {}
        for s in shifts:
            if person_name and person_name.lower() not in (s.user.first_name + " " + s.user.last_name).lower() and person_name.lower() not in s.user.username.lower():
                continue
            user_counts[s.user_id] += 1
            user_names[s.user_id] = (s.user.first_name + " " + s.user.last_name).strip() or s.user.username

        if not user_counts:
            return JsonResponse({"answer": f"No shifts found for '{person_name}' at {business.name} {week_label}."})

        sorted_staff = sorted(user_counts.items(), key=lambda x: -x[1])
        lines = [f"- {user_names[uid]}: {count} shift{'s' if count != 1 else ''}" for uid, count in sorted_staff]
        date_range = week_start.strftime("%d %b") + "–" + week_end.strftime("%d %b")
        return JsonResponse({"answer": f"Shift count at {business.name} {week_label} ({date_range}):\n" + "\n".join(lines)})

    # --- Intent: coverage / headcount ---
    if _re.search(r"\bhow many\b|\banyone\b|\bheadcount\b|\bcoverage\b", msg, _re.IGNORECASE):
        today = timezone.localdate().isoformat()
        extracted = extract_coverage_query(msg, today)
        iso_date = extracted.get("date")
        branch_name = extracted.get("branch_name")
        time_of_day = extracted.get("time_of_day")

        if not iso_date:
            return JsonResponse({"answer": "I couldn't work out which day you mean. Try: how many staff on Saturday at Luigi's?"})

        try:
            target_date = datetime.fromisoformat(iso_date).date()
        except Exception:
            return JsonResponse({"answer": "That date looked invalid. Try: how many staff on Saturday?"})

        weekday_idx, qualifier = extract_weekday_request(msg)
        if weekday_idx is not None:
            today_date = timezone.localdate()
            if qualifier == "next":
                target_date = next_weekday(today_date, weekday_idx)
            elif qualifier == "this":
                candidate = today_date + timedelta(days=(weekday_idx - today_date.weekday()))
                target_date = candidate if candidate >= today_date else next_weekday(today_date, weekday_idx)
            else:
                target_date = next_weekday(today_date, weekday_idx)

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": "I couldn't find a branch matching '" + branch_name + "'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": "That matches multiple branches: " + options + ". Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": "Which branch? You own: " + options + ". Ask like: how many staff on Saturday at Luigi's?"})
            business = owned.first()

        tz = timezone.get_current_timezone()

        TIME_WINDOWS = {
            "morning":   (time(6, 0),  time(12, 0)),
            "afternoon": (time(12, 0), time(17, 0)),
            "evening":   (time(17, 0), time(21, 0)),
            "night":     (time(21, 0), time(23, 59, 59)),
        }

        if time_of_day and time_of_day in TIME_WINDOWS:
            win_start, win_end = TIME_WINDOWS[time_of_day]
            filter_start = timezone.make_aware(datetime.combine(target_date, win_start), tz)
            filter_end   = timezone.make_aware(datetime.combine(target_date, win_end), tz)
            time_label = " (" + time_of_day + ")"
        else:
            filter_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
            filter_end   = timezone.make_aware(datetime.combine(target_date, time.max), tz)
            time_label = ""

        shifts = WorkShift.objects.filter(
            business=business,
            start__lt=filter_end,
            end__gt=filter_start,
        ).select_related("user").order_by("start")

        date_label = target_date.strftime("%A %d %b")

        if not shifts.exists():
            return JsonResponse({"answer": "No one is scheduled at " + business.name + " on " + date_label + time_label + "."})

        lines = []
        for s in shifts:
            u = s.user
            name = (u.first_name + " " + u.last_name).strip() or u.username
            slot = timezone.localtime(s.start).strftime("%H:%M") + "-" + timezone.localtime(s.end).strftime("%H:%M")
            lines.append("  - " + name + ": " + slot)

        count = len(lines)
        header = str(count) + " staff at " + business.name + " on " + date_label + time_label + ":"
        return JsonResponse({"answer": header + "\n" + "\n".join(lines)})

    if _re.search(r"\bwhen is\b|\bwhen does\b|\bwhen will\b|\bschedule for\b|\bshifts? for\b", msg, _re.IGNORECASE):
        today = timezone.localdate().isoformat()
        extracted = extract_person_schedule_query(msg, today)
        person_name = extracted.get("person_name")
        week = extracted.get("week", "this")
        branch_name = extracted.get("branch_name")

        if not person_name:
            return JsonResponse({"answer": "I couldn't work out who you're asking about. Try: when is John working this week?"})

        today_date = timezone.localdate()
        this_monday = today_date - timedelta(days=today_date.weekday())
        week_start = this_monday + timedelta(days=7) if week == "next" else this_monday
        week_end = week_start + timedelta(days=6)
        week_label = "next week" if week == "next" else "this week"

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(week_start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(week_end, time.max), tz)

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        name_lower = person_name.lower()
        member_users = User.objects.filter(
            businessmembership__business_id__in=owned_ids
        ).distinct()
        matched_users = [
            u for u in member_users
            if name_lower in (u.first_name + " " + u.last_name).lower()
            or name_lower in u.username.lower()
        ]

        if not matched_users:
            return JsonResponse({"answer": "I couldn't find anyone called '" + person_name + "' in your branches."})

        if branch_name:
            businesses = list(Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name"))
            if not businesses:
                return JsonResponse({"answer": "I couldn't find a branch matching '" + branch_name + "'."})
        else:
            businesses = list(Business.objects.filter(id__in=owned_ids).order_by("name"))

        shifts = WorkShift.objects.filter(
            business__in=businesses,
            user__in=matched_users,
            start__lte=end_dt,
            end__gte=start_dt,
        ).select_related("user", "business").order_by("start")

        if not shifts.exists():
            display = (matched_users[0].first_name + " " + matched_users[0].last_name).strip() or matched_users[0].username
            return JsonResponse({"answer": display + " has no shifts " + week_label + "."})

        by_user = defaultdict(list)
        for s in shifts:
            by_user[s.user_id].append(s)

        sections = []
        for uid, user_shifts in by_user.items():
            u = user_shifts[0].user
            display = (u.first_name + " " + u.last_name).strip() or u.username
            lines = []
            for s in user_shifts:
                day = timezone.localtime(s.start).strftime("%A %d %b")
                slot = timezone.localtime(s.start).strftime("%H:%M") + "-" + timezone.localtime(s.end).strftime("%H:%M")
                branch_label = " at " + s.business.name if len(businesses) > 1 else ""
                lines.append("  " + day + ": " + slot + branch_label)
            sections.append(display + " " + week_label + ":\n" + "\n".join(lines))

        return JsonResponse({"answer": "\n\n".join(sections)})

    if _re.search(r"\bposition\b|\bwhat role\b", msg, _re.IGNORECASE):
        today = timezone.localdate().isoformat()
        extracted = extract_person_schedule_query(msg, today)
        person_name = extracted.get("person_name")
        branch_name = extracted.get("branch_name")

        if not person_name:
            return JsonResponse({"answer": "I couldn't work out who you're asking about. Try: what position is John?"})

        owned_ids = BusinessMembership.objects.filter(
            user=request.user,
            role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            businesses = list(Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name"))
            if not businesses:
                return JsonResponse({"answer": f"I couldn't find a branch matching '{branch_name}'."})
        else:
            businesses = list(Business.objects.filter(id__in=owned_ids).order_by("name"))
            if not businesses:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})

        name_lower = person_name.lower()
        memberships = BusinessMembership.objects.filter(
            business__in=businesses,
            role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
        ).select_related('user', 'profile', 'business')

        matched = [
            m for m in memberships
            if name_lower in (m.user.first_name + ' ' + m.user.last_name).lower()
            or name_lower in m.user.username.lower()
        ]

        if not matched:
            return JsonResponse({"answer": f"I couldn't find anyone called '{person_name}' in your branches."})

        lines = []
        for m in matched:
            display = (m.user.first_name + ' ' + m.user.last_name).strip() or m.user.username
            profile = getattr(m, 'profile', None)
            pos = profile.position if profile and profile.position else 'No position assigned'
            branch_label = f" ({m.business.name})" if len(businesses) > 1 else ""
            lines.append(f"- {display}{branch_label}: {pos}")

        header = f"Position for {person_name}:" if len(matched) == 1 else f"Positions for '{person_name}':"
        return JsonResponse({"answer": header + "\n" + "\n".join(lines)})

    if _re.search(r"\bnot\s+(?:working|scheduled)\b|\bno\s+shifts?\b|\bwho.*\boff\b|\bdays?\s+off\b", msg, _re.IGNORECASE):
        today_iso = timezone.localdate().isoformat()
        extracted = extract_hours_query(msg, today_iso)
        week = extracted.get("week", "this")
        branch_name = extracted.get("branch_name")

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": f"I couldn't find a branch matching '{branch_name}'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"Which branch? You own: {options}."})
            business = owned.first()

        today_date = timezone.localdate()
        this_monday = today_date - timedelta(days=today_date.weekday())
        week_start = this_monday + timedelta(days=7) if week == "next" else this_monday
        week_end = week_start + timedelta(days=6)
        week_label = "next week" if week == "next" else "this week"

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(week_start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(week_end, time.max), tz)

        all_memberships = BusinessMembership.objects.filter(
            business=business,
            role__in=[BusinessMembership.EMPLOYEE, BusinessMembership.SUPERVISOR]
        ).select_related('user')

        scheduled_ids = set(WorkShift.objects.filter(
            business=business, start__lte=end_dt, end__gte=start_dt
        ).values_list('user_id', flat=True))

        off_staff = [m for m in all_memberships if m.user_id not in scheduled_ids]

        if not off_staff:
            return JsonResponse({"answer": f"Everyone at {business.name} has at least one shift {week_label}."})

        lines = ["- " + ((m.user.first_name + " " + m.user.last_name).strip() or m.user.username) for m in off_staff]
        date_range = week_start.strftime("%d %b") + "–" + week_end.strftime("%d %b")
        return JsonResponse({"answer": f"Not scheduled at {business.name} {week_label} ({date_range}):\n" + "\n".join(lines)})

    # --- Intent: overlapping shifts ---
    if _re.search(r"\boverlap\b|\bsame\s+time\b|\bat\s+the\s+same\s+time\b|\bworking\s+together\b", msg, _re.IGNORECASE):
        today_iso = timezone.localdate().isoformat()
        extracted = extract_schedule_query(msg, today_iso)
        iso_date = extracted.get("date")
        branch_name = extracted.get("branch_name")

        _rel = _re.search(r'\b(today|tomorrow|yesterday)\b', msg, _re.IGNORECASE)
        if _rel:
            _offsets = {'today': 0, 'tomorrow': 1, 'yesterday': -1}
            target_date = timezone.localdate() + timedelta(days=_offsets[_rel.group(1).lower()])
        elif iso_date:
            try:
                target_date = datetime.fromisoformat(iso_date).date()
            except Exception:
                return JsonResponse({"answer": "That date looked invalid."})
        else:
            weekday_idx, qualifier = extract_weekday_request(msg)
            if weekday_idx is not None:
                _td = timezone.localdate()
                if qualifier == "next":
                    target_date = next_weekday(_td, weekday_idx)
                elif qualifier == "this":
                    candidate = _td + timedelta(days=(weekday_idx - _td.weekday()))
                    target_date = candidate if candidate >= _td else next_weekday(_td, weekday_idx)
                else:
                    target_date = next_weekday(_td, weekday_idx)
            else:
                return JsonResponse({"answer": "Which day? Try: who's working at the same time on Saturday?"})

        owned_ids = BusinessMembership.objects.filter(
            user=request.user, role=BusinessMembership.OWNER
        ).values_list("business_id", flat=True)

        if branch_name:
            matches = Business.objects.filter(id__in=owned_ids, name__icontains=branch_name).order_by("name")
            if matches.count() == 0:
                return JsonResponse({"answer": f"I couldn't find a branch matching '{branch_name}'."})
            if matches.count() > 1:
                options = ", ".join(matches.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})
            business = matches.first()
        else:
            owned = Business.objects.filter(id__in=owned_ids).order_by("name")
            if owned.count() == 0:
                return JsonResponse({"answer": "You don't seem to own any branches yet."})
            if owned.count() > 1:
                options = ", ".join(owned.values_list("name", flat=True)[:8])
                return JsonResponse({"answer": f"Which branch? You own: {options}."})
            business = owned.first()

        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
        day_end = timezone.make_aware(datetime.combine(target_date, time.max), tz)

        shifts = list(WorkShift.objects.filter(
            business=business, start__lt=day_end, end__gt=day_start
        ).select_related('user').order_by('start'))

        date_label = target_date.strftime('%A %d %b')

        if not shifts:
            return JsonResponse({"answer": f"No shifts at {business.name} on {date_label}."})
        if len(shifts) < 2:
            return JsonResponse({"answer": f"Only one shift at {business.name} on {date_label} — no overlaps."})

        pairs = []
        for i in range(len(shifts)):
            for j in range(i + 1, len(shifts)):
                s1, s2 = shifts[i], shifts[j]
                if s1.start < s2.end and s2.start < s1.end:
                    n1 = (s1.user.first_name + ' ' + s1.user.last_name).strip() or s1.user.username
                    n2 = (s2.user.first_name + ' ' + s2.user.last_name).strip() or s2.user.username
                    t1 = f"{timezone.localtime(s1.start).strftime('%H:%M')}–{timezone.localtime(s1.end).strftime('%H:%M')}"
                    t2 = f"{timezone.localtime(s2.start).strftime('%H:%M')}–{timezone.localtime(s2.end).strftime('%H:%M')}"
                    pairs.append(f"- {n1} ({t1}) ↔ {n2} ({t2})")

        if not pairs:
            return JsonResponse({"answer": f"No overlapping shifts at {business.name} on {date_label}."})

        return JsonResponse({"answer": f"Overlapping shifts at {business.name} on {date_label}:\n" + "\n".join(pairs)})

    today_date = timezone.localdate()
    today = today_date.isoformat()
    extracted = extract_schedule_query(msg, today)

    iso_date = extracted.get("date")
    branch_name = extracted.get("branch_name")

    # Resolve today/tomorrow/yesterday reliably in Python — GPT can miss these
    _relative = _re.search(r'\b(today|tomorrow|yesterday)\b', msg, _re.IGNORECASE)
    if _relative:
        _offsets = {'today': 0, 'tomorrow': 1, 'yesterday': -1}
        target_date = today_date + timedelta(days=_offsets[_relative.group(1).lower()])
    elif not iso_date:
        return JsonResponse({"answer": "I couldn't find a date. Try: who's working on 2026-02-20 in Luigi's?"})
    else:
        try:
            target_date = datetime.fromisoformat(iso_date).date()
        except Exception:
            return JsonResponse({"answer": "That date looked invalid. Try YYYY-MM-DD."})

    weekday_idx, qualifier = extract_weekday_request(msg)
    if weekday_idx is not None and not _relative:
        if qualifier == "next":
            target_date = next_weekday(today_date, weekday_idx)
        elif qualifier == "this":
            candidate = today_date + timedelta(days=(weekday_idx - today_date.weekday()))
            if candidate < today_date:
                candidate = next_weekday(today_date, weekday_idx)
            target_date = candidate
        else:
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
            return JsonResponse({"answer": f"I couldn't find a branch you own matching '{branch_name}'."})
        if matches.count() > 1:
            options = ", ".join(matches.values_list("name", flat=True)[:8])
            return JsonResponse({"answer": f"That matches multiple branches: {options}. Be more specific."})

        business = matches.first()
    else:
        owned = Business.objects.filter(id__in=owned_ids).order_by("name")
        if owned.count() == 0:
            return JsonResponse({"answer": "You don't seem to own any branches yet."})
        if owned.count() > 1:
            options = ", ".join(owned.values_list("name", flat=True)[:8])
            return JsonResponse({"answer": f"Which branch? You own: {options}. Ask like: who's working Friday in Luigi's?"})
        business = owned.first()

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
