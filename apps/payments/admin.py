from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'amount_paid', 'status', 'method', 'transaction_id', 'paid_at')
    list_filter = ('status', 'method')
    search_fields = ('booking__reference', 'transaction_id')
    readonly_fields = ('created_at', 'updated_at')
