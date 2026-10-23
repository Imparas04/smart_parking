import csv
import io
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, Vehicle
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments import services as pay
from apps.payments.models import Payment

from . import stats

User = get_user_model()
PW = 'Str0ng-Pass-993'


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin(name='boss'):
    u = make_user(name)
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_slot(name='Central', city='Nashik', number='A1', rate='20.00', **kw):
    loc, _ = ParkingLocation.objects.get_or_create(name=name, city=city, defaults={'address': 'x', 'hourly_rate': Decimal(rate)})
    return ParkingSlot.objects.create(location=loc, slot_number=number, **kw)


def make_booking(user, slot, start, end, status='confirmed', plate='MH15AB1234'):
    v, _ = Vehicle.objects.get_or_create(user=user, plate_number=plate)
    b = Booking.objects.create(user=user, slot=slot, vehicle=v, start_time=start, end_time=end,
                               status=status, hourly_rate=slot.location.hourly_rate)
    pay.create_for_booking(b)
    return b


# Frozen to the minute so '+2 hours' really is 2 hours (real bookings come from minute-precision forms).
BASE = timezone.now().replace(second=0, microsecond=0)


def NOW():
    return BASE


class AccessControlTests(TestCase):
    def setUp(self):
        self.slot = make_slot()
        self.b = make_booking(make_user('carl'), self.slot, NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=1))
        self.get_urls = [reverse('dashboard:index'), reverse('dashboard:bookings'), reverse('dashboard:users'),
                         reverse('dashboard:bookings_export'), reverse('dashboard:booking_detail', args=[self.b.reference]),
                         '/api/dashboard/summary/']
        self.post_urls = [reverse('dashboard:booking_status', args=[self.b.reference]),
                          reverse('dashboard:payment_status', args=[self.b.reference]),
                          reverse('dashboard:user_active', args=[self.b.user.pk]),
                          reverse('dashboard:user_role', args=[self.b.user.pk])]

    def test_anonymous_and_normal_user_blocked_admin_allowed(self):
        for u in self.get_urls[:-1]:
            self.assertEqual(self.client.get(u).status_code, 302, u)
        self.assertIn(self.client.get(self.get_urls[-1]).status_code, (401, 403))
        self.client.force_login(make_user())
        for u in self.get_urls:
            self.assertEqual(self.client.get(u).status_code, 403, u)
        for u in self.post_urls:
            self.assertEqual(self.client.post(u, {'status': 'cancelled'}).status_code, 403, u)
        self.client.force_login(make_admin())
        for u in self.get_urls:
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_action_urls_require_post(self):
        self.client.force_login(make_admin())
        for u in self.post_urls:
            self.assertEqual(self.client.get(u).status_code, 405, u)


