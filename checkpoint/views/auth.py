from django.contrib.auth import login, get_user_model
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse_lazy

from ..forms import OwnerSignUpForm, StyledPasswordChangeForm
from ..models import Business, BusinessMembership

User = get_user_model()


def home(request):
    return render(request, 'home.html')


@transaction.atomic
def owner_signup(request):
    # Creates user, business, and OWNER membership atomically, then logs in
    if request.method == 'POST':
        form = OwnerSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            business = Business.objects.create(name=form.cleaned_data.get('business_name'))
            BusinessMembership.objects.create(
                user=user,
                business=business,
                role=BusinessMembership.OWNER
            )
            login(request, user)
            return redirect('dashboard')
    else:
        form = OwnerSignUpForm()
    return render(request, 'registration/owner_signup.html', {'form': form})


class FirstLoginPasswordChangeView(PasswordChangeView):
    # Shown to staff on first login; clears must_change_password once done
    template_name = 'dashboard/first_login_password_change.html'
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        BusinessMembership.objects.filter(
            user=self.request.user,
            must_change_password=True
        ).update(must_change_password=False)
        return response
