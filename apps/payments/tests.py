from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.bookings import services as bsvc
from apps.bookings.models import Booking, Vehicle
from apps.parking.models import ParkingLocation, ParkingSlot

from . import services
from .models import Payment
from .pricing import billable_blocks, calculate_charge

User = get_user_model()
PW = 'Str0ng-Pass-993'


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin():
    u = make_user('boss')
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_slot(rate='20.00'):
    loc = ParkingLocation.objects.create(name='Central', address='MG Road', city='Nashik', hourly_rate=Decimal(rate))
    return ParkingSlot.objects.create(location=loc, slot_number='A1')


def make_booking(user, slot, start, end, status='confirmed', plate='MH15AB1234'):
    v, _ = Vehicle.objects.get_or_create(user=user, plate_number=plate)
    b = Booking.objects.create(user=user, slot=slot, vehicle=v, start_time=start, end_time=end,
                               status=status, hourly_rate=slot.location.hourly_rate)
    services.create_for_booking(b)
    return b


class PricingTests(TestCase):
    def setUp(self):
        self.t = timezone.now()

    def test_rounds_up_with_one_hour_minimum(self):
        r = Decimal('25.50')
        for minutes, blocks in [(1, 1), (30, 1), (60, 1), (61, 2), (120, 2), (121, 3)]:
            self.assertEqual(billable_blocks(self.t, self.t + timedelta(minutes=minutes)), blocks)
        self.assertEqual(calculate_charge(r, self.t, self.t + timedelta(minutes=61)), Decimal('51.00'))
        self.assertEqual(calculate_charge(r, self.t, self.t + timedelta(minutes=30)), Decimal('25.50'))

    @override_settings(BILLING_BLOCK_MINUTES=30)
    def test_block_size_is_configurable(self):
        self.assertEqual(calculate_charge(Decimal('20'), self.t, self.t + timedelta(minutes=31)), Decimal('20.00'))
        self.assertEqual(calculate_charge(Decimal('20'), self.t, self.t + timedelta(minutes=30)), Decimal('10.00'))


class BookingCreatesPaymentTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot('30.00')
        self.client.force_login(self.user)

    def book(self, hours=2):
        start = timezone.now() + timedelta(days=1)
        return bsvc.create_booking(self.user, self.slot.pk, start, start + timedelta(hours=hours),
                                   plate_number='MH15AB1234', vehicle_type='car')

    def test_payment_created_with_server_side_amount_and_rate_snapshot(self):
        b = self.book(2)
        self.assertEqual(b.hourly_rate, Decimal('30.00'))
        self.assertEqual((b.payment.amount, b.payment.status, b.payment.amount_paid),
                         (Decimal('60.00'), 'pending', Decimal('0.00')))
        self.slot.location.hourly_rate = Decimal('99.00')
        self.slot.location.save()
        b.refresh_from_db()
        self.assertEqual(b.hourly_rate, Decimal('30.00'))

    def test_free_location_is_paid_immediately(self):
        self.slot.location.hourly_rate = Decimal('0')
        self.slot.location.save()
        self.assertEqual(self.book().payment.status, 'paid')

    def test_confirmation_page_shows_estimate_and_pay_button(self):
        b = self.book(1)
        r = self.client.get(b.get_absolute_url())
        self.assertContains(r, '30.00')
        self.assertContains(r, 'Pay now (simulated)')


class PayTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        now = timezone.now()
        self.b = make_booking(self.user, self.slot, now + timedelta(days=1), now + timedelta(days=1, hours=2))
        self.url = reverse('payments:pay', args=[self.b.reference])
        self.client.force_login(self.user)

    def test_pay_page_is_clearly_labelled_simulated(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'SIMULATED PAYMENT')
        self.assertContains(r, 'No real money')

    def test_successful_simulated_payment(self):
        r = self.client.post(self.url, {'method': 'upi', 'outcome': 'success'})
        self.assertRedirects(r, self.b.get_absolute_url())
        p = Payment.objects.get()
        self.assertEqual((p.status, p.method, p.amount_paid), ('paid', 'upi', Decimal('40.00')))
        self.assertTrue(p.transaction_id.startswith('SIM-'))
        self.assertIsNotNone(p.paid_at)
        self.assertTrue(p.is_simulated)

    def test_failed_payment_can_be_retried(self):
        self.client.post(self.url, {'method': 'card', 'outcome': 'fail'})
        p = Payment.objects.get()
        self.assertEqual((p.status, p.amount_paid), ('failed', Decimal('0.00')))
        self.assertContains(self.client.get(self.url), 'failed')
        self.client.post(self.url, {'method': 'card', 'outcome': 'success'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'paid')

    def test_cannot_pay_twice(self):
        self.client.post(self.url, {'method': 'card', 'outcome': 'success'})
        txn = Payment.objects.get().transaction_id
        self.client.post(self.url, {'method': 'card', 'outcome': 'success'})
        self.assertEqual(Payment.objects.get().transaction_id, txn)
        with self.assertRaises(Exception):
            services.pay(Payment.objects.get(), 'card')

    def test_invalid_method_rejected(self):
        self.client.post(self.url, {'method': 'bitcoin', 'outcome': 'success'})
        self.assertEqual(Payment.objects.get().status, 'pending')

    def test_other_user_cannot_pay_and_anonymous_redirected(self):
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.client.post(self.url, {'method': 'card', 'outcome': 'success'}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(Payment.objects.get().status, 'pending')

    @override_settings(PAYMENTS_SIMULATED=False)
    def test_refuses_when_no_gateway_configured(self):
        self.client.post(self.url, {'method': 'card', 'outcome': 'success'})
        self.assertEqual(Payment.objects.get().status, 'pending')


class CancelRefundTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        now = timezone.now()
        self.b = make_booking(self.user, self.slot, now + timedelta(days=1), now + timedelta(days=1, hours=2))

    def test_cancel_unpaid_cancels_payment(self):
        bsvc.cancel_booking(self.b)
        self.assertEqual(Payment.objects.get().status, 'cancelled')
        self.assertEqual(Payment.objects.get().amount_due, 0)

    def test_cancel_paid_marks_refund(self):
        services.pay(self.b.payment, 'card')
        bsvc.cancel_booking(self.b)
        p = Payment.objects.get()
        self.assertEqual(p.status, 'refunded')
        self.assertIsNotNone(p.refunded_at)

    def test_cannot_pay_cancelled_booking(self):
        bsvc.cancel_booking(self.b)
        self.client.force_login(self.user)
        self.client.post(reverse('payments:pay', args=[self.b.reference]), {'method': 'card', 'outcome': 'success'})
        self.assertEqual(Payment.objects.get().status, 'cancelled')


class CheckInOutTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot('20.00')
        self.client.force_login(self.user)
        self.now = timezone.now()

    def booking(self, start_offset, end_offset, **kw):
        return make_booking(self.user, self.slot, self.now + start_offset, self.now + end_offset, **kw)

    def test_check_in_window(self):
        early = self.booking(timedelta(hours=2), timedelta(hours=3))
        self.assertIn('opens 15 minutes', early.check_in_block_reason())
        r = self.client.post(reverse('bookings:check_in', args=[early.reference]), follow=True)
        early.refresh_from_db()
        self.assertEqual(early.status, 'confirmed')
        self.assertContains(r, 'Check-in opens')
        ended = self.booking(-timedelta(hours=3), -timedelta(hours=1))
        self.assertIn('already ended', ended.check_in_block_reason())

    def test_check_in_marks_slot_occupied_then_check_out_frees_it(self):
        b = self.booking(timedelta(minutes=10), timedelta(hours=2))
        self.client.post(reverse('bookings:check_in', args=[b.reference]))
        b.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual((b.status, self.slot.status), ('checked_in', 'occupied'))
        self.assertIsNotNone(b.checked_in_at)
        self.client.post(reverse('bookings:check_out', args=[b.reference]))
        b.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual((b.status, self.slot.status), ('completed', 'available'))
        self.assertIsNotNone(b.checked_out_at)
        self.assertEqual(b.payment.amount, Decimal('40.00'))  # booked 2h, left early: no reduction

    def test_cannot_check_out_unless_checked_in_or_twice(self):
        b = self.booking(timedelta(minutes=10), timedelta(hours=2))
        self.client.post(reverse('bookings:check_out', args=[b.reference]))
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        bsvc.check_in(b)
        bsvc.check_out(b)
        with self.assertRaises(Exception):
            bsvc.check_out(b)

    def test_overstay_is_charged_and_paid_booking_gets_balance_due(self):
        b = self.booking(-timedelta(minutes=150), -timedelta(minutes=30), status='checked_in')  # booked 2h, now 2.5h in
        b.payment.amount_paid = b.payment.amount  # paid for the booked 2h
        b.payment.status = 'paid'
        b.payment.save()
        self.slot.status = 'occupied'
        self.slot.save()
        bsvc.check_out(b)
        p = Payment.objects.get()
        self.assertEqual(p.amount, Decimal('60.00'))  # 2.5h from booked start until now, rounded up to 3h
        self.assertEqual((p.status, p.amount_due), ('pending', Decimal('20.00')))
        self.client.force_login(self.user)
        self.client.post(reverse('payments:pay', args=[b.reference]), {'method': 'card', 'outcome': 'success'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.amount_paid), ('paid', Decimal('60.00')))

    def test_checkout_allowed_with_payment_still_pending(self):
        b = self.booking(timedelta(minutes=5), timedelta(hours=1))
        bsvc.check_in(b)
        bsvc.check_out(b)
        self.assertEqual(Payment.objects.get().status, 'pending')

    def test_previous_vehicle_blocks_check_in(self):
        stuck = self.booking(-timedelta(hours=3), -timedelta(hours=1), status='checked_in')
        nxt = make_booking(make_user('bob'), self.slot, self.now + timedelta(minutes=5), self.now + timedelta(hours=1),
                           plate='GJ01AA0001')
        with self.assertRaises(Exception) as ctx:
            bsvc.check_in(nxt)
        self.assertIn('previous vehicle', str(ctx.exception))
        bsvc.check_out(stuck)
        bsvc.check_in(nxt)

    def test_unavailable_slot_blocks_check_in(self):
        b = self.booking(timedelta(minutes=5), timedelta(hours=1))
        self.slot.status = 'unavailable'
        self.slot.save()
        with self.assertRaises(Exception):
            bsvc.check_in(b)

    def test_other_user_cannot_check_in_via_web(self):
        b = self.booking(timedelta(minutes=5), timedelta(hours=1))
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.client.post(reverse('bookings:check_in', args=[b.reference])).status_code, 404)
        self.assertEqual(self.client.get(reverse('bookings:check_in', args=[b.reference])).status_code, 405)


class NoShowTests(TestCase):
    def test_command_marks_only_ended_unused_bookings(self):
        user, slot, now = make_user(), make_slot(), timezone.now()
        old = make_booking(user, slot, now - timedelta(hours=3), now - timedelta(hours=1))
        future = make_booking(user, slot, now + timedelta(days=1), now + timedelta(days=1, hours=1), plate='KA01XY9999')
        used = make_booking(user, slot, now - timedelta(hours=3), now - timedelta(hours=1), status='checked_in', plate='TN01ZZ0001')
        out = StringIO()
        call_command('expire_bookings', stdout=out)
        self.assertIn('1 booking', out.getvalue())
        for b in (old, future, used):
            b.refresh_from_db()
        self.assertEqual((old.status, future.status, used.status), ('no_show', 'confirmed', 'checked_in'))
        self.assertEqual(old.payment.status, 'cancelled')
        call_command('expire_bookings', stdout=StringIO())  # idempotent


class APITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot('20.00')
        self.now = timezone.now()
        self.b = make_booking(self.user, self.slot, self.now + timedelta(minutes=5), self.now + timedelta(hours=2))
        self.client.force_login(self.user)

    def post(self, url, body=None):
        return self.client.post(url, body or {}, content_type='application/json')

    def test_estimate_is_public_and_server_side(self):
        self.client.logout()
        s, e = '2030-01-01T10:00', '2030-01-01T12:30'
        r = self.client.get('/api/payments/estimate/', {'slot': self.slot.pk, 'start_time': s, 'end_time': e})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['amount'], r.json()['billing_blocks']), ('60.00', 3))
        bad = self.client.get('/api/payments/estimate/', {'slot': self.slot.pk, 'start_time': e, 'end_time': s})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.get('/api/payments/estimate/', {'slot': 9999, 'start_time': s, 'end_time': e}).status_code, 400)

    def test_list_detail_filters_and_isolation(self):
        pid = self.b.payment.pk
        self.assertEqual(self.client.get('/api/payments/').json()['count'], 1)
        self.assertEqual(self.client.get('/api/payments/', {'status': 'paid'}).json()['count'], 0)
        self.assertEqual(self.client.get('/api/payments/', {'booking': self.b.reference}).json()['count'], 1)
        self.assertEqual(self.client.get(f'/api/payments/{pid}/').json()['booking'], self.b.reference)
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.client.get('/api/payments/').json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/payments/{pid}/').status_code, 404)

    def test_pay_endpoint_success_failure_and_ownership(self):
        pid = self.b.payment.pk
        r = self.post(f'/api/payments/{pid}/pay/', {'method': 'card', 'outcome': 'fail'})
        self.assertEqual((r.status_code, r.json()['status']), (200, 'failed'))
        r = self.post(f'/api/payments/{pid}/pay/', {'method': 'card'})
        self.assertEqual((r.status_code, r.json()['status'], r.json()['is_simulated']), (200, 'paid', True))
        self.assertEqual(self.post(f'/api/payments/{pid}/pay/', {'method': 'card'}).status_code, 400)
        self.assertEqual(self.post(f'/api/payments/{pid}/pay/', {'method': 'zzz'}).status_code, 400)

    def test_admin_can_read_all_but_not_pay_for_others(self):
        self.client.force_login(make_admin())
        self.assertEqual(self.client.get('/api/payments/').json()['count'], 1)
        self.assertEqual(self.post(f'/api/payments/{self.b.payment.pk}/pay/', {'method': 'card'}).status_code, 403)

    def test_admin_status_management_and_transitions(self):
        pid = self.b.payment.pk
        url = f'/api/payments/{pid}/status/'
        self.assertEqual(self.client.patch(url, {'status': 'paid'}, content_type='application/json').status_code, 403)
        self.client.force_login(make_admin())
        patch = lambda body: self.client.patch(url, body, content_type='application/json')
        self.assertEqual(patch({'status': 'refunded'}).status_code, 400)  # pending -> refunded not allowed
        self.assertEqual(patch({'status': 'bogus'}).status_code, 400)
        r = patch({'status': 'paid', 'note': 'Cash at gate'})
        self.assertEqual((r.status_code, r.json()['status'], r.json()['amount_due']), (200, 'paid', '0.00'))
        self.assertTrue(r.json()['transaction_id'].startswith('MAN-'))
        self.assertEqual(patch({'status': 'refunded'}).json()['status'], 'refunded')
        self.assertEqual(patch({'status': 'paid'}).status_code, 400)  # refunded is final

    def test_api_check_in_out_by_owner_and_admin(self):
        url = f'/api/bookings/{self.b.reference}'
        r = self.post(url + '/check-in/')
        self.assertEqual((r.status_code, r.json()['status']), (200, 'checked_in'))
        self.assertEqual(self.post(url + '/check-in/').status_code, 400)
        self.client.force_login(make_admin())  # attendant checks the vehicle out
        r = self.post(url + '/check-out/')
        self.assertEqual((r.status_code, r.json()['status']), (200, 'completed'))
        self.assertEqual(r.json()['payment']['amount'], '40.00')
        self.assertEqual(self.post(url + '/check-out/').status_code, 400)

    def test_api_check_in_blocked_for_other_users(self):
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.post(f'/api/bookings/{self.b.reference}/check-in/').status_code, 404)

    def test_booking_api_includes_payment_and_flags(self):
        d = self.client.get(f'/api/bookings/{self.b.reference}/').json()
        self.assertEqual(d['payment']['status'], 'pending')
        self.assertEqual((d['can_check_in'], d['can_check_out'], d['hourly_rate']), (True, False, '20.00'))


class PagesTests(TestCase):
    def test_history_shows_amount_and_payment_status(self):
        user, slot, now = make_user(), make_slot(), timezone.now()
        make_booking(user, slot, now + timedelta(days=1), now + timedelta(days=1, hours=1))
        self.client.force_login(user)
        r = self.client.get(reverse('bookings:history'))
        self.assertContains(r, 'Pending')
        self.assertContains(r, '20.00')

    def test_booking_form_includes_fee_estimate_hook(self):
        self.client.force_login(make_user())
        r = self.client.get(reverse('bookings:book', args=[make_slot().pk]))
        self.assertContains(r, 'id="estimate"')
        self.assertContains(r, '/api/payments/estimate/')
