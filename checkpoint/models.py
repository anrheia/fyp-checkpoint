from django.db import models
from django.conf import settings
from django.utils import timezone
import random
import string
import uuid

# Collision-resistant enough for display; uniqueness is enforced at the DB level
def generate_pin():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


# A branch/location — the top-level entity everything else hangs off
class Business(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# Links a user to a branch with a specific role; a user can belong to multiple branches
class BusinessMembership(models.Model):
    OWNER = 'owner'
    SUPERVISOR = 'supervisor'
    EMPLOYEE = 'employee'

    role_choices = [
        (OWNER, 'Owner'),
        (SUPERVISOR, 'Supervisor'),
        (EMPLOYEE, 'Employee'),
    ]

    # Numeric ranks used by has_min_role for threshold comparisons
    role_ranks = {
        OWNER: 2,
        SUPERVISOR: 1,
        EMPLOYEE: 0,
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=role_choices, default=EMPLOYEE)
    # qr_token is used to generate a scannable QR code for clock-in/out
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    pin_code = models.CharField(max_length=6, unique=True, db_index=True, default=generate_pin)
    # Set to True when the account is created by an owner; cleared after first login password change
    must_change_password = models.BooleanField(default=False)

    class Meta:
        # One membership record per (user, branch) pair
        constraints = [
            models.UniqueConstraint(fields=['user', 'business'], name='unique_membership')
        ]

    def __str__(self):
        return f"{self.user.username} - {self.business.name} ({self.role})"

    def has_min_role(self, role):
        # Returns True if this membership's role is at least as privileged as the given role
        return self.role_ranks.get(self.role, -1) >= self.role_ranks.get(role, 999)

    @property
    def is_owner(self):
        return self.role == self.OWNER

    @property
    def is_supervisor(self):
        return self.role == self.SUPERVISOR

    @property
    def is_staff_or_above(self):
        return self.role in [self.EMPLOYEE, self.SUPERVISOR, self.OWNER]

    def is_supervisor_or_above(self):
        return self.role in [self.SUPERVISOR, self.OWNER]


# Optional extended profile attached to a membership (not to the user directly,
# so the same person can have different positions across branches)
class StaffProfile(models.Model):
    membership = models.OneToOneField(
        BusinessMembership,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    phone_number = models.CharField(max_length=20, blank=True)
    position = models.CharField(max_length=50, blank=True)
    supervisor_notes = models.TextField(blank=True)

    def __str__(self):
        return f"Profile for {self.membership.user.username} @ {self.membership.business.name}"


# A scheduled shift for a user at a branch
class WorkShift(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE, related_name='shifts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shifts')

    start = models.DateTimeField()
    end = models.DateTimeField()

    notes = models.TextField(blank=True)

    # SET_NULL so shifts survive if the creator's account is removed
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, related_name='created_shifts'
        )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.business.name} ({self.start} to {self.end})"


# Records a single clock-in/clock-out event; shift is nullable because staff
# can clock in outside of a scheduled shift
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
            models.Index(fields=['business', 'user', 'clock_in']),
        ]

    def __str__(self):
        status = "IN" if not self.clock_out else "OUT"
        return f"{self.user.username} - {self.business.name} ({status} at {self.clock_in})"

    @property
    def is_open(self):
        # True while the employee is still clocked in (no clock-out recorded yet)
        return self.clock_out is None