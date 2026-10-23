import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

PLATE_RE = r'^[A-Z0-9-]{4,15}$'
plate_validator = RegexValidator(PLATE_RE, 'Enter a valid plate number (4-15 letters, digits or hyphens).')


def normalize_plate(value):
    return re.sub(r'\s+', '', value or '').upper()


class Vehicle(models.Model):
    TYPE_CHOICES = [('car', 'Car'), ('bike', 'Bike'), ('ev', 'Electric vehicle')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vehicles')
    plate_number = models.CharField(max_length=15, validators=[plate_validator])
    vehicle_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='car')
    model_name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['plate_number']
        constraints = [models.UniqueConstraint(fields=['user', 'plate_number'], name='uniq_vehicle_per_user')]

    def __str__(self):
        return f'{self.plate_number} ({self.get_vehicle_type_display()})'

    def save(self, *args, **kwargs):
        self.plate_number = normalize_plate(self.plate_number)
        super().save(*args, **kwargs)


class Booking(models.Model):
    CONFIRMED = 'confirmed'
    CHECKED_IN = 'checked_in'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    NO_SHOW = 'no_show'
    STATUS_CHOICES = [
        (CONFIRMED, 'Confirmed'), (CHECKED_IN, 'Checked in'),
        (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled'), (NO_SHOW, 'No show'),
    ]
    ACTIVE_STATUSES = (CONFIRMED, CHECKED_IN)  # these block a slot's time window

    reference = models.CharField(max_length=12, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bookings')
    slot = models.ForeignKey('parking.ParkingSlot', on_delete=models.PROTECT, related_name='bookings')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='bookings')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=CONFIRMED)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0,
                                      help_text='Rate snapshot taken when the booking was made.')
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_time']
        indexes = [models.Index(fields=['slot', 'start_time', 'end_time'])]
        constraints = [models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')),
                                              name='booking_end_after_start')]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if not self.reference:
            while True:
                ref = 'PK-' + secrets.token_hex(4).upper()
                if not Booking.objects.filter(reference=ref).exists():
                    self.reference = ref
                    break
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('bookings:detail', args=[self.reference])

    @property
    def duration(self):
        return self.end_time - self.start_time

    def cancel_block_reason(self, now=None):
        """Return why this booking can't be cancelled, or None if it can."""
        now = now or timezone.now()
        if self.status != self.CONFIRMED:
            return f'Only confirmed bookings can be cancelled (this one is {self.get_status_display().lower()}).'
        cutoff = timedelta(minutes=settings.BOOKING_CANCEL_CUTOFF_MINUTES)
        if self.start_time - now < cutoff:
            return f'Bookings can only be cancelled at least {settings.BOOKING_CANCEL_CUTOFF_MINUTES} minutes before the start time.'
        return None

    def check_in_block_reason(self, now=None):
        now = now or timezone.now()
        if self.status != self.CONFIRMED:
            return f'Only confirmed bookings can be checked in (this one is {self.get_status_display().lower()}).'
        opens = self.start_time - timedelta(minutes=settings.BOOKING_CHECKIN_EARLY_MINUTES)
        if now < opens:
            return f'Check-in opens {settings.BOOKING_CHECKIN_EARLY_MINUTES} minutes before the start time.'
        if now > self.end_time:
            return 'This booking has already ended.'
        return None

    def check_out_block_reason(self):
        if self.status != self.CHECKED_IN:
            return f'Only checked-in bookings can be checked out (this one is {self.get_status_display().lower()}).'
        return None

    @property
    def can_check_in(self):
        return self.check_in_block_reason() is None

    @property
    def can_check_out(self):
        return self.check_out_block_reason() is None

    @property
    def can_cancel(self):
        return self.cancel_block_reason() is None
