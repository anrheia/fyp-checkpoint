from django.shortcuts import render, redirect
from .models import BusinessMembership

# Intercepts every request for staff with must_change_password=True and
# redirects them to the password change page until they comply.
# Owners are exempt, they set their own password at signup.
class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Let auth-related and admin URLs through so the redirect doesn't loop
            allowed_prefixes = (
                "/accounts/password_change/",
                "/accounts/password_change_done/",
                "/accounts/logout/",
                "/accounts/login/",
                "/admin/"
                )

            if request.path.startswith(allowed_prefixes):
                return self.get_response(request)

            if BusinessMembership.objects.filter(
                user=request.user,
                must_change_password=True
                ).exclude(role=BusinessMembership.OWNER).exists():
                    return redirect('password_change')

        return self.get_response(request)
    