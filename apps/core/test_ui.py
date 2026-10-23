import re
import shutil
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django.views.defaults import server_error

from apps.bookings.models import Booking, Vehicle
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments import services as pay

User = get_user_model()
PW = 'Str0ng-Pass-993'
BASE = timezone.now().replace(second=0, microsecond=0)
PROJECT = Path(settings.BASE_DIR)


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin():
    u = make_user('boss')
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_booking(user, slot, start, hours=2):
    v, _ = Vehicle.objects.get_or_create(user=user, plate_number='MH15AB1234')
    b = Booking.objects.create(user=user, slot=slot, vehicle=v, start_time=start, end_time=start + timedelta(hours=hours),
                               hourly_rate=slot.location.hourly_rate)
    pay.create_for_booking(b)
    return b


class ErrorPageTests(TestCase):
    def test_403_page_for_normal_user_on_admin_page(self):
        self.client.force_login(make_user())
        r = self.client.get(reverse('dashboard:index'))
        self.assertContains(r, 'Access denied', status_code=403)
        self.assertContains(r, 'Go home', status_code=403)

    def test_404_page_is_friendly_and_keeps_the_navigation(self):
        r = self.client.get('/no/such/page/')
        self.assertContains(r, 'Page not found', status_code=404)
        self.assertContains(r, 'Skip to main content', status_code=404)

    def test_500_page_is_standalone_and_friendly(self):
        r = server_error(RequestFactory().get('/boom/'))
        self.assertEqual(r.status_code, 500)
        self.assertIn('Something went wrong', r.content.decode())
        self.assertNotIn('Traceback', r.content.decode())

    def test_csrf_failure_page(self):
        r = Client(enforce_csrf_checks=True).post(reverse('accounts:login'), {})
        self.assertContains(r, 'Your session expired', status_code=403)


class LayoutAccessibilityTests(TestCase):
    def test_skip_link_main_landmark_favicon_and_theme(self):
        html = self.client.get(reverse('core:home')).content.decode()
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertIn('<main id="main"', html)
        self.assertIn('rel="icon"', html)
        self.assertIn('name="theme-color"', html)
        self.assertIn('<html lang="en">', html)
        self.assertIn('aria-controls="navLinks"', html)

    def test_current_section_is_marked_in_the_navigation(self):
        user = make_user()
        self.client.force_login(user)
        for url, label in ((reverse('parking:location_list'), 'Parking'), (reverse('bookings:history'), 'My Bookings'),
                           (reverse('core:home'), 'Home')):
            html = self.client.get(url).content.decode()
            current = re.findall(r'<a [^>]*aria-current="page"[^>]*>([^<]+)</a>', html)
            self.assertEqual(current, [label], url)

    def test_dashboard_link_is_marked_for_admins(self):
        self.client.force_login(make_admin())
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertEqual(re.findall(r'<a [^>]*aria-current="page"[^>]*>([^<]+)</a>', html), ['Dashboard'])


