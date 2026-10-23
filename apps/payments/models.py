from decimal import Decimal

from django.db import models


class Payment(models.Model):
    PENDING = 'pending'
    PAID = 'paid'
    FAILED = 'failed'
    REFUNDED = 'refunded'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [(PENDING, 'Pending'), (PAID, 'Paid'), (FAILED, 'Failed'),
                      (REFUNDED, 'Refunded'), (CANCELLED, 'Cancelled')]
    # Status changes an admin may make by hand
    ADMIN_TRANSITIONS = {
        PENDING: {PAID, FAILED, CANCELLED},
        FAILED: {PENDING, PAID, CANCELLED},
        PAID: {REFUNDED},
        REFUNDED: set(),
        CANCELLED: set(),
    }
    METHOD_CHOICES = [('card', 'Card'), ('upi', 'UPI'), ('wallet', 'Wallet')]

    booking = models.OneToOneField('bookings.Booking', on_delete=models.PROTECT, related_name='payment')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'),
                                 help_text='Total charge. Estimated at booking, final at check-out.')
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    method = models.CharField(max_length=10, blank=True)
    transaction_id = models.CharField(max_length=24, null=True, blank=True, unique=True)
    is_simulated = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0), name='payment_amount_gte_0'),
            models.CheckConstraint(condition=models.Q(amount_paid__gte=0), name='payment_paid_gte_0'),
        ]

    def __str__(self):
        return f'{self.booking.reference}: {self.amount} ({self.status})'

    @property
    def amount_due(self):
        if self.status in (self.REFUNDED, self.CANCELLED):
            return Decimal('0.00')
        return max(self.amount - self.amount_paid, Decimal('0.00'))

    @property
    def can_pay(self):
        return self.status in (self.PENDING, self.FAILED) and self.amount_due > 0
