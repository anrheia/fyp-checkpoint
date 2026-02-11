from django.conf import settings
from django.core.mail import send_mail
from django.utils.crypto import get_random_string

def generate_temporary_password(length=12):
    return get_random_string(length)

def send_invitation_email(restaurant_name, email, username, temp_password):
    subject = f"Invitation to join {restaurant_name} on CheckPoint"
    message = (
        f"You have been invited to join {restaurant_name} as a staff member.\n\n"
        f"Please use the following username: {username}\n\n"
        f"Your temporary password is: {temp_password}\n\n"
        "Please log in and change your password as soon as possible."
    )
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [email]
    send_mail(subject, message, from_email, recipient_list, fail_silently=False)