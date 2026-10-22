import random

from django.core.management.base import BaseCommand

from apps.parking.models import ParkingLocation, ParkingSlot

DEMO = [
    ('City Center Parking', 'MG Road', 'Nashik', 30, 'A-', 12),
    ('Railway Station Lot', 'Nashik Road Station', 'Nashik', 20, 'R-', 10),
    ('Mall Basement Parking', 'College Road', 'Nashik', 40, 'B-', 8),
]


class Command(BaseCommand):
    help = 'Create demo parking locations and slots (skips ones that already exist).'

    def handle(self, *args, **options):
        rng = random.Random(7)
        for name, address, city, rate, prefix, count in DEMO:
            loc, created = ParkingLocation.objects.get_or_create(
                name=name, city=city, defaults={'address': address, 'hourly_rate': rate})
            if not created:
                continue
            for i in range(1, count + 1):
                ParkingSlot.objects.create(
                    location=loc, slot_number=f'{prefix}{i}',
                    slot_type='ev' if i == count else 'car',
                    status=rng.choice(['available', 'available', 'occupied', 'unavailable']))
        self.stdout.write(self.style.SUCCESS('Demo parking data ready.'))
