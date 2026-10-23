import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts import services as account_services
from apps.accounts.decorators import admin_required
from apps.accounts.models import Profile
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.parking.models import ParkingLocation
from apps.payments import services as payment_services
from apps.payments.models import Payment

from . import stats
from .filters import filter_bookings

User = get_user_model()

BOOKING_ACTION_LABELS = {
    'checked_in': 'Check in', 'completed': 'Check out / complete',
    'cancelled': 'Cancel booking', 'no_show': 'Mark as no-show',
}


@admin_required
def index(request):
    days = stats.parse_days(request.GET.get('days'))
    return render(request, 'dashboard/index.html', {
        's': stats.overview(days), 'days': days, 'day_options': stats.DAY_OPTIONS, 'nav': 'overview'})


# ---- bookings ----

@admin_required
def bookings(request):
    qs, f = filter_bookings(request.GET)
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'dashboard/bookings.html', {
        'page': page, 'f': f, 'nav': 'bookings', 'querystring': params.urlencode(),
        'statuses': Booking.STATUS_CHOICES, 'pay_statuses': Payment.STATUS_CHOICES,
        'locations': ParkingLocation.objects.order_by('city', 'name')})


def _safe(value):
    """Neutralise spreadsheet formula injection in user-controlled text."""
    value = '' if value is None else str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


@admin_required
def bookings_export(request):
    qs, _ = filter_bookings(request.GET)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="bookings.csv"'
    w = csv.writer(response)
    w.writerow(['reference', 'user', 'email', 'location', 'slot', 'plate', 'vehicle_type', 'start', 'end', 'status',
                'checked_in_at', 'checked_out_at', 'amount', 'amount_paid', 'payment_status', 'created_at'])

    def ts(v):
        return timezone.localtime(v).strftime('%Y-%m-%d %H:%M') if v else ''
    for b in qs[:10000]:
        p = getattr(b, 'payment', None)
        w.writerow([b.reference, _safe(b.user.username), _safe(b.user.email), _safe(b.slot.location.name),
                    b.slot.slot_number, _safe(b.vehicle.plate_number), b.vehicle.vehicle_type, ts(b.start_time),
                    ts(b.end_time), b.status, ts(b.checked_in_at), ts(b.checked_out_at),
                    p.amount if p else '', p.amount_paid if p else '', p.status if p else '', ts(b.created_at)])
    return response


@admin_required
def booking_detail(request, reference):
    booking = get_object_or_404(Booking.objects.select_related('user', 'slot__location', 'vehicle', 'payment'),
                                reference=reference)
    payment = getattr(booking, 'payment', None)
    actions = [(s, BOOKING_ACTION_LABELS[s]) for s in sorted(booking_services.ADMIN_TRANSITIONS.get(booking.status, ()))]
    pay_options = [(s, dict(Payment.STATUS_CHOICES)[s]) for s in sorted(Payment.ADMIN_TRANSITIONS[payment.status])] if payment else []
    return render(request, 'dashboard/booking_detail.html', {
        'booking': booking, 'payment': payment, 'actions': actions, 'pay_options': pay_options, 'nav': 'bookings'})


@admin_required
@require_POST
def booking_status(request, reference):
    booking = get_object_or_404(Booking, reference=reference)
    try:
        booking_services.admin_set_status(booking, request.POST.get('status', ''))
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, 'Booking status updated.')
    return redirect('dashboard:booking_detail', reference=reference)


@admin_required
@require_POST
def payment_status(request, reference):
    booking = get_object_or_404(Booking.objects.select_related('payment'), reference=reference)
    if not hasattr(booking, 'payment'):
        messages.error(request, 'This booking has no payment record.')
        return redirect('dashboard:booking_detail', reference=reference)
    try:
        payment_services.admin_set_status(booking.payment, request.POST.get('status', ''), request.POST.get('note', '').strip())
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, 'Payment status updated.')
    return redirect('dashboard:booking_detail', reference=reference)


# ---- users ----

@admin_required
def users(request):
    qs = User.objects.select_related('profile').annotate(booking_count=Count('bookings')).order_by('-date_joined')
    q = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')
    state = request.GET.get('state', '')
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if role == 'admin':
        qs = qs.filter(Q(profile__role=Profile.ROLE_ADMIN) | Q(is_superuser=True))
    elif role == 'user':
        qs = qs.filter(profile__role=Profile.ROLE_USER, is_superuser=False)
    else:
        role = ''
    if state == 'active':
        qs = qs.filter(is_active=True)
    elif state == 'inactive':
        qs = qs.filter(is_active=False)
    else:
        state = ''
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'dashboard/users.html', {
        'page': page, 'q': q, 'role': role, 'state': state, 'nav': 'users', 'querystring': params.urlencode()})


def _user_action(request, pk, func, ok):
    target = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    try:
        func(request.user, target)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, ok.format(user=target.username))
    return redirect(request.POST.get('next') if (request.POST.get('next') or '').startswith('/dashboard/') else 'dashboard:users')


@admin_required
@require_POST
def user_active(request, pk):
    active = request.POST.get('active') == '1'
    return _user_action(request, pk, lambda a, t: account_services.set_active(a, t, active),
                        '{user} activated.' if active else '{user} deactivated.')


@admin_required
@require_POST
def user_role(request, pk):
    role = request.POST.get('role', '')
    return _user_action(request, pk, lambda a, t: account_services.set_role(a, t, role), '{user} is now ' + role + '.')
