from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordChangeForm

from .models import Business, BusinessMembership, WorkShift, StaffProfile

User = get_user_model()

class OwnerSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    business_name = forms.CharField(max_length=255)
    class Meta:
        model = User
        fields = ('username', 'email', 'business_name', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input input-bordered w-full px-4 py-2'})
            field.help_text = ''

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']

        if commit:
            user.save()
        return user

class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input input-bordered w-full'})
            field.help_text = ''

class NewBranchForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ('name',)

class InviteStaffForm(forms.ModelForm):
    role = forms.ChoiceField(
        choices=[
            (BusinessMembership.EMPLOYEE, 'Staff'),
            (BusinessMembership.SUPERVISOR, 'Supervisor'),
        ],
        initial=BusinessMembership.EMPLOYEE,
        required=True,
    )
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'username', 'email')

    INPUT_STYLE = "display: block; width: 100%; background: white; border: 1.5px solid oklch(82% 0.03 195); border-radius: 0.75rem; padding: 0.5rem 0.75rem; font-family: 'DM Sans', sans-serif; font-size: 0.875rem; color: oklch(28% 0.04 195); outline: none; box-sizing: border-box;"
    SELECT_STYLE = "display: block; width: 100%; background: white; border: 1.5px solid oklch(82% 0.03 195); border-radius: 0.75rem; padding: 0.5rem 0.75rem; font-family: 'DM Sans', sans-serif; font-size: 0.875rem; color: oklch(28% 0.04 195); outline: none; box-sizing: border-box; cursor: pointer;"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'style': self.SELECT_STYLE})
            else:
                field.widget.attrs.update({'style': self.INPUT_STYLE})
            field.help_text = ''

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'class': 'select select-bordered w-full'})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({'class': 'textarea textarea-bordered w-full'})
            else:
                field.widget.attrs.update({'class': 'input input-bordered w-full'})
            field.help_text = ''

class StaffProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    email = forms.EmailField(required=False)

    class Meta:
        model = StaffProfile
        fields = ('phone_number', 'position', 'supervisor_notes')
        widgets = {
            'position': forms.TextInput(attrs={'list': 'position-suggestions', 'placeholder': 'e.g. Kitchen, Floor, Bar…'}),
        }

    INPUT_STYLE = "display: block; width: 100%; background: white; border: 1.5px solid oklch(82% 0.03 195); border-radius: 0.75rem; padding: 0.5rem 0.75rem; font-family: 'DM Sans', sans-serif; font-size: 0.875rem; color: oklch(28% 0.04 195); outline: none; box-sizing: border-box;"
    TEXTAREA_STYLE = "display: block; width: 100%; background: white; border: 1.5px solid oklch(82% 0.03 195); border-radius: 0.75rem; padding: 0.5rem 0.75rem; font-family: 'DM Sans', sans-serif; font-size: 0.875rem; color: oklch(28% 0.04 195); outline: none; box-sizing: border-box; min-height: 6rem; resize: vertical;"

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
        for field in self.fields.values():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({'style': self.TEXTAREA_STYLE})
            else:
                field.widget.attrs.update({'style': self.INPUT_STYLE})
            field.help_text = ''

    def save_user_fields(self, user):
        user.first_name = self.cleaned_data.get('first_name', user.first_name)
        user.last_name = self.cleaned_data.get('last_name', user.last_name)
        user.email = self.cleaned_data.get('email', user.email)
        user.save(update_fields=['first_name', 'last_name', 'email'])

class StyledPasswordChangeForm(PasswordChangeForm):
    INPUT_STYLE = "display: block; width: 100%; background: white; border: 1.5px solid oklch(82% 0.03 195); border-radius: 0.75rem; padding: 0.5rem 0.75rem; font-family: 'DM Sans', sans-serif; font-size: 0.875rem; color: oklch(28% 0.04 195); outline: none; box-sizing: border-box;"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'style': self.INPUT_STYLE})
            field.help_text = ''
