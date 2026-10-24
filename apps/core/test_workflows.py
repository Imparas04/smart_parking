"""End-to-end journeys: each test walks a complete real workflow through the actual pages and APIs."""
import csv
import io
import json
import threading
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.bookings import services as bsvc
from apps.bookings.models import Booking
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments.models import Payment

User = get_user_model()
PW = 'Str0ng-Pass-993'
FMT = '%Y-%m-%dT%H:%M'


def minutes_from_now(n):
    return (timezone.now() + timedelta(minutes=n)).replace(second=0, microsecond=0)


def local(dt):
    return timezone.localtime(dt).strftime(FMT)  # what a browser's datetime-local field sends (site time zone)


def make_admin(name='boss'):
    u = User.objects.create_user(name, f'{name}@example.com', PW)
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_garage(name='City Garage', rate='30.00'):
    loc = ParkingLocation.objects.create(name=name, address='MG Road', city='Nashik', hourly_rate=Decimal(rate))
    slots = [ParkingSlot.objects.create(location=loc, slot_number=f'A{i}') for i in (1, 2, 3)]
    ParkingSlot.objects.create(location=loc, slot_number='B1', slot_type='bike')
    return loc, slots


class UserJourneyTests(TestCase):
    """Visitor -> registered user: browse, book, pay, check in/out, cancel, manage account."""

    def test_complete_user_journey(self):
        loc, (slot, *_ ) = make_garage()
        c = self.client

        # 1. an anonymous visitor can browse and search but is asked to log in to book
        self.assertContains(c.get(reverse('core:home')), 'Find and book parking')
        self.assertContains(c.get(reverse('parking:location_list'), {'q': 'garage'}), 'City Garage')
        self.assertContains(c.get(loc.get_absolute_url()), 'A1')
        self.assertContains(c.get(slot.get_absolute_url()), 'Login to book')
        self.assertEqual(c.get(reverse('bookings:history')).status_code, 302)

        # 2. register (logs in automatically)
        r = c.post(reverse('accounts:register'), {
            'username': 'asha', 'first_name': 'Asha', 'last_name': 'K', 'email': 'asha@example.com', 'phone': '9876543210',
            'password1': PW, 'password2': PW})
        self.assertRedirects(r, reverse('core:home'))
        self.assertContains(c.get(reverse('core:home')), 'Logout')

        # 3. check the fee first (public estimate API, computed on the server)
        start, end = minutes_from_now(5), minutes_from_now(5) + timedelta(hours=2)
        est = c.get('/api/payments/estimate/', {'slot': slot.pk, 'start_time': local(start), 'end_time': local(end)}).json()
        self.assertEqual((est['amount'], est['billing_blocks']), ('60.00', 2))

        # 4. book the slot; the confirmation shows the same amount and offers payment
        r = c.post(reverse('bookings:book', args=[slot.pk]), {
            'start_time': local(start), 'end_time': local(end), 'plate_number': 'mh 15 ab 1234', 'vehicle_type': 'car'})
        booking = Booking.objects.get()
        self.assertRedirects(r, booking.get_absolute_url())
        page = c.get(booking.get_absolute_url())
        self.assertContains(page, booking.reference)
        self.assertContains(page, '60.00')
        self.assertContains(page, 'Pay now (simulated)')
        self.assertEqual(booking.vehicle.plate_number, 'MH15AB1234')

        # 5. it appears in the booking history
        self.assertContains(c.get(reverse('bookings:history')), booking.reference)

        # 6. a failed simulated payment can be retried
        pay_url = reverse('payments:pay', args=[booking.reference])
        self.assertContains(c.get(pay_url), 'SIMULATED PAYMENT')
        c.post(pay_url, {'method': 'card', 'outcome': 'fail'})
        self.assertEqual(Payment.objects.get().status, 'failed')
        c.post(pay_url, {'method': 'upi', 'outcome': 'success'})
        payment = Payment.objects.get()
        self.assertEqual((payment.status, payment.amount_paid), ('paid', Decimal('60.00')))
        self.assertNotContains(c.get(booking.get_absolute_url()), 'Pay now')

        # 7. check in: the slot becomes occupied for everyone
        c.post(reverse('bookings:check_in', args=[booking.reference]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'checked_in')
        self.assertContains(Client().get(loc.get_absolute_url()), 'slot-occupied')

        # 8. check out: booking completes, slot is free again, nothing more to pay
        c.post(reverse('bookings:check_out', args=[booking.reference]))
        booking.refresh_from_db()
        slot.refresh_from_db()
        self.assertEqual((booking.status, slot.status), ('completed', 'available'))
        self.assertEqual(Payment.objects.get().amount_due, 0)

        # 9. a completed booking cannot be cancelled
        r = c.post(reverse('bookings:cancel', args=[booking.reference]), follow=True)
        self.assertContains(r, 'Only confirmed bookings can be cancelled')

        # 10. book for tomorrow, pay, then cancel: refund is recorded and history can be filtered
        tomorrow = minutes_from_now(24 * 60)
        c.post(reverse('bookings:book', args=[slot.pk]), {
            'start_time': local(tomorrow), 'end_time': local(tomorrow + timedelta(hours=1)), 'vehicle': booking.vehicle.pk})
        second = Booking.objects.exclude(pk=booking.pk).get()
        c.post(reverse('payments:pay', args=[second.reference]), {'method': 'wallet', 'outcome': 'success'})
        c.post(reverse('bookings:cancel', args=[second.reference]))
        second.refresh_from_db()
        self.assertEqual((second.status, second.payment.status), ('cancelled', 'refunded'))
        cancelled = c.get(reverse('bookings:history'), {'status': 'cancelled'})
        self.assertContains(cancelled, second.reference)
        self.assertNotContains(cancelled, booking.reference)

        # 11. account management: profile, password, logout, login with the new password
        c.post(reverse('accounts:profile'), {'first_name': 'Asha', 'last_name': 'Kulkarni', 'email': 'asha@example.com', 'phone': '9876500000'})
        self.assertEqual(User.objects.get(username='asha').profile.phone, '9876500000')
        c.post(reverse('accounts:password_change'), {'old_password': PW, 'new_password1': 'An0ther-Pass-771', 'new_password2': 'An0ther-Pass-771'})
        c.post(reverse('accounts:logout'))
        self.assertEqual(c.get(reverse('bookings:history')).status_code, 302)
        self.assertFalse(c.login(username='asha', password=PW))
        self.assertTrue(c.login(username='asha', password='An0ther-Pass-771'))


class AdminJourneyTests(TestCase):
    """Administrator: set up a location, watch bookings arrive, handle them, report, manage users."""

    def test_complete_admin_journey(self):
        admin = make_admin()
        admin_c = Client()
        admin_c.force_login(admin)

        # 1. create a location and add slots in bulk
        admin_c.post(reverse('parking:location_create'), {
            'name': 'Hill Lot', 'address': 'Gangapur Rd', 'city': 'Nashik', 'description': '', 'opening_time': '00:00',
            'closing_time': '23:59', 'hourly_rate': '40.00', 'is_active': 'on'})
        loc = ParkingLocation.objects.get(name='Hill Lot')
        admin_c.post(reverse('parking:slot_bulk_create', args=[loc.pk]), {'prefix': 'G-', 'start': 1, 'count': 5, 'slot_type': 'car'})
        self.assertEqual(loc.slots.count(), 5)
        self.assertContains(Client().get(reverse('parking:location_list')), 'Hill Lot')

        # 2. a customer books a slot there
        customer = User.objects.create_user('ben', 'ben@example.com', PW)
        user_c = Client()
        user_c.force_login(customer)
        slot = loc.slots.get(slot_number='G-1')
        tomorrow = minutes_from_now(24 * 60)
        user_c.post(reverse('bookings:book', args=[slot.pk]), {
            'start_time': local(tomorrow), 'end_time': local(tomorrow + timedelta(hours=3)), 'plate_number': 'GJ01AA0001', 'vehicle_type': 'car'})
        booking = Booking.objects.get()

        # 3. the admin sees it on the dashboard, in the filtered list and on the detail page
        cards = admin_c.get(reverse('dashboard:index')).context['s']
        self.assertEqual((cards['cards']['bookings_total'], cards['cards']['slots_total']), (1, 5))
        listing = admin_c.get(reverse('dashboard:bookings'), {'location': loc.pk, 'status': 'confirmed'})
        self.assertContains(listing, booking.reference)
        self.assertContains(admin_c.get(reverse('dashboard:booking_detail', args=[booking.reference])), 'GJ01AA0001')

        # 4. the customer arrives early; the attendant (admin) checks them in and out
        admin_c.post(reverse('dashboard:booking_status', args=[booking.reference]), {'status': 'checked_in'})
        slot.refresh_from_db()
        self.assertEqual(slot.status, 'occupied')
        admin_c.post(reverse('dashboard:booking_status', args=[booking.reference]), {'status': 'completed'})
        booking.refresh_from_db()
        slot.refresh_from_db()
        self.assertEqual((booking.status, slot.status, booking.payment.status), ('completed', 'available', 'pending'))

        # 5. cash is taken at the gate: the admin marks the payment paid
        admin_c.post(reverse('dashboard:payment_status', args=[booking.reference]), {'status': 'paid', 'note': 'Cash at gate'})
        booking.refresh_from_db()
        self.assertEqual((booking.payment.status, booking.payment.amount_paid), ('paid', Decimal('120.00')))

        # 6. reports: revenue on the dashboard and in the CSV export
        c = admin_c.get(reverse('dashboard:index')).context['s']['cards']
        self.assertEqual((c['revenue_total'], c['dues_pending']), (Decimal('120.00'), Decimal('0.00')))
        rows = list(csv.DictReader(io.StringIO(admin_c.get(reverse('dashboard:bookings_export')).content.decode())))
        self.assertEqual([(r['reference'], r['status'], r['payment_status']) for r in rows], [(booking.reference, 'completed', 'paid')])

        # 7. a location with bookings cannot be deleted; it is deactivated instead and disappears for the public
        r = admin_c.post(reverse('parking:location_delete', args=[loc.pk]), follow=True)
        self.assertContains(r, 'has bookings')
        self.assertTrue(ParkingLocation.objects.filter(pk=loc.pk).exists())
        form = {'name': 'Hill Lot', 'address': 'Gangapur Rd', 'city': 'Nashik', 'description': '', 'opening_time': '00:00',
                'closing_time': '23:59', 'hourly_rate': '40.00'}  # is_active omitted = unchecked
        admin_c.post(reverse('parking:location_update', args=[loc.pk]), form)
        self.assertNotContains(Client().get(reverse('parking:location_list')), 'Hill Lot')
        self.assertEqual(Client().get(loc.get_absolute_url()).status_code, 404)
        self.assertEqual(admin_c.get(loc.get_absolute_url()).status_code, 200)  # admins still see it

        # 8. user management: deactivate (their session dies), reactivate, promote, demote
        self.assertEqual(user_c.get(reverse('accounts:profile')).status_code, 200)
        admin_c.post(reverse('dashboard:user_active', args=[customer.pk]), {'active': '0'})
        self.assertEqual(user_c.get(reverse('accounts:profile')).status_code, 302)
        admin_c.post(reverse('dashboard:user_active', args=[customer.pk]), {'active': '1'})
        self.assertEqual(user_c.get(reverse('accounts:profile')).status_code, 200)
        self.assertEqual(user_c.get(reverse('dashboard:index')).status_code, 403)
        admin_c.post(reverse('dashboard:user_role', args=[customer.pk]), {'role': 'admin'})
        self.assertEqual(user_c.get(reverse('dashboard:index')).status_code, 200)
        admin_c.post(reverse('dashboard:user_role', args=[customer.pk]), {'role': 'user'})
        self.assertEqual(user_c.get(reverse('dashboard:index')).status_code, 403)


class ApiJourneyTests(TestCase):
    """The same business flow driven only through the REST API with token authentication."""

    def api(self, method, url, body=None, token=None):
        extra = {'HTTP_AUTHORIZATION': f'Token {token}'} if token else {}
        data = json.dumps(body) if body is not None else None
        return getattr(self.c, method)(url, data, content_type='application/json', **extra)

    def test_complete_api_journey(self):
        loc, (slot, *_ ) = make_garage()
        admin = make_admin()
        admin_token = Token.objects.create(user=admin).key
        self.c = Client(enforce_csrf_checks=True)  # token calls must work without CSRF cookies

        # register, then log in again
        r = self.api('post', '/api/auth/register/', {'username': 'dev', 'password': PW, 'first_name': 'Dev', 'email': 'dev@example.com'})
        self.assertEqual(r.status_code, 201)
        token = self.api('post', '/api/auth/login/', {'username': 'dev', 'password': PW}).json()['token']
        self.assertEqual(self.api('get', '/api/auth/profile/', token=token).json()['role'], 'user')

        # browse publicly
        found = self.api('get', '/api/parking/locations/?available=1&city=nashik').json()
        self.assertEqual((found['count'], found['results'][0]['available_slots']), (1, 4))  # 3 car slots + 1 bike slot
        free = self.api('get', f'/api/parking/slots/?location={loc.pk}&status=available&slot_type=car').json()
        self.assertEqual(free['count'], 3)

        # book, pay (fail then succeed), check in, check out
        start = minutes_from_now(5)
        body = {'slot': slot.pk, 'start_time': start.isoformat(), 'end_time': (start + timedelta(hours=2)).isoformat(),
                'plate_number': 'MH15AB1234', 'vehicle_type': 'car'}
        r = self.api('post', '/api/bookings/', body, token)
        self.assertEqual(r.status_code, 201, r.content)
        ref, pid = r.json()['reference'], r.json()['payment']['id']
        self.assertEqual(self.api('post', '/api/bookings/', body, token).status_code, 400)  # double booking refused
        self.assertEqual(self.api('post', f'/api/payments/{pid}/pay/', {'method': 'card', 'outcome': 'fail'}, token).json()['status'], 'failed')
        self.assertEqual(self.api('post', f'/api/payments/{pid}/pay/', {'method': 'card'}, token).json()['status'], 'paid')
        self.assertEqual(self.api('post', f'/api/bookings/{ref}/check-in/', token=token).json()['status'], 'checked_in')
        done = self.api('post', f'/api/bookings/{ref}/check-out/', token=token).json()
        self.assertEqual((done['status'], done['payment']['amount'], done['payment']['amount_due']), ('completed', '60.00', '0.00'))
        self.assertEqual(self.api('get', '/api/bookings/?status=completed', token=token).json()['count'], 1)

        # a second booking is cancelled -> refund
        later = minutes_from_now(2 * 24 * 60)
        r = self.api('post', '/api/bookings/', {**body, 'start_time': later.isoformat(), 'end_time': (later + timedelta(hours=1)).isoformat()}, token)
        ref2, pid2 = r.json()['reference'], r.json()['payment']['id']
        self.api('post', f'/api/payments/{pid2}/pay/', {'method': 'upi'}, token)
        self.assertEqual(self.api('post', f'/api/bookings/{ref2}/cancel/', token=token).json()['payment']['status'], 'refunded')

        # the admin's view: summary numbers, all bookings, status management; a normal user is refused
        summary = self.api('get', '/api/dashboard/summary/', token=admin_token).json()
        self.assertEqual((summary['cards']['bookings_total'], summary['cards']['revenue_total']), (2, '60.00'))
        self.assertEqual(self.api('get', '/api/bookings/', token=admin_token).json()['count'], 2)
        self.assertEqual(self.api('get', '/api/dashboard/summary/', token=token).status_code, 403)
        self.assertEqual(self.api('patch', f'/api/payments/{pid2}/status/', {'status': 'paid'}, admin_token).status_code, 400)  # refunded is final

        # logging out revokes the token
        self.assertEqual(self.api('post', '/api/auth/logout/', token=token).status_code, 204)
        self.assertEqual(self.api('get', '/api/auth/profile/', token=token).status_code, 401)


class ConcurrentBookingTests(TransactionTestCase):
    """Many people press 'book' for the same slot and time at the same moment: exactly one may win.
    (test_concurrency_file_db.py repeats this on a real SQLite file, which is how the app is actually deployed.)"""

    def test_only_one_of_many_simultaneous_bookings_succeeds(self):
        loc, (slot, *_ ) = make_garage()
        n = 8
        users = [User.objects.create_user(f'racer{i}', f'r{i}@example.com', PW) for i in range(n)]
        start = minutes_from_now(60)
        end = start + timedelta(hours=2)
        barrier, outcomes = threading.Barrier(n), []

        def attempt(user, plate):
            try:
                barrier.wait(timeout=10)
                for _ in range(40):  # the in-memory test database can report a transient 'table is locked'; retry like a client would
                    try:
                        bsvc.create_booking(user, slot.pk, start, end, plate_number=plate, vehicle_type='car')
                        outcomes.append('booked')
                    except ValidationError:
                        outcomes.append('refused')
                    except OperationalError:
                        time.sleep(0.05)
                        continue
                    break
                else:
                    outcomes.append('error:OperationalError')
            except Exception as exc:
                outcomes.append(f'error:{type(exc).__name__}')
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(u, f'RACE{i}00{i}')) for i, u in enumerate(users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(outcomes), n, outcomes)
        self.assertEqual(Booking.objects.filter(slot=slot).count(), 1, outcomes)  # the invariant: never a double booking
        self.assertEqual(outcomes.count('booked'), 1, outcomes)
        self.assertEqual(Payment.objects.count(), 1)  # and no orphaned payment rows from the losers
