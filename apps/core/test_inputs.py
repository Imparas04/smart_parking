"""Edge cases: hostile or malformed input must produce a clean 4xx/redirect/200, never a 500."""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, Vehicle
from apps.core.utils import clean_search, parse_id
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments import services as pay

User = get_user_model()
PW = 'Str0ng-Pass-993'
BASE = timezone.now().replace(second=0, microsecond=0)
HUGE = '99999999999999999999999'
NASTY = ['', '0', '-1', HUGE, '-' + HUGE, 'abc', '\x00', 'a' * 5000, "' OR 1=1 --", '<script>alert(1)</script>',
         '\U0001d518\U0001d52b\U0001d526\U0001d520\U0001d52c\U0001d521\U0001d522\U0001f697', '9999-12-31', '0000-00-00',
         '2026-02-30', '1e999', 'NaN', '../../etc/passwd', '%s%n', '{{7*7}}']
PARAMS = ['q', 'city', 'slot_type', 'status', 'payment', 'location', 'slot', 'date_from', 'date_to', 'days', 'page',
          'available', 'search', 'booking', 'role', 'state', 'vehicle_type', 'start_time', 'end_time']
KEY_PARAMS = ['location', 'slot', 'page', 'days', 'date_from', 'date_to', 'start_time', 'end_time']
KEY_VALUES = ['abc', HUGE, '-1', '0000-00-00', '9999-12-31', '\x00']


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin():
    u = make_user('boss')
    u.profile.role = 'admin'
    u.profile.save()
    return u


class ParseIdTests(TestCase):
    def test_parse_id(self):
        good = {'1': 1, ' 42 ': 42, 42: 42, str(2 ** 63 - 1): 2 ** 63 - 1}
        for raw, expected in good.items():
            self.assertEqual(parse_id(raw), expected)
        for raw in ['', None, 'abc', '0', '-5', '1.5', HUGE, str(2 ** 63), '9' * 5000, [], {}]:
            self.assertIsNone(parse_id(raw), raw)

    def test_clean_search_limits_and_strips(self):
        self.assertEqual(clean_search('  hi  '), 'hi')
        self.assertEqual(len(clean_search('x' * 5000)), 100)
        self.assertEqual(clean_search(None), '')


class RegressionTests(TestCase):
    """The exact 500s found during the Phase 7 audit."""

    def setUp(self):
        self.loc = ParkingLocation.objects.create(name='Central', address='x', city='Nashik')
        self.slot = ParkingSlot.objects.create(location=self.loc, slot_number='A1')
        self.client = Client(raise_request_exception=False)
        self.client.force_login(make_admin())

    def test_api_id_filters_return_400_not_500(self):
        for url in ('/api/parking/slots/', '/api/bookings/'):
            for param in ('location', 'slot'):
                if url.endswith('slots/') and param == 'slot':
                    continue
                for bad in ('abc', HUGE, '-3', '0', '1.5'):
                    r = self.client.get(url, {param: bad})
                    self.assertEqual(r.status_code, 400, (url, param, bad))
                    self.assertIn(param, r.json())
        self.assertEqual(self.client.get('/api/parking/slots/', {'location': self.loc.pk}).json()['count'], 1)

    def test_dashboard_filters_ignore_bad_values(self):
        url = reverse('dashboard:bookings')
        for params in ({'location': HUGE}, {'location': 'abc'}, {'date_from': '0000-00-00'}, {'date_from': '9999-12-31'},
                       {'date_to': '9999-12-31'}, {'date_from': '2026-02-30'}, {'date_to': '0001-01-01'},
                       {'q': '\x00', 'date_from': '0000-00-00'}):
            r = self.client.get(url, params)
            self.assertEqual(r.status_code, 200, params)
        r = self.client.get(url, {'location': HUGE, 'date_from': '9999-12-31'})
        self.assertEqual((r.context['f']['location'], r.context['f']['date_from']), ('', ''))

    def test_overlong_search_is_truncated_not_rejected(self):
        for url in ('/parking/', '/dashboard/bookings/', '/dashboard/users/', '/api/parking/locations/'):
            r = self.client.get(url, {'q': 'a' * 5000, 'search': 'a' * 5000, 'city': 'c' * 5000})
            self.assertEqual(r.status_code, 200, url)
        self.assertEqual(len(self.client.get('/parking/', {'q': 'a' * 5000}).context['q']), 100)