class StatsTests(TestCase):
    def setUp(self):
        self.s1 = make_slot('Central', number='A1')
        make_slot('Central', number='A2', status='occupied')
        make_slot('Central', number='A3', status='unavailable')
        self.s4 = make_slot('Mall', 'Pune', 'B1', rate='50.00')
        self.u = make_user()
        n = NOW()
        # paid 40, paid 100 (other location), refunded 40, cancelled, pending 40, part-paid balance 20
        self.paid1 = make_booking(self.u, self.s1, n + timedelta(days=1), n + timedelta(days=1, hours=2), plate='AAAA1111')
        pay.pay(self.paid1.payment, 'card')
        self.paid2 = make_booking(self.u, self.s4, n + timedelta(days=2), n + timedelta(days=2, hours=2), plate='BBBB2222')
        pay.pay(self.paid2.payment, 'upi')
        refunded = make_booking(self.u, self.s1, n + timedelta(days=3), n + timedelta(days=3, hours=2), plate='CCCC3333')
        pay.pay(refunded.payment, 'card')
        from apps.bookings import services as bsvc
        bsvc.cancel_booking(refunded)
        cancelled = make_booking(self.u, self.s1, n + timedelta(days=4), n + timedelta(days=4, hours=2), plate='DDDD4444')
        bsvc.cancel_booking(cancelled)
        self.pending = make_booking(self.u, self.s1, n + timedelta(days=5), n + timedelta(days=5, hours=2), plate='EEEE5555')
        part = make_booking(self.u, self.s1, n + timedelta(days=6), n + timedelta(days=6, hours=2), plate='FFFF6666')
        Payment.objects.filter(pk=part.payment.pk).update(amount=Decimal('60.00'), amount_paid=Decimal('40.00'),
                                                          status='pending', paid_at=n)

    def test_cards(self):
        c = stats.overview()['cards']
        self.assertEqual((c['locations_total'], c['slots_total']), (2, 4))
        self.assertEqual((c['slots_available'], c['slots_occupied'], c['slots_unavailable']), (2, 1, 1))
        self.assertEqual(c['occupancy_pct'], 25)
        self.assertEqual(c['bookings_total'], 6)
        self.assertEqual(c['bookings_active'], 4)
        self.assertEqual(c['users_total'], 1)

    def test_revenue_counts_received_money_only(self):
        c = stats.overview()['cards']
        # 40 + 100 paid, +40 part-paid; refunded/cancelled/unpaid excluded
        self.assertEqual(c['revenue_total'], Decimal('180.00'))
        self.assertEqual(c['dues_pending'], Decimal('60.00'))  # 40 unpaid + 20 balance
        self.assertEqual(c['revenue_today'], Decimal('180.00'))

    def test_per_location_and_chart_data(self):
        o = stats.overview(7)
        by_name = {l['name']: l for l in o['locations']}
        self.assertEqual((by_name['Central']['total'], by_name['Central']['available'], by_name['Central']['occupied'],
                          by_name['Central']['unavailable']), (3, 1, 1, 1))
        self.assertEqual(by_name['Central']['revenue'], Decimal('80.00'))
        self.assertEqual(by_name['Mall']['revenue'], Decimal('100.00'))
        d = o['charts']['daily']
        self.assertEqual((len(d['labels']), len(d['bookings']), len(d['revenue'])), (7, 7, 7))
        self.assertEqual(sum(d['bookings']), 6)
        self.assertAlmostEqual(sum(d['revenue']), 180.0)
        self.assertEqual(sum(o['charts']['booking_status']['values']), 6)
        self.assertEqual(o['charts']['locations']['labels'], ['Central', 'Mall'])

    def test_old_bookings_fall_outside_the_selected_window(self):
        Booking.objects.filter(pk=self.paid1.pk).update(created_at=NOW() - timedelta(days=20))
        self.assertEqual(sum(stats.overview(7)['charts']['daily']['bookings']), 5)
        self.assertEqual(sum(stats.overview(30)['charts']['daily']['bookings']), 6)

    def test_parse_days_validates(self):
        self.assertEqual([stats.parse_days(v) for v in ('7', '30', '5', 'abc', None, '9999')], [7, 30, 14, 14, 14, 14])


class EmptyStateTests(TestCase):
    def test_dashboard_renders_with_no_data(self):
        self.client.force_login(make_admin())
        r = self.client.get(reverse('dashboard:index'))
        self.assertContains(r, 'No locations yet')
        c = r.context['s']['cards']
        self.assertEqual((c['occupancy_pct'], c['revenue_total'], c['bookings_total']), (0, Decimal('0.00'), 0))


