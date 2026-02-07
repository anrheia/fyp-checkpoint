from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .forms import OwnerSignUpForm
from .models import Restaurant, RestaurantMembership

# Create your views here.

def home(request):
    return render(request, 'home.html')

@transaction.atomic
def owner_signup(request):
    if request.method == 'POST':
        form = OwnerSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            restaurant = Restaurant.objects.create(name=form.cleaned_data.get('restaurant_name'))
            RestaurantMembership.objects.create(
                user=user, 
                restaurant=restaurant, 
                role=RestaurantMembership.OWNER
            )
            login(request, user)
            return redirect('home')
    else:
        form = OwnerSignUpForm()
    return render(request, 'registration/owner_signup.html', {'form': form})

@login_required
def dashboard(request):
    is_owner = RestaurantMembership.objects.filter(
        user=request.user,
        role=RestaurantMembership.OWNER
    ).exists()

    if is_owner:
        return render(request, 'dashboard/owner_dashboard.html')
    return HttpResponse("Welcome to the Employee Dashboard!")