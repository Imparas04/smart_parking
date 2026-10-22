from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    r'^\+?[0-9]{10,15}$', 'Enter a valid phone number (10-15 digits, optional leading +).'
)


class Profile(models.Model):
    ROLE_USER = 'user'
    ROLE_ADMIN = 'admin'
    ROLE_CHOICES = [(ROLE_USER, 'User'), (ROLE_ADMIN, 'Admin')]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.get_username()} ({self.role})'

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN or self.user.is_superuser
