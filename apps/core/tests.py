from django.test import TestCase
from django.urls import reverse


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse('core:home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'Find and book parking')

    def test_static_and_media_settings(self):
        from django.conf import settings
        self.assertTrue(str(settings.STATIC_ROOT).endswith('staticfiles'))
        self.assertTrue(str(settings.MEDIA_ROOT).endswith('media'))

    def test_all_apps_installed(self):
        from django.apps import apps
        for label in ['core', 'accounts', 'parking', 'bookings', 'payments', 'dashboard']:
            self.assertTrue(apps.is_installed(f'apps.{label}'))
