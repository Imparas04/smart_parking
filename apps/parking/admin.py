from django.contrib import admin

from .models import ParkingLocation, ParkingSlot


class SlotInline(admin.TabularInline):
    model = ParkingSlot
    extra = 0


@admin.register(ParkingLocation)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'hourly_rate', 'is_active')
    list_filter = ('city', 'is_active')
    search_fields = ('name', 'address', 'city')
    inlines = [SlotInline]


@admin.register(ParkingSlot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ('slot_number', 'location', 'slot_type', 'status')
    list_filter = ('status', 'slot_type', 'location')
    search_fields = ('slot_number', 'location__name')