class DashboardPageTests(TestCase):
    def setUp(self):
        make_booking(make_user(), make_slot(), NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=2))
        self.client.force_login(make_admin())

    def test_index_has_charts_and_valid_embedded_json(self):
        r = self.client.get(reverse('dashboard:index'))
        for cid in ('chartSlots', 'chartStatus', 'chartBookings', 'chartRevenue', 'chartLocations'):
            self.assertContains(r, f'id="{cid}"')
        self.assertContains(r, 'js/vendor/chart.umd.min.js')
        html = r.content.decode()
        raw = html.split('<script id="chart-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(raw)['slot_status']['values'], [1, 0, 0])

    def test_days_selector(self):
        r = self.client.get(reverse('dashboard:index'), {'days': '30'})
        self.assertEqual(len(r.context['s']['charts']['daily']['labels']), 30)
        r = self.client.get(reverse('dashboard:index'), {'days': 'x'})
        self.assertEqual(r.context['days'], 14)


class BookingListTests(TestCase):
    def setUp(self):
        n = NOW()
        self.a, self.b = make_user('anna'), make_user('ben')
        self.s1, self.s2 = make_slot('Central', number='A1'), make_slot('Mall', 'Pune', 'B1')
        self.b1 = make_booking(self.a, self.s1, n + timedelta(days=1), n + timedelta(days=1, hours=1), plate='MH15AB1234')
        self.b2 = make_booking(self.b, self.s2, n + timedelta(days=10), n + timedelta(days=10, hours=1), plate='KA01XY9999')
        pay.pay(self.b2.payment, 'card')
        self.b3 = make_booking(self.a, self.s1, n + timedelta(days=2), n + timedelta(days=2, hours=1), status='cancelled', plate='MH15AB1234')
        self.client.force_login(make_admin())
        self.url = reverse('dashboard:bookings')

    def refs(self, **params):
        r = self.client.get(self.url, params)
        self.assertEqual(r.status_code, 200)
        return {b.reference for b in r.context['page']}

    def test_filters(self):
        every = {self.b1.reference, self.b2.reference, self.b3.reference}
        self.assertEqual(self.refs(), every)
        self.assertEqual(self.refs(status='cancelled'), {self.b3.reference})
        self.assertEqual(self.refs(payment='paid'), {self.b2.reference})
        self.assertEqual(self.refs(location=self.s2.location.pk), {self.b2.reference})
        self.assertEqual(self.refs(q='ben'), {self.b2.reference})
        self.assertEqual(self.refs(q='ka01 xy9999'), {self.b2.reference})  # plate search ignores spaces/case
        self.assertEqual(self.refs(q=self.b1.reference.lower()), {self.b1.reference})
        d = timezone.localdate()
        self.assertEqual(self.refs(date_from=str(d + timedelta(days=5))), {self.b2.reference})
        self.assertEqual(self.refs(date_to=str(d + timedelta(days=1))), {self.b1.reference})
        self.assertEqual(self.refs(status='bogus', payment='zzz', location='abc', date_from='not-a-date'), every)

    def test_pagination_and_no_n_plus_one(self):
        n = NOW()
        for i in range(25):
            make_booking(self.a, self.s1, n + timedelta(days=20 + i), n + timedelta(days=20 + i, hours=1), plate=f'ZZ{i:02d}ZZ99')
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(self.url)
        self.assertEqual(len(r.context['page']), 20)
        self.assertLess(len(ctx), 15)
        self.assertEqual(len(self.client.get(self.url, {'page': 2}).context['page']), 8)

    def test_empty_state(self):
        self.assertContains(self.client.get(self.url, {'q': 'nothing-matches'}), 'No bookings found')

    def test_csv_export_respects_filters_and_neutralises_formulas(self):
        evil = make_user('+cmd')
        make_booking(evil, self.s1, NOW() + timedelta(days=30), NOW() + timedelta(days=30, hours=1), plate='EVIL1234')
        r = self.client.get(reverse('dashboard:bookings_export'))
        self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertIn('attachment', r['Content-Disposition'])
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        self.assertEqual(rows[0][0], 'reference')
        self.assertEqual(len(rows), 5)
        self.assertIn("'+cmd", [row[1] for row in rows])
        self.assertNotIn('+cmd', [row[1] for row in rows])
        r = self.client.get(reverse('dashboard:bookings_export'), {'status': 'cancelled'})
        self.assertEqual(len(list(csv.reader(io.StringIO(r.content.decode())))), 2)


class BookingStatusAdminTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        self.client.force_login(make_admin())

    def post(self, b, status):
        return self.client.post(reverse('dashboard:booking_status', args=[b.reference]), {'status': status}, follow=True)

    def test_admin_checks_in_outside_window_and_checks_out(self):
        b = make_booking(self.user, self.slot, NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=2))
        self.assertEqual(self.client.get(reverse('dashboard:booking_detail', args=[b.reference])).status_code, 200)
        self.post(b, 'checked_in')
        b.refresh_from_db(); self.slot.refresh_from_db()
        self.assertEqual((b.status, self.slot.status), ('checked_in', 'occupied'))
        self.post(b, 'completed')
        b.refresh_from_db(); self.slot.refresh_from_db()
        self.assertEqual((b.status, self.slot.status), ('completed', 'available'))

    def test_admin_cancel_ignores_cutoff_and_refunds_paid(self):
        b = make_booking(self.user, self.slot, NOW() + timedelta(minutes=10), NOW() + timedelta(hours=2))
        pay.pay(b.payment, 'card')
        self.post(b, 'cancelled')
        b.refresh_from_db()
        self.assertEqual((b.status, b.payment.status), ('cancelled', 'refunded'))

    def test_no_show_only_after_start(self):
        future = make_booking(self.user, self.slot, NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=1))
        self.assertContains(self.post(future, 'no_show'), 'before it starts')
        future.refresh_from_db()
        self.assertEqual(future.status, 'confirmed')
        started = make_booking(self.user, self.slot, NOW() - timedelta(hours=1), NOW() + timedelta(hours=1), plate='KA01XY9999')
        self.post(started, 'no_show')
        started.refresh_from_db()
        self.assertEqual((started.status, started.payment.status), ('no_show', 'cancelled'))

    def test_invalid_transitions_rejected(self):
        done = make_booking(self.user, self.slot, NOW() - timedelta(hours=3), NOW() - timedelta(hours=1), status='completed')
        for target in ('confirmed', 'cancelled', 'checked_in', 'bogus'):
            r = self.post(done, target)
            self.assertContains(r, 'Cannot change')
        done.refresh_from_db()
        self.assertEqual(done.status, 'completed')
        conf = make_booking(self.user, self.slot, NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=1), plate='KA01XY9999')
        self.assertContains(self.post(conf, 'completed'), 'Cannot change')  # can't skip check-in

    def test_detail_offers_only_valid_actions(self):
        conf = make_booking(self.user, self.slot, NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=1))
        r = self.client.get(reverse('dashboard:booking_detail', args=[conf.reference]))
        self.assertEqual({a for a, _ in r.context['actions']}, {'checked_in', 'cancelled', 'no_show'})
        done = make_booking(self.user, self.slot, NOW() - timedelta(hours=3), NOW() - timedelta(hours=1), status='completed', plate='KA01XY9999')
        r = self.client.get(reverse('dashboard:booking_detail', args=[done.reference]))
        self.assertEqual(r.context['actions'], [])
        self.assertContains(r, 'can no longer be changed')


