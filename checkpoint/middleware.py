from django.shortcuts import render, redirect
from .models import RestaurantMembership

class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            allowed_prefixes = (
                "/accounts/password_change/", 
                "/accounts/password_change_done/", 
                "/accounts/logout/", 
                "/accounts/login/",
                "/admin/"
                )

            if request.path.startswith(allowed_prefixes):
                return self.get_response(request)
            

            if RestaurantMembership.objects.filter(
                user=request.user,
                role=RestaurantMembership.EMPLOYEE,
                must_change_password=True
                ).exists():
                    return redirect('password_change')
            
        return self.get_response(request)