from django.db import migrations

from apps.payments.pricing import calculate_charge


def backfill(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')
    Payment = apps.get_model('payments', 'Payment')
    for b in Booking.objects.filter(payment__isnull=True):
        status = 'cancelled' if b.status in ('cancelled', 'no_show') else 'pending'
        Payment.objects.create(booking=b, amount=calculate_charge(b.hourly_rate, b.start_time, b.end_time),
                               status=status, is_simulated=True)


class Migration(migrations.Migration):
    dependencies = [('payments', '0001_initial'), ('bookings', '0003_backfill_hourly_rate')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
