#!/usr/bin/env python
"""Regenerate the generated documentation.

    python tools/build_docs.py          # rewrite docs/API.md, docs/DATABASE.md and docs/postman/*
    python tools/build_docs.py --check  # exit 1 if any of those files is out of date (used by the tests)

Example responses in API.md are captured from the real code in a throw-away database with the clock frozen,
so the output is deterministic and cannot drift from the implementation.
"""
import json
import os
import re
import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DJANGO_DEBUG'] = 'True'  # the builder never runs in production mode

import django  # noqa: E402

django.setup()

import api_docs_text  # noqa: E402
import postman_collection  # noqa: E402

FIXED = datetime(2026, 11, 2, 9, 30, tzinfo=ZoneInfo('Asia/Kolkata'))


def scrub(text):
    text = re.sub(r'\b[0-9a-f]{40}\b', '9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b', text)
    text = re.sub(r'PK-[0-9A-F]{8}', 'PK-1A2B3C4D', text)
    return re.sub(r'SIM-[0-9A-F]{16}', 'SIM-0123456789ABCDEF', text)


def block(obj):
    return '\n```json\n' + scrub(json.dumps(obj, indent=2, ensure_ascii=False)) + '\n```\n'


def capture_examples():
    from django.contrib.auth import get_user_model
    from django.test import Client
    from apps.parking.models import ParkingLocation, ParkingSlot

    User = get_user_model()
    ex = {}
    with mock.patch('django.utils.timezone.now', return_value=FIXED):
        admin = User.objects.create_user('admin_demo', 'admin@example.com', 'x')
        admin.profile.role = 'admin'
        admin.profile.save()
        loc = ParkingLocation.objects.create(name='City Centre Parking', address='MG Road, near the market', city='Nashik',
                                             description='Covered parking next to the main market.', hourly_rate=Decimal('30.00'),
                                             opening_time=time(0, 0), closing_time=time(23, 59))
        for number in ('A-1', 'A-2', 'A-3'):
            ParkingSlot.objects.create(location=loc, slot_number=number)
        ParkingSlot.objects.create(location=loc, slot_number='E-1', slot_type='ev')
        c = Client()
        post = lambda url, body, **kw: c.post(url, json.dumps(body), content_type='application/json', **kw)

        ex['register_error'] = post('/api/auth/register/', {'username': 'asha', 'password': '123', 'email': 'not-an-email'}).json()
        reg = post('/api/auth/register/', {'username': 'asha', 'password': 'Str0ng-Pass-993', 'first_name': 'Asha', 'last_name': 'Kulkarni',
                                           'email': 'asha@example.com', 'phone': '9876543210'}).json()
        ex['register'] = reg
        auth = {'HTTP_AUTHORIZATION': f"Token {reg['token']}"}

        listing = c.get('/api/parking/locations/', {'available': '1'}).json()
        ex['locations'] = listing
        slots = c.get('/api/parking/slots/', {'location': loc.pk, 'status': 'available', 'slot_type': 'car'}).json()
        slots['results'] = slots['results'][:1]
        ex['slot'] = slots
        ex['vehicle'] = post('/api/bookings/vehicles/', {'plate_number': 'mh 15 ab 1234', 'vehicle_type': 'car', 'model_name': 'Hatchback'}, **auth).json()

        start = datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo('Asia/Kolkata'))
        end = datetime(2026, 11, 3, 12, 0, tzinfo=ZoneInfo('Asia/Kolkata'))
        slot = ParkingSlot.objects.get(slot_number='A-1')
        ex['estimate'] = c.get('/api/payments/estimate/', {'slot': slot.pk, 'start_time': start.isoformat(), 'end_time': end.isoformat()}).json()
        body = {'slot': slot.pk, 'start_time': start.isoformat(), 'end_time': end.isoformat(), 'vehicle': ex['vehicle']['id']}
        booking = post('/api/bookings/', body, **auth).json()
        ex['booking'] = booking
        overlap = {k: v for k, v in body.items() if k != 'vehicle'}
        ex['booking_error'] = post('/api/bookings/', {**overlap, 'plate_number': 'KA01XY9999', 'vehicle_type': 'car'}, **auth).json()
        ex['payment'] = post(f"/api/payments/{booking['payment']['id']}/pay/", {'method': 'upi'}, **auth).json()

        admin_token = post('/api/auth/login/', {'username': 'admin_demo', 'password': 'x'}).json()['token']
        s = c.get('/api/dashboard/summary/', {'days': 7}, HTTP_AUTHORIZATION=f'Token {admin_token}').json()
        daily = s['charts']['daily']
        ex['summary'] = {'days': s['days'], 'cards': s['cards'], 'locations': s['locations'][:1],
                         'charts': {'slot_status': s['charts']['slot_status'], 'booking_status': s['charts']['booking_status'],
                                    'daily': {k: v[:3] for k, v in daily.items()}, '...': 'daily arrays shortened here; also "locations"'}}
    return ex