class FormStateTests(TestCase):
    def test_validation_errors_are_marked_and_linked_for_screen_readers(self):
        r = self.client.post(reverse('accounts:register'), {
            'username': 'bob', 'first_name': 'B', 'email': 'bad', 'password1': PW, 'password2': 'different'})
        html = r.content.decode()
        self.assertIn('class="field has-error"', html)
        self.assertRegex(html, r'id="id_email_errors"')
        self.assertRegex(html, r'id="id_password2_errors"')
        self.assertIn('<span class="req"', html)  # required marker

    def test_login_error_uses_alert_role(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'nobody', 'password': 'x'})
        self.assertContains(r, 'role="alert"')

    def test_messages_are_dismissible_and_errors_are_announced(self):
        user = make_user()
        loc = ParkingLocation.objects.create(name='C', address='x', city='N')
        slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
        b = make_booking(user, slot, BASE + timedelta(minutes=10))
        self.client.force_login(user)
        r = self.client.post(reverse('bookings:cancel', args=[b.reference]), follow=True)  # inside cut-off -> error
        html = r.content.decode()
        self.assertIn('alert alert-error', html)
        self.assertIn('role="alert"', html)
        self.assertIn('class="alert-close"', html)
        self.assertIn('aria-live="polite"', html)

    def test_cancel_links_are_real_urls_not_history_hacks(self):
        self.client.force_login(make_admin())
        loc = ParkingLocation.objects.create(name='C', address='x', city='N')
        slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
        expected = {reverse('parking:location_create'): reverse('parking:location_list'),
                    reverse('parking:location_update', args=[loc.pk]): loc.get_absolute_url(),
                    reverse('parking:slot_create', args=[loc.pk]): loc.get_absolute_url(),
                    reverse('parking:slot_bulk_create', args=[loc.pk]): loc.get_absolute_url(),
                    reverse('parking:slot_update', args=[slot.pk]): slot.get_absolute_url()}
        for url, cancel in expected.items():
            html = self.client.get(url).content.decode()
            self.assertIn(f'href="{cancel}">Cancel</a>', html, url)

    def test_booking_form_has_timezone_note_and_estimate_hooks(self):
        loc = ParkingLocation.objects.create(name='C', address='x', city='N')
        slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
        self.client.force_login(make_user())
        html = self.client.get(reverse('bookings:book', args=[slot.pk])).content.decode()
        self.assertIn('All times are in India time (IST)', html)
        self.assertIn(f'data-slot="{slot.pk}"', html)
        self.assertIn('data-url="/api/payments/estimate/"', html)
        self.assertIn('js/booking.js', html)

    def test_confirmations_live_in_data_attributes(self):
        user = make_user()
        loc = ParkingLocation.objects.create(name='C', address='x', city='N')
        slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
        b = make_booking(user, slot, BASE + timedelta(days=2))
        self.client.force_login(user)
        self.assertIn('data-confirm="Cancel this booking?"', self.client.get(b.get_absolute_url()).content.decode())
        self.client.force_login(make_admin())
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertIn('data-autosubmit', html)


class EmptyStateTests(TestCase):
    def test_empty_lists_explain_what_to_do(self):
        self.client.force_login(make_user())
        self.assertContains(self.client.get(reverse('bookings:history')), 'No bookings yet')
        self.assertContains(self.client.get(reverse('parking:location_list')), 'No parking locations found')
        loc = ParkingLocation.objects.create(name='Empty', address='x', city='N')
        self.assertContains(self.client.get(loc.get_absolute_url()), 'This location has no slots yet')


class ServerSideDoubleSubmitTests(TestCase):
    """The JavaScript disables buttons after a click; the server must still be safe if it is bypassed."""

    def setUp(self):
        self.user = make_user()
        loc = ParkingLocation.objects.create(name='C', address='x', city='N', hourly_rate=Decimal('20'))
        self.slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
        self.client.force_login(self.user)

    def test_submitting_the_same_booking_twice_creates_one_booking(self):
        start = BASE + timedelta(days=2)
        data = {'start_time': start.strftime('%Y-%m-%dT%H:%M'), 'end_time': (start + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
                'plate_number': 'MH15AB1234', 'vehicle_type': 'car'}
        url = reverse('bookings:book', args=[self.slot.pk])
        self.client.post(url, data)
        self.client.post(url, data)
        self.assertEqual(Booking.objects.count(), 1)

    def test_cancelling_twice_refunds_once(self):
        b = make_booking(self.user, self.slot, BASE + timedelta(days=2))
        pay.pay(b.payment, 'card')
        url = reverse('bookings:cancel', args=[b.reference])
        self.client.post(url)
        r = self.client.post(url, follow=True)
        self.assertContains(r, 'Only confirmed bookings can be cancelled')
        b.refresh_from_db()
        self.assertEqual((b.status, b.payment.status), ('cancelled', 'refunded'))


class StaticAssetTests(TestCase):
    def test_all_referenced_scripts_and_styles_exist(self):
        for path in ('js/main.js', 'js/booking.js', 'js/dashboard.js', 'js/vendor/chart.umd.min.js', 'css/style.css'):
            self.assertIsNotNone(finders.find(path), path)

    def test_no_script_references_a_missing_file_or_external_host(self):
        refs = set()
        for path in (PROJECT / 'templates').rglob('*.html'):
            refs |= set(re.findall(r'''(?:src|href)="(https?://[^"]+)"''', path.read_text()))
        self.assertEqual(refs, set())  # nothing is loaded from a CDN or other site

    @staticmethod
    def _node():
        return shutil.which('node')

    def test_javascript_files_have_valid_syntax(self):
        if not self._node():
            self.skipTest('node is not installed')
        for name in ('main.js', 'booking.js', 'dashboard.js'):
            result = subprocess.run([self._node(), '--check', str(PROJECT / 'static' / 'js' / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
