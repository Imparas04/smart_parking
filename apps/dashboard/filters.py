from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.bookings.models import Booking, normalize_plate
from apps.payments.models import Payment


def _bound(value, add_days=0):
    day = parse_date(value or '')
    if not day:
        return None
    return timezone.make_aware(datetime.combine(day + timedelta(days=add_days), time.min))


def filter_bookings(params):
    """Return (queryset, cleaned filter values) for the admin bookings list and export."""
    qs = Booking.objects.select_related('user', 'slot__location', 'vehicle', 'payment').order_by('-created_at')
    f = {k: (params.get(k) or '').strip() for k in ('q', 'status', 'payment', 'location', 'date_from', 'date_to')}
    if f['q']:
        q = f['q']
        qs = qs.filter(Q(reference__icontains=q) | Q(user__username__icontains=q) | Q(user__email__icontains=q)
                       | Q(vehicle__plate_number__icontains=normalize_plate(q)))
    if f['status'] in dict(Booking.STATUS_CHOICES):
        qs = qs.filter(status=f['status'])
    else:
        f['status'] = ''
    if f['payment'] in dict(Payment.STATUS_CHOICES):
        qs = qs.filter(payment__status=f['payment'])
    else:
        f['payment'] = ''
    if f['location'].isdigit():
        qs = qs.filter(slot__location_id=int(f['location']))
    else:
        f['location'] = ''
    start, end = _bound(f['date_from']), _bound(f['date_to'], add_days=1)
    if start:
        qs = qs.filter(start_time__gte=start)
    else:
        f['date_from'] = ''
    if end:
        qs = qs.filter(start_time__lt=end)
    else:
        f['date_to'] = ''
    return qs, f