class PaymentStatusAdminTests(TestCase):
    def setUp(self):
        self.b = make_booking(make_user(), make_slot(), NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=2))
        self.client.force_login(make_admin())
        self.url = reverse('dashboard:payment_status', args=[self.b.reference])

    def test_mark_paid_then_refund_and_final_states(self):
        self.client.post(self.url, {'status': 'paid', 'note': 'Cash at gate'})
        p = Payment.objects.get()
        self.assertEqual((p.status, p.amount_paid, p.note), ('paid', Decimal('40.00'), 'Cash at gate'))
        self.client.post(self.url, {'status': 'refunded'})
        self.assertEqual(Payment.objects.get().status, 'refunded')
        r = self.client.post(self.url, {'status': 'paid'}, follow=True)
        self.assertContains(r, 'Cannot change')
        self.assertContains(self.client.get(reverse('dashboard:booking_detail', args=[self.b.reference])), 'status is final')

    def test_invalid_status_rejected(self):
        r = self.client.post(self.url, {'status': 'bogus'}, follow=True)
        self.assertContains(r, 'Invalid status')
        self.assertEqual(Payment.objects.get().status, 'pending')


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.alice, self.bob = make_user('alice'), make_user('bob')
        self.su = User.objects.create_superuser('root', 'root@example.com', PW)
        make_booking(self.alice, make_slot(), NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=1))
        self.client.force_login(self.admin)

    def names(self, **params):
        r = self.client.get(reverse('dashboard:users'), params)
        self.assertEqual(r.status_code, 200)
        return {u.username for u in r.context['page']}

    def test_list_search_filters_and_booking_counts(self):
        self.assertEqual(self.names(), {'boss', 'alice', 'bob', 'root'})
        self.assertEqual(self.names(q='ALI'), {'alice'})
        self.assertEqual(self.names(role='admin'), {'boss', 'root'})
        self.assertEqual(self.names(role='user'), {'alice', 'bob'})
        r = self.client.get(reverse('dashboard:users'))
        self.assertEqual({u.username: u.booking_count for u in r.context['page']}['alice'], 1)
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(self.names(state='inactive'), {'bob'})
        self.assertEqual(self.names(state='bogus', role='bogus'), {'boss', 'alice', 'bob', 'root'})

    def test_deactivate_and_reactivate(self):
        self.client.post(reverse('dashboard:user_active', args=[self.bob.pk]), {'active': '0'})
        self.bob.refresh_from_db()
        self.assertFalse(self.bob.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(username='bob', password=PW))
        self.client.force_login(self.admin)
        self.client.post(reverse('dashboard:user_active', args=[self.bob.pk]), {'active': '1'})
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.is_active)

    def test_promote_and_demote(self):
        self.client.post(reverse('dashboard:user_role', args=[self.bob.pk]), {'role': 'admin'})
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.role, 'admin')
        self.client.post(reverse('dashboard:user_role', args=[self.bob.pk]), {'role': 'user'})
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.role, 'user')
        r = self.client.post(reverse('dashboard:user_role', args=[self.bob.pk]), {'role': 'superadmin'}, follow=True)
        self.assertContains(r, 'Invalid role')

    def test_cannot_change_self_or_superuser(self):
        r = self.client.post(reverse('dashboard:user_active', args=[self.admin.pk]), {'active': '0'}, follow=True)
        self.assertContains(r, 'cannot change your own')
        r = self.client.post(reverse('dashboard:user_role', args=[self.admin.pk]), {'role': 'user'}, follow=True)
        self.assertContains(r, 'cannot change your own')
        r = self.client.post(reverse('dashboard:user_active', args=[self.su.pk]), {'active': '0'}, follow=True)
        self.assertContains(r, 'Django admin')
        self.admin.refresh_from_db(); self.su.refresh_from_db()
        self.assertTrue(self.admin.is_active and self.su.is_active)
        self.assertEqual(self.admin.profile.role, 'admin')

    def test_next_redirect_only_inside_dashboard(self):
        r = self.client.post(reverse('dashboard:user_active', args=[self.bob.pk]), {'active': '0', 'next': 'https://evil.example/'})
        self.assertRedirects(r, reverse('dashboard:users'))
        r = self.client.post(reverse('dashboard:user_active', args=[self.bob.pk]), {'active': '1', 'next': '/dashboard/users/?q=bob'},
                             follow=False)
        self.assertEqual(r['Location'], '/dashboard/users/?q=bob')

    def test_deactivated_user_blocked_in_api_too(self):
        self.client.post(reverse('dashboard:user_active', args=[self.bob.pk]), {'active': '0'})
        self.client.logout()
        r = self.client.post('/api/auth/login/', {'username': 'bob', 'password': PW}, content_type='application/json')
        self.assertEqual(r.status_code, 400)


