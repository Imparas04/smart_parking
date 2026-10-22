"""Booking business rules. Used by both the web views and the REST API."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.parking.models import ParkingSlot

from .models import PLATE_RE, Booking, Vehicle, normalize_plate

import re

# slot type -> vehicle types allowed in it
COMPATIBLE = {
    'car': {'car', 'ev'},
    'bike': {'bike'},
    'ev': {'ev'},
    'accessible': {'car', 'ev'},
}


def overlapping(qs, start, end):
    return qs.filter(status__in=Booking.ACTIVE_STATUSES, start_time__lt=end, end_time__gt=start)


def _check_times(start, end, now):
    if not start or not end:
        raise ValidationError('Start and end time are required.')
    if start < now - timedelta(minutes=2):
        raise ValidationError('Start time must be in the future.')
    if end <= start:
        raise ValidationError('End time must be after the start time.')
    minutes = (end - start).total_seconds() / 60
    if minutes < settings.BOOKING_MIN_MINUTES:
        raise ValidationError(f'Minimum booking duration is {settings.BOOKING_MIN_MINUTES} minutes.')
    if minutes > settings.BOOKING_MAX_HOURS * 60:
        raise ValidationError(f'Maximum booking duration is {settings.BOOKING_MAX_HOURS} hours.')
    if start > now + timedelta(days=settings.BOOKING_MAX_ADVANCE_DAYS):
        raise ValidationError(f'Bookings can be made at most {settings.BOOKING_MAX_ADVANCE_DAYS} days ahead.')


def _check_hours(location, start, end):
    if location.is_24h:
        return
    ls, le = timezone.localtime(start), timezone.localtime(end)
    if ls.date() != le.date():
        raise ValidationError('This location is not open overnight; the booking must end on the same day.')
    if ls.time() < location.opening_time or le.time() > location.closing_time:
        raise ValidationError(
            f'This location is open {location.opening_time:%H:%M}-{location.closing_time:%H:%M}.')


def _resolve_vehicle(user, vehicle, plate_number, vehicle_type):
    if vehicle is not None:
        if vehicle.user_id != user.id:
            raise ValidationError('Invalid vehicle.')
        return vehicle
    plate = normalize_plate(plate_number)
    if not plate:
        raise ValidationError('Select a saved vehicle or enter a plate number.')
    if not re.match(PLATE_RE, plate):
        raise ValidationError('Enter a valid plate number (4-15 letters, digits or hyphens).')
    if vehicle_type not in dict(Vehicle.TYPE_CHOICES):
        raise ValidationError('Select a valid vehicle type.')
    obj, _ = Vehicle.objects.get_or_create(user=user, plate_number=plate, defaults={'vehicle_type': vehicle_type})
    return obj


def create_booking(user, slot_id, start, end, vehicle=None, plate_number='', vehicle_type='car'):
    now = timezone.now()
    _check_times(start, end, now)
    with transaction.atomic():
        # Lock the slot row so concurrent requests for the same slot are serialised
        # (MySQL/PostgreSQL row lock; SQLite serialises writers at database level).
        try:
            slot = ParkingSlot.objects.select_for_update().select_related('location').get(pk=slot_id)
        except ParkingSlot.DoesNotExist:
            raise ValidationError('Parking slot not found.')
        if not slot.location.is_active:
            raise ValidationError('This location is not accepting bookings.')
        if slot.status == ParkingSlot.STATUS_UNAVAILABLE:
            raise ValidationError('This slot is currently unavailable.')
        _check_hours(slot.location, start, end)
        veh = _resolve_vehicle(user, vehicle, plate_number, vehicle_type)
        if veh.vehicle_type not in COMPATIBLE[slot.slot_type]:
            raise ValidationError(f'A {veh.get_vehicle_type_display().lower()} cannot use a {slot.get_slot_type_display().lower()} slot.')
        if overlapping(Booking.objects.filter(slot=slot), start, end).exists():
            raise ValidationError('This slot is already booked for part of that time. Choose another time or slot.')
        if overlapping(Booking.objects.filter(vehicle=veh), start, end).exists():
            raise ValidationError('This vehicle already has a booking during that time.')
        return Booking.objects.create(user=user, slot=slot, vehicle=veh, start_time=start, end_time=end)


def cancel_booking(booking):
    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        reason = locked.cancel_block_reason()
        if reason:
            raise ValidationError(reason)
        locked.status = Booking.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.save(update_fields=['status', 'cancelled_at', 'updated_at'])
        return locked
