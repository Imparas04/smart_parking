import os
import re
import subprocess
import sys
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.throttling import SimpleRateThrottle

from apps.bookings.models import Booking, Vehicle
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments import services as pay
from config.env import load_env_file

User = get_user_model()
PW = 'Str0ng-Pass-993'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'sec-tests'}}
BASE = timezone.now().replace(second=0, microsecond=0)
PROJECT = Path(settings.BASE_DIR)


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin(name='boss'):
    u = make_user(name)
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_world():
    loc = ParkingLocation.objects.create(name='Central', address='MG Road', city='Nashik', hourly_rate=Decimal('20'))
    slot = ParkingSlot.objects.create(location=loc, slot_number='A1')
    return loc, slot


def make_booking(user, slot, start=None, hours=2, plate='MH15AB1234', status='confirmed'):
    start = start or BASE + timedelta(days=1)
    v, _ = Vehicle.objects.get_or_create(user=user, plate_number=plate)
    b = Booking.objects.create(user=user, slot=slot, vehicle=v, start_time=start, end_time=start + timedelta(hours=hours),
                               status=status, hourly_rate=slot.location.hourly_rate)
    pay.create_for_booking(b)
    return b


# ---------------------------------------------------------------- login throttling

@override_settings(CACHES=LOCMEM)
class WebLoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.url = reverse('accounts:login')

    def tearDown(self):
        cache.clear()

    def attempt(self, username='alice', password='wrong', **extra):
        return self.client.post(self.url, {'username': username, 'password': password}, **extra)

    def test_locks_after_repeated_failures_even_for_the_right_password(self):
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER):
            self.assertEqual(self.attempt().status_code, 200)
        r = self.attempt(password=PW)  # correct password, but locked out
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, 'Too many failed login attempts', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_success_resets_the_counter(self):
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER - 1):
            self.attempt()
        self.assertEqual(self.attempt(password=PW).status_code, 302)
        self.client.logout()
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER - 1):
            self.assertEqual(self.attempt().status_code, 200)

    def test_other_ips_and_other_users_are_not_locked_out(self):
        make_user('bob')
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER):
            self.attempt()
        self.assertEqual(self.attempt(password=PW).status_code, 429)
        self.assertEqual(self.attempt(password=PW, REMOTE_ADDR='10.9.9.9').status_code, 302)  # attacker's lock does not hit others
        self.client.logout()
        self.assertEqual(self.attempt('bob', PW).status_code, 302)

    def test_spoofed_forwarded_header_does_not_evade_the_lock(self):
        for i in range(settings.LOGIN_MAX_FAILURES_PER_USER):
            self.attempt(HTTP_X_FORWARDED_FOR=f'1.2.3.{i}')
        self.assertEqual(self.attempt(password=PW, HTTP_X_FORWARDED_FOR='8.8.8.8').status_code, 429)

    def test_per_ip_limit_stops_username_spraying(self):
        for i in range(settings.LOGIN_MAX_FAILURES_PER_IP):
            self.attempt(username=f'ghost{i}')
        self.assertEqual(self.attempt(username='brand-new', password=PW).status_code, 429)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_forwarded_header_is_used_only_behind_a_trusted_proxy(self):
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER):
            self.attempt(HTTP_X_FORWARDED_FOR='6.6.6.6, 7.7.7.7')
        self.assertEqual(self.attempt(password=PW, HTTP_X_FORWARDED_FOR='1.1.1.1, 7.7.7.7').status_code, 429)  # same proxy-added IP
        self.assertEqual(self.attempt(password=PW, HTTP_X_FORWARDED_FOR='1.1.1.1, 9.9.9.9').status_code, 302)


