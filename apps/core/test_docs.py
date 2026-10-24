"""The documentation must keep matching the code: routes, commands, settings, links, generated files."""
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import get_commands
from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver

PROJECT = Path(settings.BASE_DIR)
MARKDOWN = [PROJECT / 'README.md', PROJECT / 'CHANGELOG.md', *sorted((PROJECT / 'docs').glob('*.md'))]


def api_routes_in_code():
    def walk(patterns, prefix=''):
        for p in patterns:
            if hasattr(p, 'url_patterns'):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)

    routes = set()
    for raw in walk(get_resolver().url_patterns):
        if not raw.lstrip('^').startswith('api/'):
            continue
        path = '/' + re.sub(r'[\^$]', '', raw)
        path = re.sub(r'\(\?P<(\w+)>[^)]*\)', '{}', path)  # router (regex) patterns
        path = re.sub(r'<(?:\w+:)?\w+>', '{}', path)  # path() converters
        routes.add(re.sub(r'/\^?', '/', path).replace('//', '/'))
    return routes


def documented_endpoints():
    text = (PROJECT / 'docs' / 'API.md').read_text()
    return {(m, re.sub(r'\{[^}]+\}', '{}', p)) for m, p in re.findall(r'^### (GET|POST|PUT|PATCH|DELETE) (/api/\S+)$', text, re.M)}


def postman_endpoints():
    import json
    data = json.loads((PROJECT / 'docs' / 'postman' / 'SmartParking.postman_collection.json').read_text())
    found = set()
    for folder in data['item']:
        for item in folder['item']:
            raw = item['request']['url']['raw'].replace('{{base_url}}', '').split('?')[0]
            found.add((item['request']['method'], re.sub(r'\{\{[^}]+\}\}', '{}', raw)))
    return found


class ApiDocsMatchTheCode(SimpleTestCase):
    def test_every_api_route_in_the_code_is_documented_and_nothing_stale_is(self):
        documented_paths = {p for _, p in documented_endpoints()}
        self.assertEqual(api_routes_in_code(), documented_paths)

    def test_postman_collection_covers_exactly_the_documented_endpoints(self):
        self.assertEqual(postman_endpoints(), documented_endpoints())


class GeneratedFilesTests(TestCase):
    def test_generated_docs_are_up_to_date(self):
        r = subprocess.run([sys.executable, 'tools/build_docs.py', '--check'], cwd=str(PROJECT), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class DocumentationHygieneTests(SimpleTestCase):
    def test_no_unfilled_placeholders(self):
        for path in MARKDOWN:
            self.assertNotIn('@@', path.read_text(), path.name)

    def test_relative_links_point_to_real_files(self):
        broken = []
        for path in MARKDOWN:
            for target in re.findall(r'\]\(([^)\s]+)\)', path.read_text()):
                if target.startswith(('http://', 'https://', 'mailto:', '#')):
                    continue
                if not (path.parent / target.split('#')[0]).exists():
                    broken.append((path.name, target))
        self.assertEqual(broken, [])

    def test_every_management_command_mentioned_exists(self):
        known, missing = set(get_commands()), []
        for path in MARKDOWN:
            for command in re.findall(r'manage\.py (\w+)', path.read_text()):
                if command not in known:
                    missing.append((path.name, command))
        self.assertEqual(missing, [])

    def test_every_environment_variable_the_settings_read_is_documented(self):
        source = (PROJECT / 'config' / 'settings.py').read_text()
        names = set(re.findall(r"""['"]((?:DJANGO|DB)_[A-Z_]+)['"]""", source))
        self.assertGreaterEqual(len(names), 15)
        deployment = (PROJECT / 'docs' / 'DEPLOYMENT.md').read_text()
        example = (PROJECT / '.env.example').read_text()
        self.assertEqual([n for n in sorted(names) if n not in deployment], [])
        self.assertEqual([n for n in sorted(names) if n not in example and n not in ('DJANGO_ALLOWED_HOSTS',)], [])

    def test_helper_scripts_and_ci_are_consistent(self):
        script = PROJECT / 'tools' / 'run_postman.sh'
        self.assertTrue(script.stat().st_mode & 0o111, 'run_postman.sh must be executable')
        self.assertIn('SmartParking.postman_collection.json', script.read_text())
        ci = (PROJECT / '.github' / 'workflows' / 'ci.yml').read_text()
        for needle in ('manage.py test', 'build_docs.py --check', 'check --deploy', 'run_postman.sh', 'makemigrations --check'):
            self.assertIn(needle, ci)
        try:
            import yaml
        except ImportError:
            return
        self.assertIn('jobs', yaml.safe_load(ci))

    def test_requirements_files(self):
        base = (PROJECT / 'requirements.txt').read_text().lower()
        self.assertIn('django', base)
        self.assertIn('djangorestframework', base)
        self.assertNotIn('gunicorn', base)  # production extras live in requirements-prod.txt