class FuzzGetTests(TestCase):
    def setUp(self):
        self.loc = ParkingLocation.objects.create(name='Central', address='x', city='Nashik')
        self.slot = ParkingSlot.objects.create(location=self.loc, slot_number='A1')
        self.admin, self.user = make_admin(), make_user()
        v = Vehicle.objects.create(user=self.user, plate_number='MH15AB1234')
        self.b = Booking.objects.create(user=self.user, slot=self.slot, vehicle=v, start_time=BASE + timedelta(days=1),
                                        end_time=BASE + timedelta(days=1, hours=2), hourly_rate=Decimal('20'))
        pay.create_for_booking(self.b)
        self.urls = ['/parking/', self.loc.get_absolute_url(), self.slot.get_absolute_url(), '/api/parking/locations/',
                     '/api/parking/slots/', '/api/bookings/', '/api/payments/', '/api/bookings/vehicles/',
                     '/api/payments/estimate/', '/dashboard/', '/dashboard/bookings/', '/dashboard/bookings/export.csv',
                     '/dashboard/users/', '/bookings/']

    def sweep(self, client, label):
        bad = []
        for url in self.urls:
            for value in NASTY:  # every parameter at once
                r = client.get(url, {p: value for p in PARAMS})
                if r.status_code >= 500:
                    bad.append((label, url, 'ALL', value[:20], r.status_code))
            for param in KEY_PARAMS:  # one parameter at a time
                for value in KEY_VALUES:
                    r = client.get(url, {param: value})
                    if r.status_code >= 500:
                        bad.append((label, url, param, value[:20], r.status_code))
        return bad

    def test_no_500_for_admin_user_or_anonymous(self):
        problems = []
        for who, label in ((self.admin, 'admin'), (self.user, 'user'), (None, 'anonymous')):
            c = Client(raise_request_exception=False)
            if who:
                c.force_login(who)
            problems += self.sweep(c, label)
        self.assertEqual(problems, [])


