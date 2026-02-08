from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib.auth import get_user_model

from .forms import OwnerSignUpForm, InviteStaffForm
from .models import Restaurant, RestaurantMembership
from .utils import send_invitation_email, generate_temporary_password

# Create your views here.

User = get_user_model()

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
    return render(request, 'dashboard/staff_dashboard.html')

def invite_staff(request):
    owner_membership = RestaurantMembership.objects.filter(
        user=request.user,
        role=RestaurantMembership.OWNER
    ).select_related('restaurant').first()
    if not owner_membership:
        return HttpResponse("You must be an owner to invite staff.", status=403)
    
    restaurant = owner_membership.restaurant

    if request.method == 'POST':
        form = InviteStaffForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].lower().strip()
            temp_password = generate_temporary_password()

            user, created = User.objects.get_or_create(
                username=email, 
                defaults={'email': email}
            )

            if not created:
                form.add_error('email', 'A user with this email already exists.')
                return render(request, 'dashboard/invite_staff.html', {'form': form})
            
            user.set_password(temp_password)
            user.save()

            RestaurantMembership.objects.create(
                user=user,
                restaurant=restaurant,
                role=RestaurantMembership.EMPLOYEE
            )

            send_invitation_email(email, restaurant.name, temp_password)

            return redirect('dashboard')
    else:
        form = InviteStaffForm()
    return render(request, 'dashboard/invite_staff.html', {'form': form})
