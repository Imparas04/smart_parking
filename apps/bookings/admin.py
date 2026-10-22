from django.contrib import admin

from .models import Booking, Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'vehicle_type', 'user')
    search_fields = ('plate_number', 'user__username')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('reference', 'user', 'slot', 'vehicle', 'start_time', 'end_time', 'status')
    list_filter = ('status',)
    search_fields = ('reference', 'user__username', 'vehicle__plate_number')
    readonly_fields = ('reference', 'created_at', 'updated_at', 'cancelled_at')
