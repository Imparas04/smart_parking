from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import ParkingLocation, ParkingSlot

User = get_user_model()
PW = 'Str0ng-Pass-993'


def make_admin():
    u = User.objects.create_user('boss', 'boss@example.com', PW)
    u.profile.role = 'admin'
    u.profile.save()
    return u


def make_location(name='Central', city='Nashik', **kw):
    return ParkingLocation.objects.create(name=name, address='MG Road', city=city, **kw)


def make_slot(loc, number='A1', **kw):
    return ParkingSlot.objects.create(location=loc, slot_number=number, **kw)


class ModelTests(TestCase):
    def test_slot_number_unique_per_location_and_normalised(self):
        loc, other = make_location(), make_location('Other')
        make_slot(loc, ' a1 ')
        self.assertEqual(loc.slots.get().slot_number, 'A1')
        make_slot(other, 'A1')  # same number elsewhere is fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_slot(loc, 'A1')

    def test_location_name_city_unique(self):
        make_location()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_location()


class PublicViewTests(TestCase):
    def setUp(self):
        self.a = make_location('Alpha Park', 'Nashik', hourly_rate=Decimal('25'))
        self.b = make_location('Beta Park', 'Pune')
        self.hidden = make_location('Hidden Lot', 'Nashik', is_active=False)
        make_slot(self.a, 'A1')
        make_slot(self.a, 'A2', status='occupied')
        make_slot(self.a, 'E1', slot_type='ev')
        make_slot(self.b, 'B1', status='occupied')

    def test_list_hides_inactive_and_shows_counts(self):
        r = self.client.get(reverse('parking:location_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Alpha Park')
        self.assertNotContains(r, 'Hidden Lot')
        alpha = next(l for l in r.context['page'].object_list if l.pk == self.a.pk)
        self.assertEqual((alpha.total_slots, alpha.available_slots), (3, 2))

    def test_search_city_and_availability_filters(self):
        url = reverse('parking:location_list')
        self.assertEqual([l.name for l in self.client.get(url, {'q': 'beta'}).context['page']], ['Beta Park'])
        self.assertEqual([l.name for l in self.client.get(url, {'city': 'pune'}).context['page']], ['Beta Park'])
        self.assertEqual([l.name for l in self.client.get(url, {'available': '1'}).context['page']], ['Alpha Park'])
        self.assertEqual([l.name for l in self.client.get(url, {'slot_type': 'ev'}).context['page']], ['Alpha Park'])
        r = self.client.get(url, {'q': 'zzz'})
        self.assertContains(r, 'No parking locations found')

    def test_detail_shows_status_classes_and_type_filter(self):
        r = self.client.get(self.a.get_absolute_url())
        for cls in ('slot-available', 'slot-occupied'):
            self.assertContains(r, cls)
        self.assertEqual((r.context['available'], r.context['occupied'], r.context['unavailable']), (2, 1, 0))
        r = self.client.get(self.a.get_absolute_url(), {'slot_type': 'ev'})
        self.assertEqual(len(r.context['slots']), 1)

    def test_inactive_location_404_for_public_visible_for_admin(self):
        slot = make_slot(self.hidden, 'H1')
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(slot.get_absolute_url()).status_code, 404)
        self.client.force_login(make_admin())
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(slot.get_absolute_url()).status_code, 200)

    def test_slot_detail_page(self):
        slot = self.a.slots.get(slot_number='A1')
        r = self.client.get(slot.get_absolute_url())
        self.assertContains(r, 'Slot A1')
        self.assertContains(r, 'Available')


