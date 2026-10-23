from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole, is_admin
from apps.parking.models import ParkingSlot

from . import services
from .models import Payment
from .pricing import billable_blocks, calculate_charge
from .serializers import (EstimateSerializer, PayInputSerializer, PaymentSerializer,
                          StatusUpdateSerializer)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        qs = Payment.objects.select_related('booking')
        if not is_admin(self.request.user):
            qs = qs.filter(booking__user=self.request.user)
        p = self.request.query_params
        if p.get('status') in dict(Payment.STATUS_CHOICES):
            qs = qs.filter(status=p['status'])
        if p.get('booking'):
            qs = qs.filter(booking__reference=p['booking'][:20])
        return qs

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], authentication_classes=[])
    def estimate(self, request):
        """Fee check: what would this slot cost for this period? Computed on the server."""
        ser = EstimateSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if d['end_time'] <= d['start_time']:
            raise ValidationError({'end_time': ['End time must be after the start time.']})
        slot = ParkingSlot.objects.select_related('location').filter(pk=d['slot']).first()
        if slot is None:
            raise ValidationError({'slot': ['Parking slot not found.']})
        rate = slot.location.hourly_rate
        return Response({
            'hourly_rate': str(rate),
            'billing_blocks': billable_blocks(d['start_time'], d['end_time']),
            'amount': str(calculate_charge(rate, d['start_time'], d['end_time'])),
            'currency': 'INR',
        })

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        payment = self.get_object()
        if payment.booking.user_id != request.user.id:
            raise PermissionDenied('You can only pay for your own bookings.')
        ser = PayInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            payment = services.pay(payment, ser.validated_data['method'], ser.validated_data['outcome'])
        except DjangoValidationError as exc:
            raise ValidationError({'detail': exc.messages})
        return Response(PaymentSerializer(payment).data)  # check "status": a simulated failure is still a 200

    @action(detail=True, methods=['patch'], url_path='status', permission_classes=[IsAdminRole])
    def set_status(self, request, pk=None):
        payment = self.get_object()
        ser = StatusUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            payment = services.admin_set_status(payment, ser.validated_data['status'], ser.validated_data.get('note', ''))
        except DjangoValidationError as exc:
            raise ValidationError({'detail': exc.messages})
        return Response(PaymentSerializer(payment).data)
