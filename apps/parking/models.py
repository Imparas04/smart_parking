from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class ParkingLocation(models.Model):
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    opening_time = models.TimeField(default='00:00')
    closing_time = models.TimeField(default='23:59')
    hourly_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('20.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Parking charge per hour (used for pricing in a later phase).',
    )
    is_active = models.BooleanField(default=True, help_text='Inactive locations are hidden from users.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['city', 'name']
        constraints = [models.UniqueConstraint(fields=['name', 'city'], name='uniq_location_name_city')]

    def __str__(self):
        return f'{self.name} ({self.city})'

    def get_absolute_url(self):
        return reverse('parking:location_detail', args=[self.pk])


class ParkingSlot(models.Model):
    STATUS_AVAILABLE = 'available'
    STATUS_OCCUPIED = 'occupied'
    STATUS_UNAVAILABLE = 'unavailable'
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_OCCUPIED, 'Occupied'),
        (STATUS_UNAVAILABLE, 'Unavailable'),
    ]
    TYPE_CHOICES = [('car', 'Car'), ('bike', 'Bike'), ('ev', 'EV charging'), ('accessible', 'Accessible')]

    location = models.ForeignKey(ParkingLocation, on_delete=models.CASCADE, related_name='slots')
    slot_number = models.CharField(max_length=20)
    slot_type = models.CharField(max_length=12, choices=TYPE_CHOICES, default='car')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['location', 'slot_number']
        constraints = [models.UniqueConstraint(fields=['location', 'slot_number'], name='uniq_slot_per_location')]

    def __str__(self):
        return f'{self.location.name} / {self.slot_number}'

    def save(self, *args, **kwargs):
        self.slot_number = self.slot_number.strip().upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('parking:slot_detail', args=[self.pk])
