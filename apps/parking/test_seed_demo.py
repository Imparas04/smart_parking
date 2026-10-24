from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bookings.models import Booking
from apps.dashboard import stats
from apps.payments.models import Payment

User = get_user_model()


class SeedDemoTests(TestCase):
    def run_cmd(self, *args):
        out = StringIO()
        with override_settings(DEBUG=True):  # the test runner forces DEBUG=False; developers run this with it on
            call_command('seed_demo', *args, stdout=out)
        return out.getvalue()

    def test_creates_accounts_and_realistic_data(self):
        out = self.run_cmd()
        self.assertIn('admin_demo / DemoAdmin#2026', out)
        admin = User.objects.get(username='admin_demo')
        self.assertEqual(admin.profile.role, 'admin')
        self.assertEqual(User.objects.get(username='user_demo').profile.role, 'user')
        self.assertTrue(admin.check_password('DemoAdmin#2026'))  # stored hashed, not plain
        self.assertGreaterEqual(Booking.objects.count(), 18)
        self.assertTrue({'completed', 'cancelled', 'no_show', 'confirmed'} <= set(Booking.objects.values_list('status', flat=True)))
        self.assertTrue({'paid', 'refunded', 'cancelled', 'pending'} <= set(Payment.objects.values_list('status', flat=True)))

    def test_dashboard_has_meaningful_numbers_and_charts_have_data(self):
        self.run_cmd()
        c = stats.overview(14)
        self.assertGreater(c['cards']['revenue_total'], 0)
        self.assertGreater(c['cards']['dues_pending'], 0)
        self.assertGreater(sum(c['charts']['daily']['bookings']), 10)
        self.assertGreater(sum(c['charts']['daily']['revenue']), 0)
        self.client.login(username='admin_demo', password='DemoAdmin#2026')
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard:bookings')).status_code, 200)

    def test_is_idempotent(self):
        self.run_cmd()
        n = Booking.objects.count()
        self.assertIn('already exists', self.run_cmd())
        self.assertEqual(Booking.objects.count(), n)

    def test_refuses_when_debug_is_off_unless_forced(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command('seed_demo', stdout=StringIO())
            self.assertFalse(User.objects.filter(username='admin_demo').exists())
            call_command('seed_demo', '--force', stdout=StringIO())
        self.assertTrue(User.objects.filter(username='admin_demo').exists())
