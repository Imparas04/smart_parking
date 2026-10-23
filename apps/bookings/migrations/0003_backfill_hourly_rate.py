from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')
    ParkingLocation = apps.get_model('parking', 'ParkingLocation')
    rate = ParkingLocation.objects.filter(slots__bookings=OuterRef('pk')).values('hourly_rate')[:1]
    Booking.objects.update(hourly_rate=Subquery(rate))


class Migration(migrations.Migration):
    dependencies = [('bookings', '0002_booking_checked_in_at_booking_checked_out_at_and_more'),
                    ('parking', '0001_initial')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
