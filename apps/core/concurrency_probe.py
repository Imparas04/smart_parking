"""Helper for apps/core/test_concurrency_file_db.py (run as a separate process, not a test).

Books the same slot and time from many threads at once against a real SQLite *file* database
(the default deployment setup) and prints what happened to each attempt as JSON.
"""
import json
import os
import sys
import threading
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DJANGO_DEBUG'] = 'True'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.bookings import services  # noqa: E402
from apps.bookings.models import Booking  # noqa: E402
from apps.parking.models import ParkingLocation, ParkingSlot  # noqa: E402

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 8


def main():
    call_command('migrate', verbosity=0)
    User = get_user_model()
    loc = ParkingLocation.objects.create(name='Race Lot', address='x', city='y')
    slot = ParkingSlot.objects.create(location=loc, slot_number='R1')
    users = [User.objects.create_user(f'racer{i}', f'r{i}@example.com', 'x') for i in range(THREADS)]
    start = (timezone.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
    end = start + timedelta(hours=2)
    barrier, outcomes = threading.Barrier(THREADS), []

    def attempt(user, plate):
        try:
            barrier.wait(timeout=20)
            services.create_booking(user, slot.pk, start, end, plate_number=plate, vehicle_type='car')
            outcomes.append('booked')
        except ValidationError:
            outcomes.append('refused')
        except Exception as exc:
            outcomes.append(f'error:{type(exc).__name__}')
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(u, f'RACE{i}00{i}')) for i, u in enumerate(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    print(json.dumps({'outcomes': sorted(outcomes), 'bookings': Booking.objects.filter(slot=slot).count()}))


main()
