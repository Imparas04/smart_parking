import math
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings


def billable_blocks(start, end):
    minutes = (end - start).total_seconds() / 60
    return max(1, math.ceil(minutes / settings.BILLING_BLOCK_MINUTES))


def calculate_charge(hourly_rate, start, end):
    """Server-side parking charge: rate x billing blocks (rounded up, at least one block)."""
    block_hours = Decimal(settings.BILLING_BLOCK_MINUTES) / Decimal(60)
    amount = Decimal(hourly_rate) * Decimal(billable_blocks(start, end)) * block_hours
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