def build_api_md(ex):
    text = api_docs_text.TEXT
    for name, value in ex.items():
        text = text.replace(f'@@{name}@@', block(value))
    leftover = re.findall(r'@@\w+@@', text)
    assert not leftover, f'unfilled placeholders: {leftover}'
    return text


DB_INTRO = '''# Database schema

Generated from the Django models (`python tools/build_docs.py`). The application uses Django's ORM, so the schema is created by the
migrations in each app (`python manage.py migrate`); there is no hand-written SQL.

**Engines.** SQLite is the default and the engine the whole test suite and every delivery check ran on. MySQL 8.0.16 or newer is supported by
configuration (`DB_ENGINE=mysql`, see the deployment guide) but was **not** tested here. On MySQL the server needs the time-zone tables loaded
(`mysql_tzinfo_to_sql`), otherwise the dashboard's per-day charts come back empty.

## Entity relationship diagram

```mermaid
erDiagram
    USER ||--|| PROFILE : "has (role, phone)"
    USER ||--o| TOKEN : "may have (API login)"
    USER ||--o{ VEHICLE : owns
    USER ||--o{ BOOKING : makes
    PARKING_LOCATION ||--o{ PARKING_SLOT : contains
    PARKING_SLOT ||--o{ BOOKING : "is reserved by"
    VEHICLE ||--o{ BOOKING : "is used in"
    BOOKING ||--|| PAYMENT : "is billed by"
```

## The assignment's tables

| Assignment | Table here | Notes |
|---|---|---|
| Users | `auth_user` + `accounts_profile` | Django's user table for credentials; the profile adds the role (`user`/`admin`) and phone |
| Parking_Locations | `parking_parkinglocation` | Includes the hourly rate and opening hours |
| Parking_Slots | `parking_parkingslot` | Type (car, bike, ev, accessible) and status (available, occupied, unavailable) |
| Parking_Bookings | `bookings_booking` | Time window, status, rate snapshot, check-in/out times |
| Vehicles | `bookings_vehicle` | Owned by one user; plate numbers are unique per user |
| Payments | `payments_payment` | One per booking; amount, amount paid, status, simulated transaction id |
| (extra) | `authtoken_token` | API login tokens |

## Design notes

- **Money** is stored as `DECIMAL`, never floating point. A booking keeps a **snapshot of the hourly rate** (`bookings_booking.hourly_rate`) so changing a location's rate never changes an existing booking.
- **History is protected.** Bookings point to users, slots and vehicles with `PROTECT`, so anything that has bookings cannot be deleted (use `is_active` / `unavailable` instead). A payment cannot be deleted while its booking exists either.
- **Integrity is enforced in the database where possible:** unique `(location, slot_number)`, unique `(user, plate_number)`, unique booking reference, unique transaction id, `end_time > start_time`, and non-negative payment amounts (check constraints).
- **SQLite settings.** SQLite allows one writer at a time. The project starts every SQLite transaction in `IMMEDIATE` mode with a 20-second wait (`config/settings.py`), so simultaneous bookings or payments queue up instead of failing with "database is locked". That is plenty for a demo or modest traffic; for heavy write traffic use MySQL.
- **No double bookings.** Overlap between two bookings of the same slot cannot be expressed as a portable constraint, so it is checked in `apps/bookings/services.py` inside a transaction that locks the slot row (`SELECT ... FOR UPDATE` on MySQL/PostgreSQL; SQLite serialises writers). A threaded test (`apps/core/test_workflows.py`) books one slot from 8 threads at once and asserts exactly one wins.
- **Slot status vs. bookings.** `parking_parkingslot.status` is the slot's state *right now* (it changes at check-in/check-out and when an admin marks maintenance). Availability for a future period comes from the bookings table.
- **Indexes:** every foreign key, plus `(slot, start_time, end_time)` on bookings for the overlap query.

## Tables
'''


