from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()

class OwnerSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    restaurant_name = forms.CharField(max_length=255)

    class Meta:
        model = User
        fields = ('username', 'email', 'restaurant_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        
        if commit:
            user.save()
        return user
class InviteStaffForm(forms.Form):
    email = forms.EmailField(required=True)

