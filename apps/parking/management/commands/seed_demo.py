import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.bookings.models import Booking, Vehicle
from apps.parking.models import ParkingSlot
from apps.payments import services as payment_services
from apps.payments.models import Payment

ADMIN = ('admin_demo', 'DemoAdmin#2026')
USERS = [('user_demo', 'DemoUser#2026', 'Asha'), ('user2_demo', 'DemoUser#2026', 'Rahul')]


class Command(BaseCommand):
    help = ('Create demo locations, accounts and a spread of bookings/payments so the dashboard has data. '
            'Uses well-known passwords, so it refuses to run when DEBUG is off unless --force is given.')

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Allow running with DEBUG=False (never on a real site).')

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError('seed_demo creates accounts with well-known passwords; refusing to run with DEBUG=False. '
                               'Use --force only on a throwaway/demo deployment.')
        User = get_user_model()
        if User.objects.filter(username=ADMIN[0]).exists():
            self.stdout.write('Demo data already exists; nothing to do.')
            self._print_logins()
            return
        call_command('seed_parking', stdout=self.stdout)
        admin = User.objects.create_user(ADMIN[0], 'admin_demo@example.com', ADMIN[1], first_name='Demo Admin')
        admin.profile.role = 'admin'
        admin.profile.save()
        users = [User.objects.create_user(n, f'{n}@example.com', pw, first_name=first) for n, pw, first in USERS]
        self._bookings(users)
        self.stdout.write(self.style.SUCCESS('Demo data created.'))
        self._print_logins()

    def _print_logins(self):
        self.stdout.write(f'  Admin: {ADMIN[0]} / {ADMIN[1]}')
        for n, pw, _ in USERS:
            self.stdout.write(f'  User:  {n} / {pw}')

    def _bookings(self, users):
        rng = random.Random(11)
        slots = list(ParkingSlot.objects.filter(slot_type='car', location__is_active=True).select_related('location').order_by('id'))
        vehicles = [Vehicle.objects.create(user=u, plate_number=f'MH15DM{i}00{j}', vehicle_type='car')
                    for i, u in enumerate(users) for j in range(1, 3)]
        now = timezone.now().replace(minute=0, second=0, microsecond=0)

        def make(day_offset, hour, hours, status, pay_state, i):
            slot, veh = slots[i % len(slots)], vehicles[i % len(vehicles)]
            start = (now + timedelta(days=day_offset)).replace(hour=hour)
            b = Booking.objects.create(user=veh.user, slot=slot, vehicle=veh, start_time=start, end_time=start + timedelta(hours=hours),
                                       hourly_rate=slot.location.hourly_rate, status=status)
            payment = payment_services.create_for_booking(b)
            created = start - timedelta(days=1, hours=rng.randint(0, 5))
            Booking.objects.filter(pk=b.pk).update(created_at=created)
            if status == Booking.COMPLETED:
                Booking.objects.filter(pk=b.pk).update(checked_in_at=start, checked_out_at=b.end_time)
            if pay_state == 'paid':
                Payment.objects.filter(pk=payment.pk).update(status='paid', amount_paid=payment.amount, method=rng.choice(['card', 'upi', 'wallet']),
                                                             transaction_id=f'SIM-DEMO{b.pk:010d}', paid_at=min(start, now))
            elif pay_state == 'refunded':
                Payment.objects.filter(pk=payment.pk).update(status='refunded', amount_paid=payment.amount, paid_at=created, refunded_at=created,
                                                             note='Simulated refund')
            elif pay_state == 'cancelled':
                Payment.objects.filter(pk=payment.pk).update(status='cancelled')

        i = 0
        for day in range(-13, 0):  # one or two finished bookings per past day
            for _ in range(rng.choice([1, 1, 2])):
                make(day, rng.choice([8, 9, 10, 14, 17]), rng.choice([1, 2, 3, 4]), 'completed', 'paid', i)
                i += 1
        make(-5, 11, 2, 'cancelled', 'refunded', i); i += 1
        make(-3, 15, 2, 'cancelled', 'cancelled', i); i += 1
        make(-2, 9, 2, 'no_show', 'cancelled', i); i += 1
        make(1, 10, 3, 'confirmed', 'paid', i); i += 1
        make(2, 12, 2, 'confirmed', 'pending', i); i += 1
        make(4, 9, 4, 'confirmed', 'pending', i)