def column_type(field):
    t = field.get_internal_type()
    if t in ('CharField', 'SlugField'):
        return f'varchar({field.max_length})'
    if t == 'DecimalField':
        return f'decimal({field.max_digits},{field.decimal_places})'
    if field.is_relation:
        return 'bigint'
    return {'BigAutoField': 'bigint (auto)', 'AutoField': 'integer (auto)', 'TextField': 'text', 'BooleanField': 'boolean', 'DateTimeField': 'datetime',
            'TimeField': 'time', 'DateField': 'date', 'EmailField': 'varchar(254)', 'IntegerField': 'integer'}.get(t, t.lower())


OPERATORS = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'exact': '='}


def condition_text(q):
    """Readable form of a simple check-constraint condition, e.g. `end_time > start_time`."""
    parts = []
    for child in q.children:
        lookup, value = child
        field, _, op = lookup.rpartition('__')
        value = getattr(value, 'name', value)
        parts.append(f'{field} {OPERATORS.get(op, op)} {value}')
    return f' {q.connector} '.join(parts)


def build_database_md():
    from django.apps import apps
    from django.db.models import NOT_PROVIDED
    wanted = [('auth', 'user'), ('accounts', 'profile'), ('authtoken', 'token'), ('parking', 'parkinglocation'), ('parking', 'parkingslot'),
              ('bookings', 'vehicle'), ('bookings', 'booking'), ('payments', 'payment')]
    out = [DB_INTRO]
    for app, name in wanted:
        model = apps.get_model(app, name)
        out.append(f'\n### `{model._meta.db_table}`\n')
        doc = (model.__doc__ or '').strip()
        if doc and not doc.startswith(model.__name__ + '('):
            out.append(doc.split('\n')[0] + '\n')
        out.append('| Column | Type | Null | Notes |\n|---|---|---|---|')
        for f in model._meta.concrete_fields:
            notes = []
            if f.primary_key:
                notes.append('primary key')
            elif f.unique:
                notes.append('unique')
            if f.is_relation:
                notes.append(f'-> `{f.related_model._meta.db_table}` ({"one-to-one" if f.one_to_one else "many-to-one"}, on delete {f.remote_field.on_delete.__name__})')
            if f.choices:
                notes.append('one of: ' + ', '.join(f'`{v}`' for v, _ in f.choices))
            if f.has_default() and f.default is not NOT_PROVIDED and not f.primary_key:
                d = f.default
                notes.append('default ' + (f'`{d.__name__}()`' if callable(d) else f'`{d}`'))
            if getattr(f, 'auto_now_add', False):
                notes.append('set on creation')
            if getattr(f, 'auto_now', False):
                notes.append('updated on every save')
            out.append(f'| `{f.column}` | {column_type(f)} | {"yes" if f.null else "no"} | {"; ".join(notes)} |')
        extra = []
        for c in model._meta.constraints:
            kind = 'unique' if c.__class__.__name__ == 'UniqueConstraint' else 'check'
            detail = ', '.join(c.fields) if kind == 'unique' else condition_text(c.condition)
            extra.append(f'- {kind} constraint `{c.name}`: {detail}')
        for i in model._meta.indexes:
            extra.append(f'- index on ({", ".join(i.fields)})')
        if extra:
            out.append('\n' + '\n'.join(extra))
    return '\n'.join(out) + '\n'


def generated_files():
    from django.test.runner import DiscoverRunner
    from django.test.utils import setup_test_environment, teardown_test_environment
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old = runner.setup_databases()
    try:
        examples = capture_examples()
        files = {'docs/API.md': build_api_md(examples), 'docs/DATABASE.md': build_database_md()}
    finally:
        runner.teardown_databases(old)
        teardown_test_environment()
    files['docs/postman/SmartParking.postman_collection.json'] = json.dumps(postman_collection.build(), indent=2) + '\n'
    files['docs/postman/SmartParking.postman_environment.json'] = json.dumps(postman_collection.environment(), indent=2) + '\n'
    return files


def main(argv):
    files = generated_files()
    stale = [p for p, content in files.items() if not (ROOT / p).is_file() or (ROOT / p).read_text() != content]
    if '--check' in argv:
        if stale:
            print('Out of date (run: python tools/build_docs.py):', ', '.join(stale))
            return 1
        print('Generated documentation is up to date.')
        return 0
    for path, content in files.items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    print('Wrote:', ', '.join(files))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
