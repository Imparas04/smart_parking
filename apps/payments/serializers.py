from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    booking = serializers.CharField(source='booking.reference', read_only=True)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Payment
        fields = ['id', 'booking', 'amount', 'amount_paid', 'amount_due', 'status', 'method',
                  'transaction_id', 'is_simulated', 'note', 'paid_at', 'refunded_at', 'created_at']
        read_only_fields = fields


class PayInputSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.METHOD_CHOICES)
    outcome = serializers.ChoiceField(choices=['success', 'fail'], default='success')


class StatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Payment.STATUS_CHOICES)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class EstimateSerializer(serializers.Serializer):
    slot = serializers.IntegerField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
