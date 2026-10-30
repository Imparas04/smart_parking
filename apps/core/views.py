from django.db.models import Count, Q
from django.shortcuts import render

from apps.parking.models import ParkingLocation, ParkingSlot


def home(request):
    locations = ParkingLocation.objects.filter(is_active=True)
    totals = ParkingSlot.objects.filter(location__is_active=True).aggregate(
        total=Count('id'), free=Count('id', filter=Q(status=ParkingSlot.STATUS_AVAILABLE)))
    featured = list(locations.annotate(
        total_slots=Count('slots'),
        available_slots=Count('slots', filter=Q(slots__status=ParkingSlot.STATUS_AVAILABLE)),
    ).order_by('-available_slots', 'name')[:3])
    cities = list(locations.order_by('city').values_list('city', flat=True).distinct()[:6])
    stats = {'locations': locations.count(), 'free': totals['free'], 'total': totals['total'], 'cities': len(cities)}
    return render(request, 'core/home.html', {'stats': stats, 'featured': featured, 'cities': cities})
