from rest_framework import serializers

from .models import ParkingLocation, ParkingSlot


class LocationSerializer(serializers.ModelSerializer):
    total_slots = serializers.IntegerField(read_only=True)
    available_slots = serializers.IntegerField(read_only=True)

    class Meta:
        model = ParkingLocation
        fields = ['id', 'name', 'address', 'city', 'description', 'opening_time', 'closing_time',
                  'hourly_rate', 'is_active', 'total_slots', 'available_slots']


class SlotSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model = ParkingSlot
        fields = ['id', 'location', 'location_name', 'slot_number', 'slot_type', 'status', 'notes']

    def validate_slot_number(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        location = attrs.get('location') or (self.instance.location if self.instance else None)
        number = attrs.get('slot_number') or (self.instance.slot_number if self.instance else None)
        if location and number:
            qs = ParkingSlot.objects.filter(location=location, slot_number=number)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'slot_number': 'This slot number already exists at this location.'})
        return attrs
