from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parking.models import ParkingLocation, ParkingSlot

from .models import Booking, Vehicle

User = get_user_model()
PW = 'Str0ng-Pass-993'
FMT = '%Y-%m-%dT%H:%M'


def at(days, hour, minute=0):
    d = timezone.localdate() + timedelta(days=days)
    return timezone.make_aware(datetime.combine(d, time(hour, minute)))


def make_user(name='alice'):
    return User.objects.create_user(name, f'{name}@example.com', PW)


def make_admin():
    u = make_user('boss')
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_slot(location=None, number='A1', **kw):
    location = location or ParkingLocation.objects.create(name='Central', address='MG Road', city='Nashik')
    return ParkingSlot.objects.create(location=location, slot_number=number, **kw)


def book_data(start, end, **kw):
    data = {'start_time': start.strftime(FMT), 'end_time': end.strftime(FMT),
            'plate_number': 'mh 15 ab 1234', 'vehicle_type': 'car'}
    data.update(kw)
    return data


class BookingFlowTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        self.url = reverse('bookings:book', args=[self.slot.pk])
        self.client.force_login(self.user)

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_successful_booking_creates_vehicle_and_confirmation(self):
        r = self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        b = Booking.objects.get()
        self.assertRedirects(r, b.get_absolute_url())
        self.assertTrue(b.reference.startswith('PK-'))
        self.assertEqual(b.status, 'confirmed')
        self.assertEqual(b.vehicle.plate_number, 'MH15AB1234')
        self.assertContains(self.client.get(b.get_absolute_url()), b.reference)

    def test_vehicle_reused_by_plate(self):
        self.client.post(self.url, book_data(at(1, 10), at(1, 11)))
        self.client.post(self.url, book_data(at(2, 10), at(2, 11), plate_number='MH15AB1234'))
        self.assertEqual(Vehicle.objects.count(), 1)
        self.assertEqual(Booking.objects.count(), 2)

    def test_can_pick_saved_vehicle(self):
        v = Vehicle.objects.create(user=self.user, plate_number='KA01XY9999')
        self.client.post(self.url, {'start_time': at(1, 9).strftime(FMT), 'end_time': at(1, 10).strftime(FMT), 'vehicle': v.pk})
        self.assertEqual(Booking.objects.get().vehicle, v)

    def test_cannot_use_another_users_vehicle(self):
        other = Vehicle.objects.create(user=make_user('bob'), plate_number='KA01XY9999')
        r = self.client.post(self.url, {'start_time': at(1, 9).strftime(FMT), 'end_time': at(1, 10).strftime(FMT), 'vehicle': other.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Booking.objects.count(), 0)

    def _rejected(self, data, text=None):
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Booking.objects.count(), 0)
        if text:
            self.assertContains(r, text)

    def test_time_validation(self):
        self._rejected(book_data(timezone.now() - timedelta(hours=2), timezone.now() + timedelta(hours=1)), 'in the future')
        self._rejected(book_data(at(1, 12), at(1, 10)), 'after the start')
        self._rejected(book_data(at(1, 10), at(1, 10, 10)), 'Minimum booking')
        self._rejected(book_data(at(1, 10), at(3, 10)), 'Maximum booking')
        self._rejected(book_data(at(60, 10), at(60, 12)), 'ahead')

    def test_vehicle_validation(self):
        self._rejected(book_data(at(1, 10), at(1, 12), plate_number=''), 'plate number')
        self._rejected(book_data(at(1, 10), at(1, 12), plate_number='!!'))
        self._rejected(book_data(at(1, 10), at(1, 12), vehicle_type='bike'), 'cannot use')

    def test_overlap_rejected_but_back_to_back_allowed(self):
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        other = self.client.post(self.url, book_data(at(1, 11), at(1, 13), plate_number='KA01XY9999'))
        self.assertContains(other, 'already booked')
        self.client.post(self.url, book_data(at(1, 9), at(1, 10, 30), plate_number='KA01XY9999'))
        self.assertEqual(Booking.objects.count(), 1)
        self.client.post(self.url, book_data(at(1, 12), at(1, 13), plate_number='KA01XY9999'))
        self.client.post(self.url, book_data(at(1, 9), at(1, 10), plate_number='TN01ZZ0001'))
        self.assertEqual(Booking.objects.count(), 3)

    def test_second_user_cannot_double_book(self):
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        self.client.force_login(make_user('bob'))
        self.client.post(self.url, book_data(at(1, 10, 30), at(1, 11), plate_number='GJ01AA0001'))
        self.assertEqual(Booking.objects.count(), 1)

    def test_same_vehicle_cannot_overlap_on_different_slots(self):
        slot2 = make_slot(self.slot.location, 'A2')
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        r = self.client.post(reverse('bookings:book', args=[slot2.pk]), book_data(at(1, 11), at(1, 13)))
        self.assertContains(r, 'already has a booking')

    def test_unavailable_slot_and_inactive_location_cannot_be_booked(self):
        self.slot.status = 'unavailable'
        self.slot.save()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        self.assertEqual(Booking.objects.count(), 0)
        self.slot.status = 'available'
        self.slot.save()
        self.slot.location.is_active = False
        self.slot.location.save()
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        self.assertEqual(Booking.objects.count(), 0)

    def test_occupied_slot_can_be_booked_for_later(self):
        self.slot.status = 'occupied'
        self.slot.save()
        self.client.post(self.url, book_data(at(1, 10), at(1, 12)))
        self.assertEqual(Booking.objects.count(), 1)

    def test_opening_hours_enforced(self):
        loc = ParkingLocation.objects.create(name='Office', address='x', city='Pune',
                                             opening_time=time(8, 0), closing_time=time(20, 0))
        slot = make_slot(loc, 'O1')
        url = reverse('bookings:book', args=[slot.pk])
        for s, e in [(at(1, 7), at(1, 9)), (at(1, 19), at(1, 21)), (at(1, 18), at(2, 9))]:
            self.client.post(url, book_data(s, e))
        self.assertEqual(Booking.objects.count(), 0)
        self.client.post(url, book_data(at(1, 9), at(1, 18)))
        self.assertEqual(Booking.objects.count(), 1)

    def test_bike_and_ev_slot_compatibility(self):
        bike_slot = make_slot(self.slot.location, 'B1', slot_type='bike')
        url = reverse('bookings:book', args=[bike_slot.pk])
        self.client.post(url, book_data(at(1, 10), at(1, 11), plate_number='MH12BK0001', vehicle_type='car'))
        self.assertEqual(Booking.objects.count(), 0)
        self.client.post(url, book_data(at(1, 10), at(1, 11), plate_number='MH12BK0001', vehicle_type='bike'))
        self.assertEqual(Booking.objects.count(), 1)


class HistoryAndCancelTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('bob')
        self.slot = make_slot()
        self.v = Vehicle.objects.create(user=self.user, plate_number='MH15AB1234')
        self.ov = Vehicle.objects.create(user=self.other, plate_number='KA01XY9999')
        self.client.force_login(self.user)

    def mk(self, start, end=None, user=None, status='confirmed'):
        user = user or self.user
        return Booking.objects.create(user=user, slot=self.slot, vehicle=self.v if user == self.user else self.ov,
                                      start_time=start, end_time=end or start + timedelta(hours=1), status=status)

    def test_history_shows_only_own_and_filters(self):
        mine = self.mk(at(1, 10))
        done = self.mk(at(-1, 10), status='completed')
        theirs = self.mk(at(2, 10), user=self.other)
        r = self.client.get(reverse('bookings:history'))
        refs = {b.reference for b in r.context['page']}
        self.assertEqual(refs, {mine.reference, done.reference})
        r = self.client.get(reverse('bookings:history'), {'status': 'completed'})
        self.assertEqual([b.reference for b in r.context['page']], [done.reference])
        self.assertNotContains(self.client.get(reverse('bookings:history')), theirs.reference)

    def test_history_pagination_and_empty_state(self):
        self.assertContains(self.client.get(reverse('bookings:history')), 'No bookings yet')
        for i in range(12):
            self.mk(at(i + 1, 10))
        r = self.client.get(reverse('bookings:history'))
        self.assertEqual(len(r.context['page']), 10)
        self.assertEqual(len(self.client.get(reverse('bookings:history'), {'page': 2}).context['page']), 2)

    def test_other_users_booking_is_404(self):
        theirs = self.mk(at(2, 10), user=self.other)
        self.assertEqual(self.client.get(theirs.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse('bookings:cancel', args=[theirs.reference])).status_code, 404)

    def test_cancel_eligible_booking_frees_the_window(self):
        b = self.mk(at(1, 10), at(1, 12))
        r = self.client.post(reverse('bookings:cancel', args=[b.reference]))
        self.assertRedirects(r, b.get_absolute_url())
        b.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')
        self.assertIsNotNone(b.cancelled_at)
        self.client.post(reverse('bookings:book', args=[self.slot.pk]), book_data(at(1, 10), at(1, 12), plate_number='MH15AB1234'))
        self.assertEqual(Booking.objects.filter(status='confirmed').count(), 1)

    def test_cancel_blocked_inside_cutoff_and_when_not_confirmed(self):
        soon = self.mk(timezone.now() + timedelta(minutes=30))
        self.client.post(reverse('bookings:cancel', args=[soon.reference]))
        soon.refresh_from_db()
        self.assertEqual(soon.status, 'confirmed')
        self.assertFalse(soon.can_cancel)
        self.assertContains(self.client.get(soon.get_absolute_url()), 'at least 60 minutes')
        done = self.mk(at(3, 10), status='checked_in')
        self.client.post(reverse('bookings:cancel', args=[done.reference]))
        done.refresh_from_db()
        self.assertEqual(done.status, 'checked_in')

    def test_cancel_requires_post(self):
        b = self.mk(at(1, 10))
        self.assertEqual(self.client.get(reverse('bookings:cancel', args=[b.reference])).status_code, 405)


class DeleteProtectionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        v = Vehicle.objects.create(user=self.user, plate_number='MH15AB1234')
        Booking.objects.create(user=self.user, slot=self.slot, vehicle=v, start_time=at(1, 10), end_time=at(1, 11))

    def test_model_level_protection(self):
        with self.assertRaises(ProtectedError):
            self.slot.delete()

    def test_admin_views_show_message_instead_of_crashing(self):
        self.client.force_login(make_admin())
        r = self.client.post(reverse('parking:slot_delete', args=[self.slot.pk]), follow=True)
        self.assertContains(r, 'has bookings')
        r = self.client.post(reverse('parking:location_delete', args=[self.slot.location.pk]), follow=True)
        self.assertContains(r, 'has bookings')
        self.assertTrue(ParkingSlot.objects.filter(pk=self.slot.pk).exists())

    def test_api_returns_409(self):
        self.client.force_login(make_admin())
        self.assertEqual(self.client.delete(f'/api/parking/slots/{self.slot.pk}/').status_code, 409)
        self.assertEqual(self.client.delete(f'/api/parking/locations/{self.slot.location.pk}/').status_code, 409)


class APITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.slot = make_slot()
        self.client.force_login(self.user)

    def post(self, body, url='/api/bookings/'):
        return self.client.post(url, body, content_type='application/json')

    def body(self, start, end, **kw):
        d = {'slot': self.slot.pk, 'start_time': start.isoformat(), 'end_time': end.isoformat(),
             'plate_number': 'MH15AB1234', 'vehicle_type': 'car'}
        d.update(kw)
        return d

    def test_create_list_filter_retrieve_cancel(self):
        r = self.post(self.body(at(1, 10), at(1, 12)))
        self.assertEqual(r.status_code, 201, r.content)
        ref = r.json()['reference']
        self.assertTrue(r.json()['can_cancel'])
        self.assertEqual(self.client.get('/api/bookings/').json()['count'], 1)
        self.assertEqual(self.client.get('/api/bookings/', {'status': 'cancelled'}).json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/bookings/{ref}/').json()['vehicle']['plate_number'], 'MH15AB1234')
        r = self.post({}, f'/api/bookings/{ref}/cancel/')
        self.assertEqual((r.status_code, r.json()['status']), (200, 'cancelled'))
        self.assertEqual(self.post({}, f'/api/bookings/{ref}/cancel/').status_code, 400)

    def test_api_validation_and_overlap(self):
        self.assertEqual(self.post(self.body(at(1, 10), at(1, 12))).status_code, 201)
        r = self.post(self.body(at(1, 11), at(1, 13), plate_number='KA01XY9999'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('already booked', str(r.json()))
        self.assertEqual(self.post(self.body(at(1, 12), at(1, 11), plate_number='KA01XY9999')).status_code, 400)
        self.assertEqual(self.post({'slot': self.slot.pk}).status_code, 400)
        self.assertEqual(self.post(self.body(at(3, 10), at(3, 11), slot=99999)).status_code, 400)

    def test_api_requires_auth_and_isolates_users(self):
        self.post(self.body(at(1, 10), at(1, 12)))
        ref = Booking.objects.get().reference
        self.client.logout()
        self.assertIn(self.client.get('/api/bookings/').status_code, (401, 403))
        self.client.force_login(make_user('bob'))
        self.assertEqual(self.client.get('/api/bookings/').json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/bookings/{ref}/').status_code, 404)
        self.assertEqual(self.post({}, f'/api/bookings/{ref}/cancel/').status_code, 404)

    def test_admin_reads_all_but_cannot_cancel_others(self):
        self.post(self.body(at(1, 10), at(1, 12)))
        ref = Booking.objects.get().reference
        self.client.force_login(make_admin())
        self.assertEqual(self.client.get('/api/bookings/').json()['count'], 1)
        self.assertEqual(self.post({}, f'/api/bookings/{ref}/cancel/').status_code, 403)

    def test_cannot_book_with_others_vehicle_id(self):
        v = Vehicle.objects.create(user=make_user('bob'), plate_number='GJ01AA0001')
        r = self.post({'slot': self.slot.pk, 'start_time': at(1, 10).isoformat(),
                       'end_time': at(1, 11).isoformat(), 'vehicle': v.pk})
        self.assertEqual(r.status_code, 400)

    def test_vehicle_endpoints(self):
        r = self.post({'plate_number': 'a b 1', 'vehicle_type': 'bike'}, '/api/bookings/vehicles/')
        self.assertEqual(r.status_code, 400)  # plate too short
        r = self.post({'plate_number': 'mh 01 aa 0001', 'vehicle_type': 'bike'}, '/api/bookings/vehicles/')
        self.assertEqual(r.status_code, 201, r.content)
        vid = r.json()['id']
        self.assertEqual(self.post({'plate_number': 'MH01AA0001', 'vehicle_type': 'bike'}, '/api/bookings/vehicles/').status_code, 400)
        self.assertEqual(self.client.get('/api/bookings/vehicles/').json()['count'], 1)
        self.post(self.body(at(1, 10), at(1, 11), vehicle=vid, plate_number='', vehicle_type='bike', slot=make_slot(self.slot.location, 'B1', slot_type='bike').pk))
        self.assertEqual(self.client.delete(f'/api/bookings/vehicles/{vid}/').status_code, 409)
