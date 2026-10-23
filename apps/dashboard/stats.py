"""Dashboard numbers. Revenue = money actually received (paid, plus part-paid balances);
refunded and cancelled payments are excluded. Daily revenue is attributed to the date of the latest payment."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.bookings.models import Booking
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments.models import Payment

DAY_OPTIONS = (7, 14, 30, 90)
DEFAULT_DAYS = 14
RECEIVED = (Payment.PAID, Payment.PENDING, Payment.FAILED)  # statuses where amount_paid is money we hold
ZERO = Decimal('0.00')


def parse_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return days if days in DAY_OPTIONS else DEFAULT_DAYS


def _money(value):
    return (value or ZERO).quantize(Decimal('0.01'))


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def overview(days=DEFAULT_DAYS):
    User = get_user_model()
    today = timezone.localdate()
    today_start = _day_start(today)
    series_start = _day_start(today - timedelta(days=days - 1))

    slot_counts = dict(ParkingSlot.objects.values_list('status').annotate(n=Count('id')))
    slot_status = {k: slot_counts.get(k, 0) for k, _ in ParkingSlot.STATUS_CHOICES}
    slots_total = sum(slot_status.values())

    booking_counts = dict(Booking.objects.values_list('status').annotate(n=Count('id')))
    booking_status = {k: booking_counts.get(k, 0) for k, _ in Booking.STATUS_CHOICES}

    received = Payment.objects.filter(status__in=RECEIVED)
    revenue_total = received.aggregate(t=Sum('amount_paid'))['t']
    revenue_today = received.filter(paid_at__gte=today_start).aggregate(t=Sum('amount_paid'))['t']
    revenue_period = received.filter(paid_at__gte=series_start).aggregate(t=Sum('amount_paid'))['t']
    dues = Payment.objects.filter(status__in=(Payment.PENDING, Payment.FAILED)).aggregate(
        t=Sum(ExpressionWrapper(F('amount') - F('amount_paid'), output_field=DecimalField())))['t']

    cards = {
        'locations_total': ParkingLocation.objects.count(),
        'locations_active': ParkingLocation.objects.filter(is_active=True).count(),
        'slots_total': slots_total,
        'slots_available': slot_status['available'],
        'slots_occupied': slot_status['occupied'],
        'slots_unavailable': slot_status['unavailable'],
        'occupancy_pct': round(100 * slot_status['occupied'] / slots_total) if slots_total else 0,
        'users_total': User.objects.count(),
        'bookings_total': sum(booking_status.values()),
        'bookings_active': booking_status['confirmed'] + booking_status['checked_in'],
        'bookings_today': Booking.objects.filter(created_at__gte=today_start).count(),
        'revenue_total': _money(revenue_total),
        'revenue_today': _money(revenue_today),
        'revenue_period': _money(revenue_period),
        'dues_pending': _money(dues),
    }

    # daily series (zero-filled)
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    per_day_bookings = {r['d']: r['n'] for r in Booking.objects.filter(created_at__gte=series_start)
                        .annotate(d=TruncDate('created_at')).values('d').annotate(n=Count('id'))}
    per_day_revenue = {r['d']: r['t'] for r in received.filter(paid_at__gte=series_start)
                       .annotate(d=TruncDate('paid_at')).values('d').annotate(t=Sum('amount_paid'))}

    # per location
    locs = ParkingLocation.objects.annotate(
        total=Count('slots'),
        available=Count('slots', filter=Q(slots__status='available')),
        occupied=Count('slots', filter=Q(slots__status='occupied')),
        unavailable=Count('slots', filter=Q(slots__status='unavailable')),
    ).order_by('city', 'name')
    rev = {r['booking__slot__location_id']: r for r in received.values('booking__slot__location_id')
           .annotate(revenue=Sum('amount_paid'), bookings=Count('id'))}
    locations = []
    for loc in locs:
        r = rev.get(loc.pk, {})
        locations.append({
            'id': loc.pk, 'name': loc.name, 'city': loc.city, 'is_active': loc.is_active,
            'total': loc.total, 'available': loc.available, 'occupied': loc.occupied,
            'unavailable': loc.unavailable,
            'occupancy_pct': round(100 * loc.occupied / loc.total) if loc.total else 0,
            'paid_bookings': r.get('bookings', 0), 'revenue': _money(r.get('revenue')),
        })

    charts = {
        'slot_status': {'labels': [l for _, l in ParkingSlot.STATUS_CHOICES], 'values': list(slot_status.values())},
        'booking_status': {'labels': [l for _, l in Booking.STATUS_CHOICES], 'values': list(booking_status.values())},
        'daily': {
            'labels': [d.strftime('%d %b') for d in dates],
            'bookings': [per_day_bookings.get(d, 0) for d in dates],
            'revenue': [float(_money(per_day_revenue.get(d))) for d in dates],
        },
        'locations': {
            'labels': [l['name'] for l in locations],
            'available': [l['available'] for l in locations],
            'occupied': [l['occupied'] for l in locations],
            'unavailable': [l['unavailable'] for l in locations],
        },
    }
    return {'days': days, 'cards': cards, 'locations': locations, 'charts': charts}


def jsonable(obj):
    """Money as 2-decimal strings, like the rest of the API (chart arrays stay numeric)."""
    if isinstance(obj, Decimal):
        return str(obj.quantize(Decimal('0.01')))
    if isinstance(obj, dict):
        return {k: (v if k == 'charts' else jsonable(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    return obj
