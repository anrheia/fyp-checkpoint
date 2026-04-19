from .auth import home, owner_signup, FirstLoginPasswordChangeView
from .dashboard import dashboard, send_branch_message, send_staff_message, switch_dashboard_view
from .owner import invite_staff, delete_branch, create_branch, view_staff, staff_detail, assign_roles, assign_existing_staff, remove_staff
from .schedule import (branch_schedule, branch_shifts_json, create_shift, delete_shift,
                       pending_shift_notifications, send_shift_notifications)
from .chat import schedule_chat, schedule_chat_api
from .clock import clock_in, clock_out, staff_branch_shifts_json, my_hours, staff_hours_json
from .qr import my_qr_code, qr_scanner, process_qr_scan, process_pin_scan
from .reports import download_owner_report, download_supervisor_report
