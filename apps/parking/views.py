import re

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import admin_required
from apps.accounts.permissions import is_admin
from apps.core.utils import clean_search

from .forms import BulkSlotForm, LocationForm, SlotForm
from .models import ParkingLocation, ParkingSlot


def _visible_locations(user):
    qs = ParkingLocation.objects.all()
    return qs if is_admin(user) else qs.filter(is_active=True)


def location_list(request):
    qs = _visible_locations(request.user).annotate(
        total_slots=Count('slots'),
        available_slots=Count('slots', filter=Q(slots__status=ParkingSlot.STATUS_AVAILABLE)),
    ).order_by('city', 'name')
    q = clean_search(request.GET.get('q'))
    city = clean_search(request.GET.get('city'), 80)
    slot_type = request.GET.get('slot_type', '').strip()[:20]
    only_available = request.GET.get('available') == '1'
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q) | Q(city__icontains=q))
    if city:
        qs = qs.filter(city__iexact=city)
    if slot_type in dict(ParkingSlot.TYPE_CHOICES):
        qs = qs.filter(slots__slot_type=slot_type, slots__status=ParkingSlot.STATUS_AVAILABLE).distinct()
    if only_available:
        qs = qs.filter(available_slots__gt=0)
    page = Paginator(qs, 9).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    cities = _visible_locations(request.user).order_by('city').values_list('city', flat=True).distinct()
    return render(request, 'parking/location_list.html', {
        'page': page, 'cities': cities, 'q': q, 'city': city, 'slot_type': slot_type,
        'only_available': only_available, 'slot_types': ParkingSlot.TYPE_CHOICES,
        'querystring': params.urlencode(),
    })


def natural_slot_key(slot):
    """Sort 'A-2' before 'A-10' (plain text order would put A-10 first)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', slot.slot_number)]


def location_detail(request, pk):
    location = get_object_or_404(_visible_locations(request.user), pk=pk)
    slots = location.slots.all()
    slot_type = request.GET.get('slot_type', '')
    if slot_type in dict(ParkingSlot.TYPE_CHOICES):
        slots = slots.filter(slot_type=slot_type)
    slots = sorted(slots, key=natural_slot_key)
    counts = {r['status']: r['n'] for r in location.slots.values('status').annotate(n=Count('id'))}
    return render(request, 'parking/location_detail.html', {
        'location': location, 'slots': slots, 'slot_type': slot_type, 'slot_types': ParkingSlot.TYPE_CHOICES,
        'available': counts.get('available', 0), 'occupied': counts.get('occupied', 0),
        'unavailable': counts.get('unavailable', 0), 'total': sum(counts.values()),
    })


def slot_detail(request, pk):
    slot = get_object_or_404(ParkingSlot.objects.select_related('location'), pk=pk)
    if not slot.location.is_active and not is_admin(request.user):
        return render(request, '404.html', status=404)
    return render(request, 'parking/slot_detail.html', {'slot': slot, 'location': slot.location})


# ---- Admin management ----

@admin_required
def location_create(request):
    form = LocationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        loc = form.save()
        messages.success(request, 'Location created. Now add parking slots.')
        return redirect(loc)
    return render(request, 'parking/form.html', {'form': form, 'title': 'Add parking location',
                                                 'cancel_url': reverse('parking:location_list')})


@admin_required
def location_update(request, pk):
    loc = get_object_or_404(ParkingLocation, pk=pk)
    form = LocationForm(request.POST or None, instance=loc)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Location updated.')
        return redirect(loc)
    return render(request, 'parking/form.html', {'form': form, 'title': f'Edit {loc.name}', 'cancel_url': loc.get_absolute_url()})


@admin_required
def location_delete(request, pk):
    loc = get_object_or_404(ParkingLocation, pk=pk)
    if request.method == 'POST':
        try:
            loc.delete()
        except ProtectedError:
            messages.error(request, 'This location has bookings and cannot be deleted. Mark it inactive instead.')
            return redirect(loc)
        messages.success(request, 'Location and its slots deleted.')
        return redirect('parking:location_list')
    return render(request, 'parking/confirm_delete.html', {
        'object_name': loc.name, 'extra': f'This also deletes its {loc.slots.count()} slot(s).',
        'cancel_url': loc.get_absolute_url()})


@admin_required
def slot_create(request, location_pk):
    loc = get_object_or_404(ParkingLocation, pk=location_pk)
    form = SlotForm(request.POST or None, location=loc)
    if request.method == 'POST' and form.is_valid():
        slot = form.save(commit=False)
        slot.location = loc
        slot.save()
        messages.success(request, f'Slot {slot.slot_number} added.')
        return redirect(loc)
    return render(request, 'parking/form.html', {'form': form, 'title': f'Add slot to {loc.name}', 'cancel_url': loc.get_absolute_url()})


@admin_required
def slot_bulk_create(request, location_pk):
    loc = get_object_or_404(ParkingLocation, pk=location_pk)
    form = BulkSlotForm(request.POST or None, location=loc)
    if request.method == 'POST' and form.is_valid():
        created = form.save()
        messages.success(request, f'{len(created)} slots added.')
        return redirect(loc)
    return render(request, 'parking/form.html', {'form': form, 'title': f'Add multiple slots to {loc.name}',
                                                 'cancel_url': loc.get_absolute_url()})


@admin_required
def slot_update(request, pk):
    slot = get_object_or_404(ParkingSlot.objects.select_related('location'), pk=pk)
    form = SlotForm(request.POST or None, instance=slot)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Slot updated.')
        return redirect(slot.location)
    return render(request, 'parking/form.html', {'form': form, 'title': f'Edit slot {slot.slot_number}',
                                                 'cancel_url': slot.get_absolute_url()})


@admin_required
def slot_delete(request, pk):
    slot = get_object_or_404(ParkingSlot.objects.select_related('location'), pk=pk)
    if request.method == 'POST':
        loc = slot.location
        try:
            slot.delete()
        except ProtectedError:
            messages.error(request, 'This slot has bookings and cannot be deleted. Mark it unavailable instead.')
            return redirect(slot)
        messages.success(request, 'Slot deleted.')
        return redirect(loc)
    return render(request, 'parking/confirm_delete.html', {
        'object_name': f'slot {slot.slot_number}', 'cancel_url': slot.get_absolute_url()})