@override_settings(CACHES=LOCMEM)
class ApiThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        make_user()

    def tearDown(self):
        cache.clear()

    def login(self, password='wrong', **extra):
        return self.client.post('/api/auth/login/', {'username': 'alice', 'password': password},
                                content_type='application/json', **extra)

    def test_api_login_lockout_returns_429_with_retry_after(self):
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_USER):
            self.assertEqual(self.login().status_code, 400)
        r = self.login(PW)
        self.assertEqual(r.status_code, 429)
        self.assertIn('Retry-After', r)

    def test_api_rate_limit_scope(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'auth': '3/min'}):
            codes = [self.client.post('/api/auth/register/', {'username': f'u{i}', 'password': PW, 'first_name': 'x',
                                                              'email': f'u{i}@example.com'}, content_type='application/json').status_code
                     for i in range(5)]
        self.assertEqual(codes, [201, 201, 201, 429, 429])

    def test_garbage_login_payloads_do_not_crash(self):
        for body in ('[]', '"x"', '{"username": ["a"], "password": 1}', '{"username": null}'):
            r = self.client.post('/api/auth/login/', body, content_type='application/json')
            self.assertIn(r.status_code, (400, 429))


# ---------------------------------------------------------------- deactivated accounts

class DeactivatedAccountTests(TestCase):
    def test_existing_session_and_token_stop_working(self):
        user = make_user()
        token = Token.objects.create(user=user)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/profile/', HTTP_AUTHORIZATION=f'Token {token.key}').status_code, 200)
        user.is_active = False
        user.save()
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 302)  # session no longer valid
        self.assertEqual(Client().get('/api/auth/profile/', HTTP_AUTHORIZATION=f'Token {token.key}').status_code, 401)


# ---------------------------------------------------------------- CSRF

class CsrfTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.user = make_user()
        self.loc, self.slot = make_world()
        self.b = make_booking(self.user, self.slot)

    def test_every_state_changing_web_endpoint_rejects_missing_csrf_token(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.user)
        ref = self.b.reference
        admin_posts = [reverse('parking:location_create'), reverse('parking:location_update', args=[self.loc.pk]),
                       reverse('parking:location_delete', args=[self.loc.pk]), reverse('parking:slot_create', args=[self.loc.pk]),
                       reverse('parking:slot_bulk_create', args=[self.loc.pk]), reverse('parking:slot_update', args=[self.slot.pk]),
                       reverse('parking:slot_delete', args=[self.slot.pk]), reverse('dashboard:booking_status', args=[ref]),
                       reverse('dashboard:payment_status', args=[ref]), reverse('dashboard:user_active', args=[self.user.pk]),
                       reverse('dashboard:user_role', args=[self.user.pk])]
        user_posts = [reverse('accounts:logout'), reverse('accounts:profile'), reverse('accounts:password_change'),
                      reverse('bookings:book', args=[self.slot.pk]), reverse('bookings:cancel', args=[ref]),
                      reverse('bookings:check_in', args=[ref]), reverse('bookings:check_out', args=[ref]), reverse('payments:pay', args=[ref])]
        for url in admin_posts:
            self.assertEqual(c.post(url, {'status': 'cancelled'}).status_code, 403, url)
        for url in user_posts:
            self.assertEqual(owner.post(url, {}).status_code, 403, url)
        anon = Client(enforce_csrf_checks=True)
        for url in (reverse('accounts:login'), reverse('accounts:register')):
            self.assertEqual(anon.post(url, {}).status_code, 403, url)
        self.b.refresh_from_db()
        self.assertEqual((self.b.status, ParkingLocation.objects.count()), ('confirmed', 1))  # nothing changed

    def test_csrf_failure_page_is_friendly(self):
        r = Client(enforce_csrf_checks=True).post(reverse('accounts:login'), {})
        self.assertContains(r, 'session expired', status_code=403)

    def test_session_authenticated_api_writes_need_csrf_but_token_auth_does_not(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        body = {'slot': self.slot.pk, 'start_time': (BASE + timedelta(days=3)).isoformat(),
                'end_time': (BASE + timedelta(days=3, hours=1)).isoformat(), 'plate_number': 'MH15AB1234'}
        self.assertEqual(c.post('/api/bookings/', body, content_type='application/json').status_code, 403)
        token = Token.objects.create(user=self.user)
        r = Client(enforce_csrf_checks=True).post('/api/bookings/', body, content_type='application/json',
                                                  HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertEqual(r.status_code, 201, r.content)

    def test_all_post_forms_in_templates_have_a_csrf_token(self):
        missing = []
        for path in (PROJECT / 'templates').rglob('*.html'):
            text = path.read_text()
            for m in re.finditer(r'<form\b[^>]*>.*?</form>', text, re.S):
                if re.search(r'method="post"', m.group(0)[:m.group(0).index('>')], re.I) and 'csrf_token' not in m.group(0):
                    missing.append(str(path))
        self.assertEqual(missing, [])


# ---------------------------------------------------------------- ownership / IDOR

class OwnershipTests(TestCase):
    """User B must not be able to read or change anything that belongs to user A, on the web or the API."""

    def setUp(self):
        self.loc, self.slot = make_world()
        self.a, self.b = make_user('alice'), make_user('bob')
        self.booking = make_booking(self.a, self.slot, start=BASE + timedelta(minutes=5), hours=2)
        self.vehicle = self.booking.vehicle
        self.ref = self.booking.reference
        self.pid = self.booking.payment.pk

    def snapshot(self):
        self.booking.refresh_from_db()
        self.booking.payment.refresh_from_db()
        return (self.booking.status, self.booking.payment.status, Vehicle.objects.count())

    def test_other_user_gets_404_or_403_everywhere_and_nothing_changes(self):
        before = self.snapshot()
        self.client.force_login(self.b)
        api = lambda m, url, body=None: getattr(self.client, m)(url, body or {}, content_type='application/json')
        web = [('get', reverse('bookings:detail', args=[self.ref])), ('post', reverse('bookings:cancel', args=[self.ref])),
               ('post', reverse('bookings:check_in', args=[self.ref])), ('post', reverse('bookings:check_out', args=[self.ref])),
               ('get', reverse('payments:pay', args=[self.ref])), ('post', reverse('payments:pay', args=[self.ref]))]
        for method, url in web:
            self.assertEqual(getattr(self.client, method)(url, {'method': 'card', 'outcome': 'success'}).status_code, 404, url)
        for method, url, body in [('get', f'/api/bookings/{self.ref}/', None), ('post', f'/api/bookings/{self.ref}/cancel/', None),
                                  ('post', f'/api/bookings/{self.ref}/check-in/', None), ('post', f'/api/bookings/{self.ref}/check-out/', None),
                                  ('get', f'/api/payments/{self.pid}/', None),
                                  ('post', f'/api/payments/{self.pid}/pay/', {'method': 'card'}),
                                  ('get', f'/api/bookings/vehicles/{self.vehicle.pk}/', None),
                                  ('delete', f'/api/bookings/vehicles/{self.vehicle.pk}/', None)]:
            self.assertEqual(api(method, url, body).status_code, 404, url)
        self.assertEqual(self.client.get('/api/bookings/').json()['count'], 0)
        self.assertEqual(self.client.get('/api/payments/').json()['count'], 0)
        self.assertEqual(self.client.get('/api/bookings/vehicles/').json()['count'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_cannot_book_with_someone_elses_vehicle(self):
        self.client.force_login(self.b)
        later = BASE + timedelta(days=5)
        r = self.client.post(reverse('bookings:book', args=[self.slot.pk]), {
            'start_time': later.strftime('%Y-%m-%dT%H:%M'), 'end_time': (later + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
            'vehicle': self.vehicle.pk})
        self.assertEqual(r.status_code, 200)
        r = self.client.post('/api/bookings/', {'slot': self.slot.pk, 'start_time': later.isoformat(),
                                                'end_time': (later + timedelta(hours=1)).isoformat(), 'vehicle': self.vehicle.pk},
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Booking.objects.filter(user=self.b).count(), 0)

    def test_anonymous_is_turned_away_from_every_private_url(self):
        urls = [reverse('bookings:history'), reverse('bookings:detail', args=[self.ref]), reverse('payments:pay', args=[self.ref]),
                reverse('accounts:profile'), reverse('bookings:book', args=[self.slot.pk])]
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 302, u)
        for u in ('/api/bookings/', f'/api/bookings/{self.ref}/', '/api/payments/', '/api/bookings/vehicles/', '/api/auth/profile/'):
            self.assertEqual(self.client.get(u).status_code, 401, u)

    def test_role_downgrade_takes_effect_immediately(self):
        admin = make_admin()
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 200)
        admin.profile.role = 'user'
        admin.profile.save()
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 403)

    def test_promoting_to_admin_does_not_grant_django_admin_access(self):
        admin = make_admin()
        self.client.force_login(admin)
        r = self.client.get('/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])


# ---------------------------------------------------------------- headers

class SecurityHeaderTests(TestCase):
    def test_security_headers_on_pages(self):
        r = self.client.get(reverse('core:home'))
        csp = r['Content-Security-Policy']
        self.assertIn("script-src 'self'", csp)
        self.assertNotRegex(csp, r"script-src[^;]*'unsafe-inline'")
        self.assertNotRegex(csp, r"script-src[^;]*'unsafe-eval'")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertEqual(r['X-Frame-Options'], 'DENY')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['Referrer-Policy'], 'same-origin')
        self.assertIn('camera=()', r['Permissions-Policy'])

    def test_csp_not_applied_to_django_admin_and_report_only_mode(self):
        self.assertNotIn('Content-Security-Policy', self.client.get('/admin/login/'))
        with override_settings(CSP_REPORT_ONLY=True):
            r = self.client.get(reverse('core:home'))
        self.assertIn('Content-Security-Policy-Report-Only', r)
        self.assertNotIn('Content-Security-Policy', r)

    def test_session_cookie_flags(self):
        make_user()
        r = self.client.post(reverse('accounts:login'), {'username': 'alice', 'password': PW})
        cookie = r.cookies['sessionid']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')

    def test_api_responses_are_json_only(self):
        r = self.client.get('/api/parking/locations/', HTTP_ACCEPT='text/html')
        self.assertEqual(r['Content-Type'], 'application/json')


class NoInlineScriptTests(TestCase):
    """The CSP forbids inline scripts, so no page may rely on them."""

    def setUp(self):
        self.loc, self.slot = make_world()
        self.user, self.admin = make_user(), make_admin()
        self.b = make_booking(self.user, self.slot)

    def pages(self):
        user_pages = [reverse('bookings:history'), reverse('bookings:detail', args=[self.b.reference]),
                      reverse('payments:pay', args=[self.b.reference]), reverse('bookings:book', args=[self.slot.pk]),
                      reverse('accounts:profile'), reverse('accounts:password_change')]
        public = [reverse('core:home'), reverse('accounts:login'), reverse('accounts:register'),
                  reverse('parking:location_list'), self.loc.get_absolute_url(), self.slot.get_absolute_url()]
        admin = [reverse('dashboard:index'), reverse('dashboard:bookings'), reverse('dashboard:users'),
                 reverse('dashboard:booking_detail', args=[self.b.reference]), reverse('parking:location_create'),
                 reverse('parking:location_update', args=[self.loc.pk]), reverse('parking:slot_create', args=[self.loc.pk]),
                 reverse('parking:slot_bulk_create', args=[self.loc.pk]), reverse('parking:slot_update', args=[self.slot.pk]),
                 reverse('parking:location_delete', args=[self.loc.pk]), reverse('parking:slot_delete', args=[self.slot.pk]),
                 self.loc.get_absolute_url()]
        return [(None, public), (self.user, user_pages), (self.admin, admin)]

    def test_no_inline_script_handlers_or_javascript_urls_in_any_page(self):
        offenders = []
        for who, urls in self.pages():
            c = Client()
            if who:
                c.force_login(who)
            for url in urls:
                r = c.get(url)
                self.assertEqual(r.status_code, 200, url)
                html = r.content.decode()
                if re.search(r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")[^>]*>', html):
                    offenders.append((url, 'inline <script>'))
                if re.search(r'\son[a-z]+\s*=', html):
                    offenders.append((url, 'inline event handler'))
                if 'javascript:' in html:
                    offenders.append((url, 'javascript: URL'))
        self.assertEqual(offenders, [])

    def test_scripts_load_from_this_site_only(self):
        c = Client()
        c.force_login(self.admin)
        for url in (reverse('dashboard:index'), reverse('core:home')):
            for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', c.get(url).content.decode()):
                self.assertTrue(src.startswith('/static/'), src)


# ---------------------------------------------------------------- production settings & env loader

class ProductionSettingsTests(TestCase):
    def run_settings(self, **env):
        code = ("import django, json; django.setup(); from django.conf import settings as s; "
                "print(json.dumps({k: getattr(s, k, None) for k in ['DEBUG','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE',"
                "'SECURE_SSL_REDIRECT','SECURE_HSTS_SECONDS','SECURE_PROXY_SSL_HEADER']}))")
        base = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        base.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'PYTHONPATH': str(PROJECT)})
        base.update(env)
        return subprocess.run([sys.executable, '-c', code], cwd=str(PROJECT), env=base, capture_output=True, text=True)

    def test_production_mode_refuses_to_start_with_the_dev_secret_key(self):
        r = self.run_settings(DJANGO_DEBUG='False')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)
        r = self.run_settings(DJANGO_DEBUG='False', DJANGO_SECRET_KEY='too-short')
        self.assertNotEqual(r.returncode, 0)

    def test_production_mode_turns_on_secure_defaults(self):
        import json
        r = self.run_settings(DJANGO_DEBUG='False', DJANGO_SECRET_KEY='k' * 20 + 'x' * 20 + 'y' * 20, DJANGO_BEHIND_PROXY='True')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual((s['DEBUG'], s['SESSION_COOKIE_SECURE'], s['CSRF_COOKIE_SECURE'], s['SECURE_SSL_REDIRECT']),
                         (False, True, True, True))
        self.assertGreater(s['SECURE_HSTS_SECONDS'], 0)
        self.assertEqual(s['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_comma_separated_lists_ignore_spaces(self):
        import json
        code = ("import django, json; django.setup(); from django.conf import settings as s; "
                "print(json.dumps([s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS]))")
        base = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        base.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'PYTHONPATH': str(PROJECT),
                     'DJANGO_ALLOWED_HOSTS': 'parking.test, localhost ,  ,127.0.0.1',
                     'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://a.example.com, https://b.example.com'})
        r = subprocess.run([sys.executable, '-c', code], cwd=str(PROJECT), env=base, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [['parking.test', 'localhost', '127.0.0.1'],
                                                ['https://a.example.com', 'https://b.example.com']])

    def test_development_defaults_still_work_without_any_configuration(self):
        import json
        r = self.run_settings()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)['DEBUG'])


class EnvFileTests(TestCase):
    def test_loads_values_ignores_comments_and_never_overrides_real_environment(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / '.env'
            path.write_text('# comment\nA=1\nB = "two words"\nexport C=\'3\'\nEXISTING=from-file\n\nnot a line\nEMPTY=\n')
            env = {'EXISTING': 'from-environment'}
            self.assertEqual(load_env_file(path, env), 4)
            self.assertEqual(env, {'EXISTING': 'from-environment', 'A': '1', 'B': 'two words', 'C': '3', 'EMPTY': ''})
        self.assertEqual(load_env_file('/nonexistent/.env', {}), 0)


class SecurityLoggingTests(TestCase):
    def test_failed_logins_are_logged_without_the_password(self):
        make_user()
        with self.assertLogs('apps.security', level='WARNING') as logs:
            self.client.post(reverse('accounts:login'), {'username': 'alice', 'password': 'S3cret-Typo-77'})
        text = ' '.join(logs.output)
        self.assertIn('alice', text)
        self.assertIn('127.0.0.1', text)
        self.assertNotIn('S3cret-Typo-77', text)
