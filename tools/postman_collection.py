"""Builds the Postman collection (v2.1) for the SmartPark API. Run via tools/build_docs.py."""
import json

BASE = '{{base_url}}'
USER = {'Authorization': 'Token {{user_token}}'}
ADMIN = {'Authorization': 'Token {{admin_token}}'}
OTHER = {'Authorization': 'Token {{other_token}}'}

TIMES = [  # pre-request script: booking window starting in 5 minutes (so check-in is allowed), or N days ahead
    "const start = new Date(Date.now() + {offset} * 60 * 1000); start.setSeconds(0, 0);",
    "const end = new Date(start.getTime() + {hours} * 3600 * 1000);",
    "pm.variables.set('start_iso', start.toISOString()); pm.variables.set('end_iso', end.toISOString());",
]


def times(minutes_ahead=5, hours=2):
    return [line.format(offset=minutes_ahead, hours=hours) for line in TIMES]


def status_test(code, *extra):
    lines = [f"pm.test('Status is {code}', () => pm.response.to.have.status({code}));"]
    if extra:
        lines.append('const j = pm.response.json();')
        lines.extend(extra)
    return lines


def expect(label, expr):
    return f"pm.test({json.dumps(label)}, () => {{ {expr} }});"


def req(name, method, path, *, headers=None, body=None, query=None, test=(), pre=(), description=''):
    headers = dict(headers or {})
    if body is not None:
        headers['Content-Type'] = 'application/json'
    qs = ''.join(('&' if i else '?') + f'{k}={v}' for i, (k, v) in enumerate(query or []))
    segments = [s for s in path.strip('/').split('/')]
    if path.endswith('/'):
        segments.append('')
    item = {
        'name': name,
        'request': {
            'method': method,
            'header': [{'key': k, 'value': v} for k, v in headers.items()],
            'url': {'raw': BASE + path + qs, 'host': [BASE], 'path': segments,
                    'query': [{'key': k, 'value': v} for k, v in (query or [])]},
            'description': description,
        },
        'event': [],
    }
    if body is not None:
        item['request']['body'] = {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}}
    if pre:
        item['event'].append({'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': list(pre)}})
    if test:
        item['event'].append({'listen': 'test', 'script': {'type': 'text/javascript', 'exec': list(test)}})
    return item


def set_var(name, expr):
    return f"pm.collectionVariables.set({json.dumps(name)}, {expr});"


