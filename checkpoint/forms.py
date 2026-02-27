from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Business, WorkShift

User = get_user_model()

class OwnerSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    business_name = forms.CharField(max_length=255)

    class Meta:
        model = User
        fields = ('username', 'email', 'business_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        
        if commit:
            user.save()
        return user
    
class NewBranchForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ('name',)

class InviteStaffForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username
    
class WorkShiftForm(forms.ModelForm):
    class Meta:
        model = WorkShift
        fields = ('user', 'start', 'end', 'notes')
        widgets = {
            'start': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

        