class APITests(TestCase):
    def setUp(self):
        self.b = make_booking(make_user(), make_slot(), NOW() + timedelta(days=1), NOW() + timedelta(days=1, hours=2))
        pay.pay(self.b.payment, 'card')

    def test_summary_shape_and_money_as_strings(self):
        self.client.force_login(make_admin())
        d = self.client.get('/api/dashboard/summary/', {'days': '7'}).json()
        self.assertEqual(d['days'], 7)
        self.assertEqual(d['cards']['revenue_total'], '40.00')
        self.assertEqual(d['locations'][0]['revenue'], '40.00')
        self.assertEqual(len(d['charts']['daily']['labels']), 7)
        self.assertIsInstance(d['charts']['daily']['revenue'][0], float)
        self.assertEqual(self.client.get('/api/dashboard/summary/', {'days': '3'}).json()['days'], 14)

    def test_summary_forbidden_for_users(self):
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.client.get('/api/dashboard/summary/').status_code, 403)

    def test_booking_status_api_admin_only(self):
        b = make_booking(make_user('zed'), make_slot(number='Z9'), NOW() + timedelta(days=2), NOW() + timedelta(days=2, hours=1), plate='ZZZZ9999')
        url = f'/api/bookings/{b.reference}/status/'
        patch = lambda body: self.client.patch(url, body, content_type='application/json')
        self.client.force_login(make_user('bob'))
        self.assertEqual(patch({'status': 'cancelled'}).status_code, 403)  # permission is checked before lookup
        self.client.force_login(b.user)
        self.assertEqual(patch({'status': 'cancelled'}).status_code, 403)  # owner is not admin
        self.client.force_login(make_admin())
        self.assertEqual(patch({'status': 'bogus'}).status_code, 400)
        self.assertEqual(patch({'status': 'completed'}).status_code, 400)
        r = patch({'status': 'cancelled'})
        self.assertEqual((r.status_code, r.json()['status'], r.json()['payment']['status']), (200, 'cancelled', 'cancelled'))
        self.assertEqual(patch({'status': 'checked_in'}).status_code, 400)
