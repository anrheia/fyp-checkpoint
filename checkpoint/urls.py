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
]