class FuzzPostTests(TestCase):
    def setUp(self):
        self.loc = ParkingLocation.objects.create(name='Central', address='x', city='Nashik')
        self.slot = ParkingSlot.objects.create(location=self.loc, slot_number='A1')
        self.user, self.admin = make_user(), make_admin()
        self.vehicle = Vehicle.objects.create(user=self.user, plate_number='MH15AB1234')
        later = BASE + timedelta(days=3)
        self.good_form = {'start_time': later.strftime('%Y-%m-%dT%H:%M'),
                          'end_time': (later + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
                          'plate_number': 'MH15AB1234', 'vehicle_type': 'car'}
        self.good_api = {'slot': self.slot.pk, 'start_time': later.isoformat(), 'end_time': (later + timedelta(hours=2)).isoformat(),
                         'plate_number': 'MH15AB1234', 'vehicle_type': 'car'}

    def client_for(self, user):
        c = Client(raise_request_exception=False)
        c.force_login(user)
        return c

    def test_web_booking_form_never_500s(self):
        c, bad = self.client_for(self.user), []
        url = reverse('bookings:book', args=[self.slot.pk])
        for field in ('vehicle', 'start_time', 'end_time', 'plate_number', 'vehicle_type'):
            for value in NASTY + ['0001-01-01T00:00', '9999-12-31T23:59', '2026-13-45T99:99']:
                r = c.post(url, {**self.good_form, field: value})
                if r.status_code >= 500:
                    bad.append((field, value[:20], r.status_code))
        self.assertEqual(bad, [])

    def test_api_booking_create_never_500s_even_with_wrong_types(self):
        c, bad = self.client_for(self.user), []
        weird = [None, [], {}, True, 1e308, -1, 2 ** 70, 'x' * 5000, 'abc', '9999-12-31T23:59:59-05:00',
                 '0001-01-01T00:00:00+14:00', '2026-02-30T10:00:00', {'a': 1}, [1, 2]]
        for field in self.good_api:
            for value in weird + NASTY:
                r = c.post('/api/bookings/', json.dumps({**self.good_api, field: value}), content_type='application/json')
                if r.status_code >= 500:
                    bad.append((field, str(value)[:20], r.status_code))
        for raw in ('[]', '"x"', '123', 'null', '{bad json', ''):
            if c.post('/api/bookings/', raw, content_type='application/json').status_code >= 500:
                bad.append(('raw body', raw))
        self.assertEqual(bad, [])

    def test_registration_profile_and_vehicle_apis_never_500(self):
        anon, c, bad = Client(raise_request_exception=False), self.client_for(self.user), []
        reg = {'username': 'newbie', 'password': PW, 'first_name': 'N', 'email': 'n@example.com', 'phone': '9876543210'}
        for field in reg:
            for value in NASTY + [None, [], {}, 2 ** 70]:
                body = {**reg, field: value}
                body['username'] = body['username'] if field == 'username' else f'u{abs(hash((field, str(value)[:30])))}'
                if anon.post('/api/auth/register/', json.dumps(body), content_type='application/json').status_code >= 500:
                    bad.append(('register', field, str(value)[:20]))
        for field in ('first_name', 'last_name', 'email', 'phone'):
            for value in NASTY + [None, [], 2 ** 70]:
                if c.patch('/api/auth/profile/', json.dumps({field: value}), content_type='application/json').status_code >= 500:
                    bad.append(('profile', field, str(value)[:20]))
        for field in ('plate_number', 'vehicle_type', 'model_name'):
            for value in NASTY + [None, [], 2 ** 70]:
                body = {'plate_number': 'KA01XY9999', 'vehicle_type': 'car', field: value}
                if c.post('/api/bookings/vehicles/', json.dumps(body), content_type='application/json').status_code >= 500:
                    bad.append(('vehicle', field, str(value)[:20]))
        self.assertEqual(bad, [])

    def test_web_registration_and_admin_forms_never_500(self):
        bad = []
        anon = Client(raise_request_exception=False)
        good = {'username': 'x1', 'first_name': 'A', 'last_name': '', 'email': 'x1@example.com', 'phone': '', 'password1': PW, 'password2': PW}
        for field in good:
            for value in NASTY:
                data = {**good, field: value}
                if field != 'username':
                    data['username'] = f'user{abs(hash((field, value[:30])))}'
                if anon.post(reverse('accounts:register'), data).status_code >= 500:
                    bad.append(('register', field, value[:20]))
        admin = self.client_for(self.admin)
        loc = {'name': 'New', 'address': 'a', 'city': 'c', 'description': '', 'opening_time': '06:00', 'closing_time': '22:00',
               'hourly_rate': '10.00'}
        for field in loc:
            for value in NASTY + ['25:99', '1' * 40, '-0.01']:
                if admin.post(reverse('parking:location_create'), {**loc, field: value, 'name': f'N{abs(hash((field, value[:30])))}'}).status_code >= 500:
                    bad.append(('location', field, value[:20]))
        for field in ('slot_number', 'slot_type', 'status', 'notes'):
            for value in NASTY:
                data = {'slot_number': 'S1', 'slot_type': 'car', 'status': 'available', 'notes': '', field: value}
                if admin.post(reverse('parking:slot_create', args=[self.loc.pk]), data).status_code >= 500:
                    bad.append(('slot', field, value[:20]))
        for field in ('prefix', 'start', 'count', 'slot_type'):
            for value in NASTY + ['201', '1' * 30]:
                data = {'prefix': 'Z', 'start': '1', 'count': '2', 'slot_type': 'car', field: value}
                if admin.post(reverse('parking:slot_bulk_create', args=[self.loc.pk]), data).status_code >= 500:
                    bad.append(('bulk', field, value[:20]))
        ref = Booking.objects.create(user=self.user, slot=self.slot, vehicle=self.vehicle, start_time=BASE + timedelta(days=9),
                                     end_time=BASE + timedelta(days=9, hours=1), hourly_rate=Decimal('20')).reference
        for value in NASTY:
            for url, data in ((reverse('dashboard:booking_status', args=[ref]), {'status': value}),
                              (reverse('dashboard:payment_status', args=[ref]), {'status': value, 'note': value}),
                              (reverse('dashboard:user_active', args=[self.user.pk]), {'active': value, 'next': value}),
                              (reverse('dashboard:user_role', args=[self.user.pk]), {'role': value, 'next': value}),
                              (reverse('payments:pay', args=[ref]), {'method': value, 'outcome': value})):
                if admin.post(url, data).status_code >= 500:
                    bad.append((url, value[:20]))
        self.assertEqual(bad, [])