def build():
    reg_body = ('{"username": "pm_user_{{run_id}}", "password": "{{user_password}}", "first_name": "Postman", '
                '"last_name": "Tester", "email": "pm_{{run_id}}@example.com", "phone": "9876543210"}')
    folders = []

    folders.append(('1. Authentication', [
        req('Register a new user', 'POST', '/api/auth/register/', body=reg_body,
            pre=["if (!pm.collectionVariables.get('run_id')) { pm.collectionVariables.set('run_id', String(Date.now()).slice(-8)); }"],
            test=status_test(201, expect('returns a token and the new user', "pm.expect(j.token).to.be.a('string'); pm.expect(j.user.role).to.eql('user');"),
                             expect('never returns the password', "pm.expect(JSON.stringify(j)).to.not.include(pm.collectionVariables.get('user_password'));"),
                             set_var('user_token', 'j.token')),
            description='Public. New accounts always get the `user` role.'),
        req('Register with a duplicate email (rejected)', 'POST', '/api/auth/register/',
            body='{"username": "dup_{{run_id}}", "password": "{{user_password}}", "first_name": "Dup", "email": "pm_{{run_id}}@example.com"}',
            test=status_test(400, expect('email error reported', "pm.expect(j.email).to.exist;"))),
        req('Login', 'POST', '/api/auth/login/', body='{"username": "pm_user_{{run_id}}", "password": "{{user_password}}"}',
            test=status_test(200, expect('token returned', "pm.expect(j.token).to.be.a('string');"), set_var('user_token', 'j.token'))),
        req('Login with a wrong password (rejected)', 'POST', '/api/auth/login/', body='{"username": "pm_user_{{run_id}}", "password": "wrong-password"}',
            test=status_test(400, expect('generic error, no hint which part was wrong', "pm.expect(j.non_field_errors[0]).to.eql('Invalid username or password.');"))),
        req('Get my profile', 'GET', '/api/auth/profile/', headers=USER,
            test=status_test(200, expect('is me', "pm.expect(j.username).to.eql('pm_user_' + pm.collectionVariables.get('run_id'));"))),
        req('Update my profile', 'PATCH', '/api/auth/profile/', headers=USER, body='{"phone": "9123456780", "last_name": "Updated"}',
            test=status_test(200, expect('changes saved', "pm.expect(j.phone).to.eql('9123456780'); pm.expect(j.last_name).to.eql('Updated');"))),
        req('Profile without a token (rejected)', 'GET', '/api/auth/profile/', test=status_test(401)),
        req('Login as the demo administrator', 'POST', '/api/auth/login/', body='{"username": "{{admin_username}}", "password": "{{admin_password}}"}',
            test=status_test(200, expect('has the admin role', "pm.expect(j.user.role).to.eql('admin');"), set_var('admin_token', 'j.token')),
            description='Needs the demo data: `python manage.py seed_demo`.'),
    ]))

    folders.append(('2. Browse parking (public)', [
        req('List locations that have free slots', 'GET', '/api/parking/locations/', query=[('available', '1')],
            test=status_test(200, expect('paginated and not empty', "pm.expect(j.count).to.be.above(0); pm.expect(j.results[0]).to.include.keys('id', 'name', 'hourly_rate', 'available_slots');"),
                             set_var('location_id', 'j.results[0].id'))),
        req('List free car slots at that location', 'GET', '/api/parking/slots/', query=[('location', '{{location_id}}'), ('status', 'available'), ('slot_type', 'car')],
            test=status_test(200, expect('at least one free car slot', "pm.expect(j.count).to.be.above(0);"), set_var('slot_id', 'j.results[0].id'))),
        req('Get the location', 'GET', '/api/parking/locations/{{location_id}}/', test=status_test(200, expect('same location', "pm.expect(j.id).to.eql(Number(pm.collectionVariables.get('location_id')));"))),
        req('Get the slot', 'GET', '/api/parking/slots/{{slot_id}}/', test=status_test(200, expect('is available', "pm.expect(j.status).to.eql('available');"))),
        req('Check the fee before booking', 'GET', '/api/payments/estimate/', query=[('slot', '{{slot_id}}'), ('start_time', '{{start_iso}}'), ('end_time', '{{end_iso}}')],
            pre=times(5, 2),
            test=status_test(200, expect('amount is a 2-decimal string for 2 billed hours', "pm.expect(j.amount).to.match(/^\\d+\\.\\d{2}$/); pm.expect(j.billing_blocks).to.eql(2);"),
                             set_var('estimate', 'j.amount')),
            description='Public. The server computes the charge: hourly rate x hours, rounded up, minimum 1 hour.'),
        req('A malformed id filter is a 400, not a 500', 'GET', '/api/parking/slots/', query=[('location', 'abc')],
            test=status_test(400, expect('names the parameter', "pm.expect(j.location).to.exist;"))),
    ]))

    folders.append(('3. Parking administration (admin only)', [
        req('A normal user cannot create a location', 'POST', '/api/parking/locations/', headers=USER,
            body='{"name": "Nope", "address": "x", "city": "x", "hourly_rate": "10.00"}', test=status_test(403)),
        req('Create a location', 'POST', '/api/parking/locations/', headers=ADMIN,
            body='{"name": "Postman Lot {{run_id}}", "address": "1 Test Road", "city": "Nashik", "description": "Created by the Postman run", "opening_time": "06:00:00", "closing_time": "22:00:00", "hourly_rate": "25.00"}',
            test=status_test(201, expect('created with no slots yet', "pm.expect(j.total_slots).to.eql(0);"), set_var('new_location_id', 'j.id'))),
        req('Update the location', 'PATCH', '/api/parking/locations/{{new_location_id}}/', headers=ADMIN, body='{"hourly_rate": "35.00"}',
            test=status_test(200, expect('rate changed', "pm.expect(j.hourly_rate).to.eql('35.00');"))),
        req('Create a slot', 'POST', '/api/parking/slots/', headers=ADMIN, body='{"location": {{new_location_id}}, "slot_number": "pm1", "slot_type": "car"}',
            test=status_test(201, expect('slot number is normalised to upper case', "pm.expect(j.slot_number).to.eql('PM1');"), set_var('new_slot_id', 'j.id'))),
        req('A duplicate slot number is rejected', 'POST', '/api/parking/slots/', headers=ADMIN, body='{"location": {{new_location_id}}, "slot_number": "PM1"}',
            test=status_test(400, expect('explains why', "pm.expect(JSON.stringify(j)).to.include('already exists');"))),
        req('Mark the slot unavailable', 'PATCH', '/api/parking/slots/{{new_slot_id}}/', headers=ADMIN, body='{"status": "unavailable"}',
            test=status_test(200, expect('status changed', "pm.expect(j.status).to.eql('unavailable');"))),
        req('Delete the slot', 'DELETE', '/api/parking/slots/{{new_slot_id}}/', headers=ADMIN, test=status_test(204)),
        req('Delete the location', 'DELETE', '/api/parking/locations/{{new_location_id}}/', headers=ADMIN, test=status_test(204)),
    ]))

    folders.append(('4. Vehicles and bookings', [
        req('Save a vehicle', 'POST', '/api/bookings/vehicles/', headers=USER, body='{"plate_number": "pm {{run_id}}", "vehicle_type": "car", "model_name": "Test car"}',
            test=status_test(201, expect('plate is normalised', "pm.expect(j.plate_number).to.eql('PM' + pm.collectionVariables.get('run_id'));"), set_var('vehicle_id', 'j.id'))),
        req('List my vehicles', 'GET', '/api/bookings/vehicles/', headers=USER, test=status_test(200, expect('has one', "pm.expect(j.count).to.eql(1);"))),
        req('Get a vehicle', 'GET', '/api/bookings/vehicles/{{vehicle_id}}/', headers=USER, test=status_test(200)),
        req('Book the slot (starts in 5 minutes, 2 hours)', 'POST', '/api/bookings/', headers=USER,
            body='{"slot": {{slot_id}}, "start_time": "{{start_iso}}", "end_time": "{{end_iso}}", "vehicle": {{vehicle_id}}}', pre=times(5, 2),
            test=status_test(201, expect('confirmed with a reference', "pm.expect(j.status).to.eql('confirmed'); pm.expect(j.reference).to.match(/^PK-[0-9A-F]{8}$/);"),
                             expect('payment starts pending', "pm.expect(j.payment.status).to.eql('pending');"),
                             expect('charge matches the estimate', "pm.expect(j.payment.amount).to.eql(pm.collectionVariables.get('estimate'));"),
                             set_var('booking_ref', 'j.reference'), set_var('payment_id', 'j.payment.id'))),
        req('Booking the same slot and time again is refused', 'POST', '/api/bookings/', headers=USER,
            body='{"slot": {{slot_id}}, "start_time": "{{start_iso}}", "end_time": "{{end_iso}}", "plate_number": "PX{{run_id}}", "vehicle_type": "car"}',
            test=status_test(400, expect('no double booking', "pm.expect(JSON.stringify(j.detail)).to.include('already booked');"))),
        req('A booking in the past is refused', 'POST', '/api/bookings/', headers=USER,
            body='{"slot": {{slot_id}}, "start_time": "2020-01-01T10:00:00Z", "end_time": "2020-01-01T12:00:00Z", "vehicle": {{vehicle_id}}}',
            test=status_test(400, expect('explains', "pm.expect(JSON.stringify(j.detail)).to.include('future');"))),
        req('List my bookings', 'GET', '/api/bookings/', headers=USER, test=status_test(200, expect('contains it', "pm.expect(j.results.map(b => b.reference)).to.include(pm.collectionVariables.get('booking_ref'));"))),
        req('Filter bookings by status', 'GET', '/api/bookings/', headers=USER, query=[('status', 'confirmed')], test=status_test(200, expect('only confirmed', "j.results.forEach(b => pm.expect(b.status).to.eql('confirmed'));"))),
        req('Get the booking', 'GET', '/api/bookings/{{booking_ref}}/', headers=USER,
            test=status_test(200, expect('can check in now', "pm.expect(j.can_check_in).to.eql(true); pm.expect(j.can_check_out).to.eql(false);"))),
        req('A vehicle with bookings cannot be deleted', 'DELETE', '/api/bookings/vehicles/{{vehicle_id}}/', headers=USER, test=status_test(409)),
    ]))

    folders.append(('5. Payments (simulated)', [
        req('List my payments', 'GET', '/api/payments/', headers=USER, test=status_test(200, expect('includes this booking', "pm.expect(j.results[0].booking).to.eql(pm.collectionVariables.get('booking_ref'));"))),
        req('Get the payment', 'GET', '/api/payments/{{payment_id}}/', headers=USER,
            test=status_test(200, expect('nothing paid yet', "pm.expect(j.amount_due).to.eql(j.amount); pm.expect(j.is_simulated).to.eql(true);"))),
        req('Pay - simulated failure', 'POST', '/api/payments/{{payment_id}}/pay/', headers=USER, body='{"method": "card", "outcome": "fail"}',
            test=status_test(200, expect('a failed attempt is a normal response with status "failed"', "pm.expect(j.status).to.eql('failed'); pm.expect(j.amount_paid).to.eql('0.00');"))),
        req('Pay - simulated success (retry)', 'POST', '/api/payments/{{payment_id}}/pay/', headers=USER, body='{"method": "upi"}',
            test=status_test(200, expect('paid in full', "pm.expect(j.status).to.eql('paid'); pm.expect(j.amount_due).to.eql('0.00'); pm.expect(j.transaction_id).to.match(/^SIM-/);"))),
        req('Paying again is refused', 'POST', '/api/payments/{{payment_id}}/pay/', headers=USER, body='{"method": "upi"}', test=status_test(400)),
    ]))

    folders.append(('6. Check-in and check-out', [
        req('Check in', 'POST', '/api/bookings/{{booking_ref}}/check-in/', headers=USER, test=status_test(200, expect('checked in', "pm.expect(j.status).to.eql('checked_in'); pm.expect(j.checked_in_at).to.be.a('string');"))),
        req('The slot is now occupied', 'GET', '/api/parking/slots/{{slot_id}}/', test=status_test(200, expect('occupied', "pm.expect(j.status).to.eql('occupied');"))),
        req('Check out', 'POST', '/api/bookings/{{booking_ref}}/check-out/', headers=USER,
            test=status_test(200, expect('completed and fully paid', "pm.expect(j.status).to.eql('completed'); pm.expect(j.payment.amount_due).to.eql('0.00');"))),
        req('The slot is free again', 'GET', '/api/parking/slots/{{slot_id}}/', test=status_test(200, expect('available', "pm.expect(j.status).to.eql('available');"))),
        req('Checking in a completed booking is refused', 'POST', '/api/bookings/{{booking_ref}}/check-in/', headers=USER, test=status_test(400)),
    ]))

    folders.append(('7. Cancellation and refund', [
        req('Book again, 2 days ahead', 'POST', '/api/bookings/', headers=USER,
            body='{"slot": {{slot_id}}, "start_time": "{{start_iso}}", "end_time": "{{end_iso}}", "vehicle": {{vehicle_id}}}', pre=times(2 * 24 * 60, 1),
            test=status_test(201, set_var('booking2_ref', 'j.reference'), set_var('payment2_id', 'j.payment.id'))),
        req('Pay for it', 'POST', '/api/payments/{{payment2_id}}/pay/', headers=USER, body='{"method": "wallet"}', test=status_test(200, expect('paid', "pm.expect(j.status).to.eql('paid');"))),
        req('Cancel it', 'POST', '/api/bookings/{{booking2_ref}}/cancel/', headers=USER,
            test=status_test(200, expect('cancelled and refunded', "pm.expect(j.status).to.eql('cancelled'); pm.expect(j.payment.status).to.eql('refunded');"))),
        req('Cancelling twice is refused', 'POST', '/api/bookings/{{booking2_ref}}/cancel/', headers=USER, test=status_test(400)),
    ]))

    folders.append(('8. Administrator', [
        req('Dashboard summary', 'GET', '/api/dashboard/summary/', headers=ADMIN, query=[('days', '14')],
            test=status_test(200, expect('totals present, money as strings', "pm.expect(j.cards.bookings_total).to.be.at.least(2); pm.expect(j.cards.revenue_total).to.match(/^\\d+\\.\\d{2}$/);"),
                             expect('chart data included', "pm.expect(j.charts.daily.labels.length).to.eql(14);"))),
        req('A normal user cannot see the summary', 'GET', '/api/dashboard/summary/', headers=USER, test=status_test(403)),
        req('List all bookings (admin sees everyone)', 'GET', '/api/bookings/', headers=ADMIN, test=status_test(200, expect('includes the test user\'s bookings', "pm.expect(j.count).to.be.at.least(2);"))),
        req('User books for 3 days ahead', 'POST', '/api/bookings/', headers=USER,
            body='{"slot": {{slot_id}}, "start_time": "{{start_iso}}", "end_time": "{{end_iso}}", "vehicle": {{vehicle_id}}}', pre=times(3 * 24 * 60, 1),
            test=status_test(201, set_var('booking3_ref', 'j.reference'), set_var('payment3_id', 'j.payment.id'))),
        req('Admin marks the payment as paid (cash)', 'PATCH', '/api/payments/{{payment3_id}}/status/', headers=ADMIN, body='{"status": "paid", "note": "Cash at gate"}',
            test=status_test(200, expect('paid manually', "pm.expect(j.status).to.eql('paid'); pm.expect(j.transaction_id).to.match(/^MAN-/);"))),
        req('An invalid payment transition is refused', 'PATCH', '/api/payments/{{payment3_id}}/status/', headers=ADMIN, body='{"status": "pending"}', test=status_test(400)),
        req('A normal user cannot change payment status', 'PATCH', '/api/payments/{{payment3_id}}/status/', headers=USER, body='{"status": "refunded"}', test=status_test(403)),
        req('Admin cancels the booking', 'PATCH', '/api/bookings/{{booking3_ref}}/status/', headers=ADMIN, body='{"status": "cancelled"}',
            test=status_test(200, expect('cancelled and the paid amount refunded', "pm.expect(j.status).to.eql('cancelled'); pm.expect(j.payment.status).to.eql('refunded');"))),
        req('A normal user cannot change booking status', 'PATCH', '/api/bookings/{{booking_ref}}/status/', headers=USER, body='{"status": "cancelled"}', test=status_test(403)),
    ]))

    folders.append(('9. Security checks', [
        req('Register a second user', 'POST', '/api/auth/register/',
            body='{"username": "pm_other_{{run_id}}", "password": "{{user_password}}", "first_name": "Other", "email": "pm_other_{{run_id}}@example.com"}',
            test=status_test(201, set_var('other_token', 'j.token'))),
        req('Another user cannot read my booking', 'GET', '/api/bookings/{{booking_ref}}/', headers=OTHER, test=status_test(404)),
        req('Another user cannot pay my payment', 'POST', '/api/payments/{{payment_id}}/pay/', headers=OTHER, body='{"method": "card"}', test=status_test(404)),
        req('Another user cannot cancel my booking', 'POST', '/api/bookings/{{booking_ref}}/cancel/', headers=OTHER, test=status_test(404)),
        req('Another user sees an empty booking list', 'GET', '/api/bookings/', headers=OTHER, test=status_test(200, expect('nothing of mine leaks', "pm.expect(j.count).to.eql(0);"))),
        req('No token: rejected', 'GET', '/api/bookings/', test=status_test(401)),
        req('Invalid token: rejected', 'GET', '/api/bookings/', headers={'Authorization': 'Token 0000000000000000000000000000000000000000'}, test=status_test(401)),
    ]))

    folders.append(('10. Sign out', [
        req('Log out (revokes the token)', 'POST', '/api/auth/logout/', headers=USER, test=status_test(204)),
        req('The revoked token no longer works', 'GET', '/api/auth/profile/', headers=USER, test=status_test(401)),
    ]))

    return {
        'info': {'name': 'SmartPark - Smart Parking Management API',
                 'description': 'Full workflow test of the REST API. Run the folders in order (Collection Runner or `newman run`). '
                                'Needs the demo data (`python manage.py seed_demo`) for the administrator login. '
                                'Run against a development or test database: each run creates a new test user and a few bookings.',
                 'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'},
        'item': [{'name': n, 'item': items} for n, items in folders],
        'variable': [{'key': 'user_password', 'value': 'Pm-Test-Pass-2026'}],
    }


def environment():
    return {'id': 'smartpark-local', 'name': 'SmartPark local', '_postman_variable_scope': 'environment',
            'values': [{'key': 'base_url', 'value': 'http://127.0.0.1:8000', 'enabled': True},
                       {'key': 'admin_username', 'value': 'admin_demo', 'enabled': True},
                       {'key': 'admin_password', 'value': 'DemoAdmin#2026', 'enabled': True}]}