class AdminCrudTests(TestCase):
    def setUp(self):
        self.loc = make_location()
        self.new_loc = {'name': 'New Lot', 'address': 'X Street', 'city': 'Nashik', 'description': '',
                        'opening_time': '06:00', 'closing_time': '22:00', 'hourly_rate': '30.00', 'is_active': 'on'}

    def test_non_admin_blocked_everywhere(self):
        urls = [reverse('parking:location_create'), reverse('parking:location_update', args=[self.loc.pk]),
                reverse('parking:location_delete', args=[self.loc.pk]),
                reverse('parking:slot_create', args=[self.loc.pk]), reverse('parking:slot_bulk_create', args=[self.loc.pk])]
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 302)  # anonymous -> login
        self.client.force_login(User.objects.create_user('u', 'u@example.com', PW))
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 403)
            self.assertEqual(self.client.post(u, self.new_loc).status_code, 403)
        self.assertEqual(ParkingLocation.objects.count(), 1)

    def test_admin_location_crud(self):
        self.client.force_login(make_admin())
        r = self.client.post(reverse('parking:location_create'), self.new_loc)
        new = ParkingLocation.objects.get(name='New Lot')
        self.assertRedirects(r, new.get_absolute_url())
        self.client.post(reverse('parking:location_update', args=[new.pk]), {**self.new_loc, 'hourly_rate': '45.00'})
        new.refresh_from_db()
        self.assertEqual(new.hourly_rate, Decimal('45.00'))
        self.client.post(reverse('parking:location_delete', args=[new.pk]))
        self.assertFalse(ParkingLocation.objects.filter(pk=new.pk).exists())

    def test_location_validation(self):
        self.client.force_login(make_admin())
        r = self.client.post(reverse('parking:location_create'), {**self.new_loc, 'name': 'central', 'hourly_rate': '-1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ParkingLocation.objects.count(), 1)

    def test_delete_requires_post(self):
        self.client.force_login(make_admin())
        self.client.get(reverse('parking:location_delete', args=[self.loc.pk]))
        self.assertTrue(ParkingLocation.objects.filter(pk=self.loc.pk).exists())

    def test_admin_slot_crud_and_duplicate_rejected(self):
        self.client.force_login(make_admin())
        add = reverse('parking:slot_create', args=[self.loc.pk])
        self.client.post(add, {'slot_number': 'z9', 'slot_type': 'car', 'status': 'available', 'notes': ''})
        slot = self.loc.slots.get()
        self.assertEqual(slot.slot_number, 'Z9')
        r = self.client.post(add, {'slot_number': 'Z9', 'slot_type': 'car', 'status': 'available', 'notes': ''})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.loc.slots.count(), 1)
        self.client.post(reverse('parking:slot_update', args=[slot.pk]),
                         {'slot_number': 'Z9', 'slot_type': 'ev', 'status': 'unavailable', 'notes': 'broken'})
        slot.refresh_from_db()
        self.assertEqual((slot.status, slot.slot_type), ('unavailable', 'ev'))
        self.client.post(reverse('parking:slot_delete', args=[slot.pk]))
        self.assertEqual(self.loc.slots.count(), 0)

    def test_bulk_create(self):
        self.client.force_login(make_admin())
        url = reverse('parking:slot_bulk_create', args=[self.loc.pk])
        self.client.post(url, {'prefix': 'b-', 'start': 1, 'count': 5, 'slot_type': 'car'})
        self.assertEqual(sorted(self.loc.slots.values_list('slot_number', flat=True)), ['B-1', 'B-2', 'B-3', 'B-4', 'B-5'])
        r = self.client.post(url, {'prefix': 'B-', 'start': 4, 'count': 3, 'slot_type': 'car'})
        self.assertEqual(r.status_code, 200)  # conflict, nothing created
        self.assertEqual(self.loc.slots.count(), 5)
        r = self.client.post(url, {'prefix': '', 'start': 1, 'count': 500, 'slot_type': 'car'})
        self.assertEqual(self.loc.slots.count(), 5)


class APITests(TestCase):
    def setUp(self):
        self.loc = make_location()
        self.slot = make_slot(self.loc, 'A1')
        self.hidden = make_location('Hidden', is_active=False)
        make_slot(self.hidden, 'H1')
        self.admin = make_admin()
        self.user = User.objects.create_user('u', 'u@example.com', PW)

    def test_public_read_and_hidden_filtering(self):
        r = self.client.get('/api/parking/locations/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([l['name'] for l in r.json()['results']], ['Central'])
        self.assertEqual(r.json()['results'][0]['available_slots'], 1)
        self.assertEqual(self.client.get('/api/parking/locations/%d/' % self.hidden.pk).status_code, 404)
        r = self.client.get('/api/parking/slots/', {'location': self.loc.pk, 'status': 'available'})
        self.assertEqual(r.json()['count'], 1)
        self.assertEqual(self.client.get('/api/parking/slots/').json()['count'], 1)

    def test_writes_need_admin(self):
        body = {'name': 'N', 'address': 'a', 'city': 'c', 'hourly_rate': '10.00'}
        self.assertIn(self.client.post('/api/parking/locations/', body, content_type='application/json').status_code, (401, 403))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/api/parking/locations/', body, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.delete('/api/parking/slots/%d/' % self.slot.pk).status_code, 403)

    def test_admin_crud_and_validation(self):
        self.client.force_login(self.admin)
        r = self.client.post('/api/parking/locations/', {'name': 'N', 'address': 'a', 'city': 'c', 'hourly_rate': '10.00'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        loc_id = r.json()['id']
        r = self.client.post('/api/parking/slots/', {'location': loc_id, 'slot_number': 'x1', 'slot_type': 'car', 'status': 'available'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['slot_number'], 'X1')
        r = self.client.post('/api/parking/slots/', {'location': loc_id, 'slot_number': 'X1'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/parking/slots/', {'location': loc_id, 'slot_number': 'Y', 'status': 'bogus'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        r = self.client.patch('/api/parking/slots/%d/' % self.slot.pk, {'status': 'occupied'}, content_type='application/json')
        self.assertEqual(r.json()['status'], 'occupied')
        self.assertEqual(self.client.delete('/api/parking/slots/%d/' % self.slot.pk).status_code, 204)


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent(self):
        call_command('seed_parking', stdout=StringIO())
        n = ParkingSlot.objects.count()
        call_command('seed_parking', stdout=StringIO())
        self.assertEqual(ParkingLocation.objects.count(), 3)
        self.assertEqual(ParkingSlot.objects.count(), n)


class ApiResponseShapeTests(TestCase):
    """Every location response has the same fields, whether it comes from a list, a create or an update."""

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def test_create_and_update_responses_include_slot_counts_like_list_and_detail(self):
        body = {'name': 'Shape Lot', 'address': 'a', 'city': 'c', 'hourly_rate': '10.00'}
        created = self.client.post('/api/parking/locations/', body, content_type='application/json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual((created.json()['total_slots'], created.json()['available_slots']), (0, 0))
        pk = created.json()['id']
        make_slot(ParkingLocation.objects.get(pk=pk), 'S1')
        make_slot(ParkingLocation.objects.get(pk=pk), 'S2', status='occupied')
        updated = self.client.patch(f'/api/parking/locations/{pk}/', {'hourly_rate': '12.00'}, content_type='application/json')
        listed = self.client.get('/api/parking/locations/').json()['results'][0]
        detail = self.client.get(f'/api/parking/locations/{pk}/').json()
        self.assertEqual(set(created.json()), set(updated.json()))
        self.assertEqual(set(created.json()), set(listed))
        self.assertEqual((updated.json()['total_slots'], updated.json()['available_slots']), (2, 1))
        self.assertEqual((detail['total_slots'], detail['available_slots']), (2, 1))

    def test_duplicate_slot_error_is_clear_and_case_insensitive(self):
        loc = make_location()
        make_slot(loc, 'A1')
        for number in ('A1', 'a1', ' A1 '):
            r = self.client.post('/api/parking/slots/', {'location': loc.pk, 'slot_number': number}, content_type='application/json')
            self.assertEqual(r.status_code, 400, number)
            self.assertIn('already exists', r.json()['slot_number'][0])
        self.assertEqual(loc.slots.count(), 1)


class ApiSurfaceTests(TestCase):
    def test_no_undocumented_router_extras(self):
        """The API exposes only the documented endpoints: no browsable API root, no .json suffix variants."""
        make_location()
        self.assertEqual(self.client.get('/api/parking/').status_code, 404)
        self.assertEqual(self.client.get('/api/parking/locations.json').status_code, 404)
        self.assertEqual(self.client.get('/api/parking/locations/').status_code, 200)
