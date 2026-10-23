import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Payment
from .pricing import calculate_charge


def create_for_booking(booking):
    amount = calculate_charge(booking.hourly_rate, booking.start_time, booking.end_time)
    payment = Payment(booking=booking, amount=amount, is_simulated=settings.PAYMENTS_SIMULATED)
    if amount == 0:
        payment.status, payment.method, payment.paid_at = Payment.PAID, 'free', timezone.now()
    payment.save()
    return payment


def _locked(booking):
    return Payment.objects.select_for_update().filter(booking=booking).first()


def pay(payment, method, outcome='success'):
    """Simulated payment. No money moves; outcome 'fail' lets you test the failure path."""
    if not settings.PAYMENTS_SIMULATED:
        raise ValidationError('No payment gateway is configured.')
    if method not in dict(Payment.METHOD_CHOICES):
        raise ValidationError('Choose a valid payment method.')
    if outcome not in ('success', 'fail'):
        raise ValidationError('Invalid simulated outcome.')
    with transaction.atomic():
        locked = Payment.objects.select_for_update().select_related('booking').get(pk=payment.pk)
        if locked.booking.status in ('cancelled', 'no_show'):
            raise ValidationError('This booking is cancelled, so there is nothing to pay.')
        if not locked.can_pay:
            raise ValidationError('There is no outstanding amount to pay.')
        locked.method = method
        if outcome == 'success':
            locked.amount_paid = locked.amount
            locked.status = Payment.PAID
            locked.paid_at = timezone.now()
            locked.transaction_id = 'SIM-' + secrets.token_hex(8).upper()
            locked.note = 'Simulated payment'
        else:
            locked.status = Payment.FAILED
            locked.note = 'Simulated payment failure'
        locked.save()
        return locked


def apply_final_amount(booking, amount):
    """Called at check-out. An overstay on a paid booking leaves a balance due."""
    payment = _locked(booking)
    if payment is None:
        return None
    payment.amount = amount
    if payment.status == Payment.PAID and payment.amount > payment.amount_paid:
        payment.status = Payment.PENDING
        payment.note = 'Balance due after overstay'
    payment.save()
    return payment


def on_booking_cancelled(booking):
    payment = _locked(booking)
    if payment is None:
        return None
    if payment.status == Payment.PAID:
        payment.status, payment.refunded_at, payment.note = Payment.REFUNDED, timezone.now(), 'Simulated refund'
    elif payment.status in (Payment.PENDING, Payment.FAILED):
        payment.status = Payment.CANCELLED
    payment.save()
    return payment


def on_booking_no_show(booking):
    payment = _locked(booking)
    if payment and payment.status in (Payment.PENDING, Payment.FAILED):
        payment.status, payment.note = Payment.CANCELLED, 'No-show: not charged'
        payment.save()
    return payment


def admin_set_status(payment, new_status, note=''):
    if new_status not in dict(Payment.STATUS_CHOICES):
        raise ValidationError('Invalid status.')
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if new_status not in Payment.ADMIN_TRANSITIONS[locked.status]:
            raise ValidationError(f'Cannot change a {locked.status} payment to {new_status}.')
        locked.status = new_status
        if new_status == Payment.PAID:
            locked.amount_paid, locked.paid_at = locked.amount, timezone.now()
            locked.method = locked.method or 'manual'
            locked.transaction_id = locked.transaction_id or 'MAN-' + secrets.token_hex(8).upper()
        elif new_status == Payment.REFUNDED:
            locked.refunded_at = timezone.now()
        locked.note = (note or f'Status set to {new_status} by admin')[:200]
        locked.save()
        return locked
