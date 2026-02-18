from django.db import models
from django.conf import settings
from django.utils import timezone

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
    
class TimeClock(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE, related_name='timeclocks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='timeclocks')

    shift = models.ForeignKey(
        'WorkShift', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='timeclocks'
    )

    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['business','user', 'clock_in']),
        ]

    def __str__(self):
        status = "IN" if not self.clock_out else "OUT"
        return f"{self.user.username} - {self.business.name} ({status} at {self.clock_in})"
    
    @property
    def is_open(self):
        return self.clock_out is None