from rest_framework import serializers

from .models import ParkingLocation, ParkingSlot


class LocationSerializer(serializers.ModelSerializer):
    total_slots = serializers.SerializerMethodField()
    available_slots = serializers.SerializerMethodField()

    class Meta:
        model = ParkingLocation
        fields = ['id', 'name', 'address', 'city', 'description', 'opening_time', 'closing_time',
                  'hourly_rate', 'is_active', 'total_slots', 'available_slots']


    # Lists annotate these counts (no extra queries); a freshly created/updated object computes them.
    def get_total_slots(self, obj):
        value = getattr(obj, 'total_slots', None)
        return value if value is not None else obj.slots.count()

    def get_available_slots(self, obj):
        value = getattr(obj, 'available_slots', None)
        return value if value is not None else obj.slots.filter(status=ParkingSlot.STATUS_AVAILABLE).count()


class SlotSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model = ParkingSlot
        fields = ['id', 'location', 'location_name', 'slot_number', 'slot_type', 'status', 'notes']
        validators = []  # uniqueness is checked in validate() (after normalising the number) with a clearer message

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
