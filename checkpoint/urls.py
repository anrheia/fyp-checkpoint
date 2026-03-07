from django.urls import path
from . import views

urlpatterns = [
    path('owner/signup/', views.owner_signup, name='owner_signup'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('branch/create/', views.create_branch, name='create_branch'),
    path('branches/<int:business_id>/invite-staff/', views.invite_staff, name='invite_staff'),
    path('branches/<int:business_id>/staff/', views.view_staff, name='view_staff'),

    path('branches/<int:business_id>/schedule/', views.branch_schedule, name='branch_schedule'),
    path('branches/<int:business_id>/schedule/shifts.json', views.branch_shifts_json, name='branch_shifts_json'),
    path('branches/<int:business_id>/schedule/new/', views.create_shift, name='create_shift'),
    path('branches/<int:business_id>/schedule/shifts/<int:shift_id>/delete/', views.delete_shift, name='delete_shift'),

    path('schedule/chat/', views.schedule_chat, name='schedule_chat'),
    path('schedule/chat/api/', views.schedule_chat_api, name='schedule_chat_api'),

    path("business/<int:business_id>/clock-in/", views.clock_in, name="clock_in"),
    path("business/<int:business_id>/clock-out/", views.clock_out, name="clock_out"),

    #staff paths
    path("branches/<int:business_id>/schedule/shifts/staff.json", views.staff_branch_shifts_json, name="staff_branch_shifts_json"),
    path("business/<int:business_id>/my-hours/", views.my_hours, name="my_hours"),

    path("business/<int:business_id>/my-qr/", views.my_qr_code, name="my_qr_code"),
    path("business/<int:business_id>/qr-scanner/", views.qr_scanner, name="qr_scanner"),
    path("qr-scan/<uuid:token>/", views.process_qr_scan, name="process_qr_scan"),
]