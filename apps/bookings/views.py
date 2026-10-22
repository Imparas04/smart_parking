from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.parking.models import ParkingSlot

from . import services
from .forms import BookingForm
from .models import Booking


@login_required
def book_slot(request, slot_pk):
    slot = get_object_or_404(ParkingSlot.objects.select_related('location'), pk=slot_pk)
    if not slot.location.is_active or slot.status == ParkingSlot.STATUS_UNAVAILABLE:
        messages.error(request, 'This slot is not available for booking.')
        return redirect(slot)
    form = BookingForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            booking = services.create_booking(
                request.user, slot.pk, d['start_time'], d['end_time'], vehicle=d['vehicle'],
                plate_number=d['plate_number'], vehicle_type=d['vehicle_type'] or 'car')
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
        else:
            messages.success(request, f'Booking confirmed. Your reference is {booking.reference}.')
            return redirect(booking)
    busy = slot.bookings.filter(status__in=Booking.ACTIVE_STATUSES, end_time__gt=timezone.now()) \
        .order_by('start_time')[:10]
    return render(request, 'bookings/book.html', {'form': form, 'slot': slot, 'location': slot.location, 'busy': busy})


@login_required
def history(request):
    qs = request.user.bookings.select_related('slot__location', 'vehicle')
    status = request.GET.get('status', '')
    if status in dict(Booking.STATUS_CHOICES):
        qs = qs.filter(status=status)
    page = Paginator(qs, 10).get_page(request.GET.get('page'))
    return render(request, 'bookings/history.html', {
        'page': page, 'status': status, 'statuses': Booking.STATUS_CHOICES})


@login_required
def detail(request, reference):
    booking = get_object_or_404(
        Booking.objects.select_related('slot__location', 'vehicle'), reference=reference, user=request.user)
    return render(request, 'bookings/detail.html', {
        'booking': booking, 'cancel_reason': booking.cancel_block_reason()})


@login_required
@require_POST
def cancel(request, reference):
    booking = get_object_or_404(Booking, reference=reference, user=request.user)
    try:
        services.cancel_booking(booking)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, 'Booking cancelled.')
    return redirect(booking)
