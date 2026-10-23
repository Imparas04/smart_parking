from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import is_admin
from apps.core.exceptions import Conflict

from . import services
from .models import Booking, Vehicle
from .serializers import BookingCreateSerializer, BookingSerializer, VehicleSerializer


def _raise(exc):
    raise ValidationError({'detail': exc.messages})


class VehicleViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = VehicleSerializer

    def get_queryset(self):
        return Vehicle.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise Conflict('This vehicle has bookings and cannot be deleted.')


class BookingViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    lookup_field = 'reference'
    serializer_class = BookingSerializer

    def get_queryset(self):
        qs = Booking.objects.select_related('slot__location', 'vehicle', 'payment')
        if not is_admin(self.request.user):
            qs = qs.filter(user=self.request.user)
        p = self.request.query_params
        if p.get('status') in dict(Booking.STATUS_CHOICES):
            qs = qs.filter(status=p['status'])
        if p.get('slot'):
            qs = qs.filter(slot_id=p['slot'])
        if p.get('location'):
            qs = qs.filter(slot__location_id=p['location'])
        return qs

    def create(self, request, *args, **kwargs):
        ser = BookingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        vehicle = None
        if d.get('vehicle'):
            vehicle = Vehicle.objects.filter(pk=d['vehicle'], user=request.user).first()
            if vehicle is None:
                raise ValidationError({'vehicle': ['Invalid vehicle.']})
        try:
            booking = services.create_booking(
                request.user, d['slot'], d['start_time'], d['end_time'], vehicle=vehicle,
                plate_number=d.get('plate_number', ''), vehicle_type=d.get('vehicle_type', 'car'))
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, reference=None):
        booking = self.get_object()
        if booking.user_id != request.user.id:
            raise PermissionDenied('You can only cancel your own bookings.')
        try:
            booking = services.cancel_booking(booking)
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(BookingSerializer(booking).data)

    def _transition(self, request, func):
        booking = self.get_object()
        if booking.user_id != request.user.id and not is_admin(request.user):
            raise PermissionDenied('Not allowed.')
        try:
            booking = func(booking)
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(BookingSerializer(Booking.objects.select_related('slot__location', 'vehicle', 'payment').get(pk=booking.pk)).data)

    @action(detail=True, methods=['post'], url_path='check-in')
    def check_in(self, request, reference=None):
        """Owner or admin (parking attendant)."""
        return self._transition(request, services.check_in)

    @action(detail=True, methods=['post'], url_path='check-out')
    def check_out(self, request, reference=None):
        """Owner or admin (parking attendant)."""
        return self._transition(request, services.check_out)
