from django.conf import settings
from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.views import LoginView, LogoutView 
from .forms import StyledAuthenticationForm
from . import views

urlpatterns = [
    path('owner/signup/', views.owner_signup, name='owner_signup'),
    path('login/', LoginView.as_view(template_name='registration/login.html', authentication_form=StyledAuthenticationForm), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),

    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/switch-view/', views.switch_dashboard_view, name='switch_dashboard_view'),
    path('branch/create/', views.create_branch, name='create_branch'),
    path('branches/<int:business_id>/delete/', views.delete_branch, name='delete_branch'),
    path('branches/<int:business_id>/invite-staff/', views.invite_staff, name='invite_staff'),
    path('branches/<int:business_id>/staff/', views.view_staff, name='view_staff'),

    path('branches/<int:business_id>/schedule/', views.branch_schedule, name='branch_schedule'),
    path('branches/<int:business_id>/schedule/shifts.json', views.branch_shifts_json, name='branch_shifts_json'),
    path('branches/<int:business_id>/schedule/new/', views.create_shift, name='create_shift'),
    path('branches/<int:business_id>/schedule/shifts/<int:shift_id>/delete/', views.delete_shift, name='delete_shift'),
    path('business/<int:business_id>/schedule/pending-notifications/', views.pending_shift_notifications, name='pending_shift_notifications'),
    path('business/<int:business_id>/schedule/send-notifications/', views.send_shift_notifications, name='send_shift_notifications'),

    path('schedule/chat/', views.schedule_chat, name='schedule_chat'),
    path('schedule/chat/api/', views.schedule_chat_api, name='schedule_chat_api'),

    path("business/<int:business_id>/clock-in/", views.clock_in, name="clock_in"),
    path("business/<int:business_id>/clock-out/", views.clock_out, name="clock_out"),

    #staff paths
    path("branches/<int:business_id>/message/", views.send_staff_message, name="send_staff_message"),
    path("branches/<int:business_id>/send-message/", views.send_branch_message, name="send_branch_message"),
    path("branches/<int:business_id>/schedule/shifts/staff.json", views.staff_branch_shifts_json, name="staff_branch_shifts_json"),
    path("business/<int:business_id>/my-hours/", views.my_hours, name="my_hours"),

    path("business/<int:business_id>/my-qr/", views.my_qr_code, name="my_qr_code"),
    path("business/<int:business_id>/qr-scanner/", views.qr_scanner, name="qr_scanner"),
    path("qr-scan/<uuid:token>/", views.process_qr_scan, name="process_qr_scan"),
    path("pin-scan/", views.process_pin_scan, name="process_pin_scan"),

    path('business/<int:business_id>/staff/<int:membership_id>/', views.staff_detail, name='staff_detail'),
    path('branches/<int:business_id>/assign-roles/', views.assign_roles, name='assign_roles'),
    path('branches/<int:business_id>/assign-existing/', views.assign_existing_staff, name='assign_existing_staff'),
    path('branches/<int:business_id>/staff/<int:membership_id>/remove/', views.remove_staff, name='remove_staff'),
    path('branches/<int:business_id>/staff/<int:user_id>/hours.json', views.staff_hours_json, name='staff_hours_json'),

    path('report/owner/', views.download_owner_report, name='download_owner_report'),
    path('business/<int:business_id>/report/supervisor/', views.download_supervisor_report, name='download_supervisor_report'),

    path('under-construction/', TemplateView.as_view(template_name='under_construction.html'), name='under_construction'),
]