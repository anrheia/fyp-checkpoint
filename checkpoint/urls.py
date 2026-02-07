from django.urls import path
from . import views

urlpatterns = [
    path('owner/signup/', views.owner_signup, name='owner_signup'),
    path('dashboard/', views.dashboard, name='dashboard'),
]