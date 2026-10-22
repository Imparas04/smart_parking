from django.db.models import Count, ProtectedError, Q
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import is_admin
from apps.core.exceptions import Conflict

from .models import ParkingLocation, ParkingSlot
from .serializers import LocationSerializer, SlotSerializer


class ReadAnyWriteAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request.user)


class ProtectedDeleteMixin:
    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise Conflict('Cannot delete: related bookings exist. Deactivate it instead.')


class LocationViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = LocationSerializer
    permission_classes = [ReadAnyWriteAdmin]

    def get_queryset(self):
        qs = ParkingLocation.objects.annotate(
            total_slots=Count('slots'),
            available_slots=Count('slots', filter=Q(slots__status=ParkingSlot.STATUS_AVAILABLE)),
        ).order_by('city', 'name')
        if not is_admin(self.request.user):
            qs = qs.filter(is_active=True)
        p = self.request.query_params
        if p.get('city'):
            qs = qs.filter(city__iexact=p['city'])
        if p.get('search'):
            s = p['search']
            qs = qs.filter(Q(name__icontains=s) | Q(address__icontains=s) | Q(city__icontains=s))
        if p.get('available') in ('1', 'true'):
            qs = qs.filter(available_slots__gt=0)
        return qs


class SlotViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = SlotSerializer
    permission_classes = [ReadAnyWriteAdmin]

    def get_queryset(self):
        qs = ParkingSlot.objects.select_related('location').order_by('location_id', 'slot_number')
        if not is_admin(self.request.user):
            qs = qs.filter(location__is_active=True)
        p = self.request.query_params
        for field in ('location', 'status', 'slot_type'):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        return qs
