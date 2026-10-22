from rest_framework import serializers

from .models import Booking, Vehicle, normalize_plate, plate_validator


class VehicleSerializer(serializers.ModelSerializer):
    plate_number = serializers.CharField(max_length=20)  # normalised, then validated, in validate_plate_number

    class Meta:
        model = Vehicle
        fields = ['id', 'plate_number', 'vehicle_type', 'model_name']

    def validate_plate_number(self, value):
        plate = normalize_plate(value)
        plate_validator(plate)
        user = self.context['request'].user
        if Vehicle.objects.filter(user=user, plate_number=plate).exists():
            raise serializers.ValidationError('You already saved this vehicle.')
        return plate


class BookingSerializer(serializers.ModelSerializer):
    slot_number = serializers.CharField(source='slot.slot_number', read_only=True)
    location_id = serializers.IntegerField(source='slot.location_id', read_only=True)
    location_name = serializers.CharField(source='slot.location.name', read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = ['reference', 'slot', 'slot_number', 'location_id', 'location_name', 'vehicle',
                  'start_time', 'end_time', 'status', 'can_cancel', 'cancelled_at', 'created_at']
        read_only_fields = fields


class BookingCreateSerializer(serializers.Serializer):
    slot = serializers.IntegerField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    vehicle = serializers.IntegerField(required=False)
    plate_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    vehicle_type = serializers.ChoiceField(choices=Vehicle.TYPE_CHOICES, required=False, default='car')

    def validate(self, attrs):
        if not attrs.get('vehicle') and not attrs.get('plate_number'):
            raise serializers.ValidationError('Provide a vehicle id or a plate_number.')
        return attrs
