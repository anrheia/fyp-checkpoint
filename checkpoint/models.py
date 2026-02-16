from django.db import models
from django.conf import settings

# Create your models here.

class Business(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class BusinessMembership(models.Model):
    OWNER = 'owner'
    EMPLOYEE = 'employee'

    role_choices = [
        (OWNER, 'Owner'),
        (EMPLOYEE, 'Employee'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=role_choices)

    must_change_password = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'business'], name='unique_membership')
        ]

class WorkShift(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE, related_name='shifts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shifts')

    start = models.DateTimeField()
    end = models.DateTimeField()

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, related_name='created_shifts'
        )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.business.name} ({self.start} to {self.end})"