from django.core.management.base import BaseCommand

from apps.bookings.services import mark_no_shows


class Command(BaseCommand):
    help = 'Mark confirmed bookings that ended without a check-in as no-shows (run periodically, e.g. via cron).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f'{mark_no_shows()} booking(s) marked as no-show.'))
