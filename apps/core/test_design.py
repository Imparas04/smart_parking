"""The redesigned frontend: live home page data, template helpers, illustrations and icons."""
import re
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, Vehicle
from apps.core.templatetags import ui
from apps.parking.models import ParkingLocation, ParkingSlot
from apps.payments import services as payment_services

PROJECT = Path(settings.BASE_DIR)
User = get_user_model()


def make_location(name, city='Nashik', free=0, occupied=0, unavailable=0, **kw):
    loc = ParkingLocation.objects.create(name=name, address='MG Road', city=city, hourly_rate=Decimal('30'), **kw)
    n = 0
    for status, count in (('available', free), ('occupied', occupied), ('unavailable', unavailable)):
        for _ in range(count):
            n += 1
            ParkingSlot.objects.create(location=loc, slot_number=f'S{n}', status=status)
    return loc


class TemplateHelperTests(SimpleTestCase):
    def test_pct(self):
        self.assertEqual([ui.pct(v, t) for v, t in ((8, 12), (0, 5), (5, 5), (3, 0), ('x', 4), (None, None), (9, 4), (-2, 4))], [67, 0, 100, 0, 0, 0, 100, 0])

    def test_meter_class(self):
        self.assertEqual([ui.meter_class(a, t) for a, t in ((10, 10), (2, 10), (1, 10), (0, 10), (0, 0), ('x', 'y'))], ['', 'low', 'low', 'none', 'none', 'none'])

    def test_art_variant_is_stable_and_in_range(self):
        self.assertEqual({ui.art(i) for i in range(40)}, {0, 1, 2, 3})
        self.assertEqual(ui.art(7), ui.art(7))
        self.assertEqual(ui.art('oops'), 0)

    def test_slot_icon_mapping_and_fallback(self):
        self.assertEqual([ui.slot_icon(t) for t in ('car', 'bike', 'ev', 'accessible', 'weird')], ['car', 'bike', 'bolt', 'access', 'car'])

    def test_icon_tag_renders_an_accessible_sprite_reference_and_escapes(self):
        html = Template("{% load ui %}{% icon 'car' 'icon-lg' %}").render(Context())
        self.assertIn('<use href="#i-car"/>', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('icon icon-lg', html)
        hostile = Template("{% load ui %}{% icon name %}").render(Context({'name': '"><script>x</script>'}))
        self.assertNotIn('<script>', hostile)


class HomePageTests(TestCase):
    def test_renders_with_an_empty_database(self):
        r = self.client.get(reverse('core:home'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['stats'], {'locations': 0, 'free': 0, 'total': 0, 'cities': 0})
        self.assertEqual(r.context['featured'], [])
        self.assertNotContains(r, 'Popular locations')
        self.assertContains(r, 'Find and book parking')

    def test_shows_live_numbers_from_active_locations_only(self):
        make_location('Central', free=3, occupied=2, unavailable=1)
        make_location('Mall', city='Pune', free=1)
        make_location('Hidden', free=50, is_active=False)
        r = self.client.get(reverse('core:home'))
        self.assertEqual(r.context['stats'], {'locations': 2, 'free': 4, 'total': 7, 'cities': 2})
        self.assertNotContains(r, 'Hidden')

    def test_popular_locations_are_the_three_with_most_free_bays(self):
        for name, free in (('Few', 1), ('Most', 9), ('Some', 4), ('Many', 7), ('None', 0)):
            make_location(name, free=free)
        r = self.client.get(reverse('core:home'))
        self.assertEqual([l.name for l in r.context['featured']], ['Most', 'Many', 'Some'])
        self.assertContains(r, 'Popular locations')

    def test_hero_search_and_city_chips_point_at_the_parking_page(self):
        make_location('Central', city='Nashik', free=1)
        html = self.client.get(reverse('core:home')).content.decode()
        self.assertIn(f'action="{reverse("parking:location_list")}"', html)
        self.assertIn('name="q"', html)
        self.assertIn(f'{reverse("parking:location_list")}?city=Nashik', html)

    def test_home_exposes_no_private_data(self):
        user = User.objects.create_user('secretive', 'secret@example.com', 'x')
        loc = make_location('Central', free=2)
        v = Vehicle.objects.create(user=user, plate_number='MH15AB1234')
        b = Booking.objects.create(user=user, slot=loc.slots.first(), vehicle=v, start_time=timezone.now() + timedelta(days=1),
                                   end_time=timezone.now() + timedelta(days=1, hours=2), hourly_rate=Decimal('30'))
        payment_services.create_for_booking(b)
        html = self.client.get(reverse('core:home')).content.decode()
        for secret in ('secretive', 'secret@example.com', 'MH15AB1234', b.reference):
            self.assertNotIn(secret, html)

    def test_home_query_count_does_not_grow_with_data(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(12):
            make_location(f'Lot {i}', city=f'City{i % 4}', free=2, occupied=1)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('core:home'))
        self.assertLessEqual(len(ctx), 6)


class LocationCardTests(TestCase):
    def test_card_shows_the_availability_bar_and_state(self):
        make_location('Roomy', free=8, occupied=4)
        make_location('Tight', free=1, occupied=9)
        make_location('Full', occupied=5)
        html = self.client.get(reverse('parking:location_list')).content.decode()
        self.assertIn('--fill: 67%', html)                                  # 8 of 12
        self.assertRegex(html, r'class="meter low"')                        # 1 of 10
        self.assertRegex(html, r'class="meter none"')                       # 0 of 5
        self.assertIn('Full</span>', html)
        self.assertIn('8 free', html)


class IllustrationAndIconTests(SimpleTestCase):
    def svg_files(self):
        files = sorted((PROJECT / 'static' / 'img').glob('*.svg'))
        self.assertGreaterEqual(len(files), 5)
        return files

    def test_every_illustration_is_well_formed_safe_and_small(self):
        for path in self.svg_files():
            text = path.read_text()
            root = ET.fromstring(text)  # raises on malformed XML
            self.assertTrue(root.tag.endswith('svg'), path.name)
            self.assertIn('viewBox', root.attrib, path.name)
            self.assertNotIn('<script', text.lower(), path.name)
            self.assertNotRegex(text, r'(href|src)\s*=\s*"(https?:|//|data:text/html)', path.name)
            self.assertNotRegex(text, r'\son[a-z]+\s*=', path.name)
            self.assertLess(path.stat().st_size, 20_000, path.name)
            if '@keyframes' in text:
                self.assertIn('prefers-reduced-motion', text, f'{path.name} animates but ignores reduced-motion')

    def test_meaningful_illustrations_have_a_text_alternative(self):
        for name in ('hero-parking.svg', 'auth-art.svg', 'error-art.svg', 'empty-state.svg', 'logo.svg'):
            root = ET.fromstring((PROJECT / 'static' / 'img' / name).read_text())
            self.assertTrue(root.attrib.get('role') == 'img' and ('aria-label' in root.attrib or 'aria-labelledby' in root.attrib), name)

    def test_every_icon_used_in_a_template_exists_in_the_sprite(self):
        sprite = (PROJECT / 'templates' / 'partials' / 'icons.html').read_text()
        defined = set(re.findall(r'<symbol id="i-([a-z]+)"', sprite))
        used = set()
        for path in (PROJECT / 'templates').rglob('*.html'):
            used |= set(re.findall(r"""\{%\s*icon\s+'([a-z]+)'""", path.read_text()))
        used |= set(ui.SLOT_ICONS.values())
        self.assertGreater(len(used), 15)
        self.assertEqual(sorted(used - defined), [])

    def test_sprite_symbols_are_unique_and_well_formed(self):
        sprite = (PROJECT / 'templates' / 'partials' / 'icons.html').read_text()
        ids = re.findall(r'<symbol id="(i-[a-z]+)"', sprite)
        self.assertEqual(len(ids), len(set(ids)))
        ET.fromstring(sprite)


class RenderedMarkupTests(TestCase):
    def test_every_image_has_alt_text_and_dimensions_on_key_pages(self):
        make_location('Central', free=2)
        user = User.objects.create_user('alice', 'a@example.com', 'x')
        urls = [reverse('core:home'), reverse('accounts:login'), reverse('accounts:register'), reverse('parking:location_list'),
                '/no/such/page/']
        self.client.force_login(user)
        urls += [reverse('bookings:history')]
        for url in urls:
            html = self.client.get(url).content.decode()
            for tag in re.findall(r'<img\b[^>]*>', html):
                self.assertIn('alt=', tag, f'{url}: {tag}')
                self.assertRegex(tag, r'width="\d+"', f'{url}: {tag}')

    def test_brand_is_a_single_text_unit_and_viewport_is_set(self):
        html = self.client.get(reverse('core:home')).content.decode()
        self.assertIn('<span class="brand-name">Smart<span>Park</span></span>', html)
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', html)
