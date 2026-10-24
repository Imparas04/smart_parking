"""Simultaneous bookings against the real deployment database: a SQLite *file* (not the in-memory test database)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PROJECT = Path(settings.BASE_DIR)
PROBE = PROJECT / 'apps' / 'core' / 'concurrency_probe.py'


def run_probe(threads):
    with tempfile.TemporaryDirectory() as folder:
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        env['DJANGO_SQLITE_PATH'] = str(Path(folder) / 'race.sqlite3')
        r = subprocess.run([sys.executable, str(PROBE), str(threads)], cwd=str(PROJECT), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


class FileDatabaseConcurrencyTests(SimpleTestCase):
    def test_one_booking_wins_and_every_other_request_is_refused_cleanly(self):
        """Without SQLite's IMMEDIATE transaction mode the losers crash with 'database is locked' (a 500 page for real users)."""
        for _ in range(2):
            result = run_probe(8)
            self.assertEqual(result['outcomes'], ['booked'] + ['refused'] * 7, result)
            self.assertEqual(result['bookings'], 1)

    def test_sqlite_waits_for_the_write_lock_instead_of_failing(self):
        db = settings.DATABASES['default']
        if 'sqlite' not in db['ENGINE']:
            self.skipTest('SQLite-specific setting')
        self.assertEqual(db['OPTIONS']['transaction_mode'], 'IMMEDIATE')
        self.assertGreaterEqual(db['OPTIONS']['timeout'], 10)
