"""Production-readiness checks that normal tests (which use plain static storage) would miss."""
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.test import TestCase, override_settings

PROJECT = Path(settings.BASE_DIR)


class StaticFilesForProductionTests(TestCase):
    def test_collectstatic_works_with_manifest_storage_and_every_template_reference_resolves(self):
        """With hashed (manifest) storage one missing file makes every page return 500 in production."""
        with tempfile.TemporaryDirectory() as root:
            storages = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'}}
            with override_settings(STATIC_ROOT=root, STORAGES=storages):
                call_command('collectstatic', interactive=False, verbosity=0)  # fails on broken references in JS/CSS
                names = set()
                for path in (PROJECT / 'templates').rglob('*.html'):
                    names |= set(re.findall(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""", path.read_text()))
                self.assertGreaterEqual(len(names), 5)  # style.css + 4 scripts; guards against the regex matching nothing
                for name in sorted(names):
                    url = staticfiles_storage.url(name)  # raises ValueError if missing from the manifest
                    self.assertRegex(url, r'\.[0-9a-f]{12}\.\w+$', name)

    def test_vendored_scripts_do_not_reference_missing_files(self):
        for path in (PROJECT / 'static' / 'js').rglob('*.js'):
            self.assertNotIn('sourceMappingURL', path.read_text(), path.name)

    def test_production_files_exist(self):
        self.assertTrue((PROJECT / 'requirements-prod.txt').is_file())
        self.assertIn('gunicorn config.wsgi', (PROJECT / 'Procfile').read_text())
        prod = (PROJECT / 'requirements-prod.txt').read_text()
        self.assertIn('whitenoise', prod)
        self.assertIn('gunicorn', prod)
