from django.db import models
from django.conf import settings
import uuid

"""
USER PROFILE
"""

class User(models.Model):

    class Role(models.TextChoices):
        EMPLOYEE = "employee", "Employee"
        SUPERVISOR = "supervisor", "Supervisor"
        OWNER = "owner", "Owner"

    # One to one link to the django auth user table
    # Each user has at most one user profile row
    user = models.OneToOneField (
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.EMPLOYEE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_username()} ({self.role})"
    
"""
RESTAURANT
"""

class Restaurant(models.Model):

    # FK to the user that owns this restaurant (usually role = owner)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # prevent deleting owner if restaurant exists
        related_name="owned_restaurants",
    )

    restaurant_name = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.restaurant_name
    
"""
Employee
"""
    
class Employee(models.Model):

    class Position(models.TextChoices):
        FLOOR = "floor_staff", "Floor staff"
        BAR = "bar_staff", "Bar staff"
        KITCHEN = "kitchen_staff", "Kitchen staff"
        OTHER = "other", "Other"

    employee_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee",
    )

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="employees",
    )

    position = models.CharField(
        max_length=30,
        choices=Position.choices,
        default=Position.FLOOR,
    )

    active_status = models.CharField(
        max_length=20,
        default="active",
        help_text="e.g. active, inactive, on_leave",
    )

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} @ {self.restaurant.restaurant_name}"