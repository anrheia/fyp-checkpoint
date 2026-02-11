from django.db import models
from django.conf import settings

# Create your models here.

class Restaurant(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class RestaurantMembership(models.Model):
    OWNER = 'owner'
    EMPLOYEE = 'employee'

    role_choices = [
        (OWNER, 'Owner'),
        (EMPLOYEE, 'Employee'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=role_choices)

    must_change_password = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'restaurant'], name='unique_membership')
        ]

        