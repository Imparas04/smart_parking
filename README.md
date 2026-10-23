# Smart Parking Management System

Django-based web app for finding, booking and managing parking slots.
Stack: Python, Django, Django REST Framework, Django Templates, HTML/CSS/JavaScript.

## Setup

```bash
python -m venv venv
# Windows: venv\Scripts\activate    |  macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional; defaults work for local development
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/

## Configuration

Settings are read from environment variables (see `.env.example`).
SQLite is the default database. For MySQL set `DB_ENGINE=mysql`, the `DB_*` values, and `pip install mysqlclient`.

## Project layout

- `config/` project settings and root URLs
- `apps/core` home page and shared context
- `apps/accounts`, `apps/parking`, `apps/bookings`, `apps/payments`, `apps/dashboard` feature apps (filled in later phases)
- `templates/` base layout and partials, `static/` CSS and JS, `media/` uploads

## Authentication and roles

- Pages: `/accounts/register/`, `/accounts/login/`, `/accounts/profile/`, `/accounts/password/`; logout is a POST form.
- Roles live on `Profile.role` (`user` or `admin`). Registration always creates `user`. Superusers are admin automatically; promote others in Django admin (Users > Profile inline).
- Admin-only pages use `@admin_required`; APIs use `IsAdminRole`. `/dashboard/` is admin-only.
- REST API (token auth, send header `Authorization: Token <key>`):
  - `POST /api/auth/register/` `{username, password, first_name, last_name, email, phone}`
  - `POST /api/auth/login/` `{username, password}`
  - `POST /api/auth/logout/`
  - `GET|PATCH /api/auth/profile/`

## Parking locations and slots

- Public pages: `/parking/` (search by name/address/city, city, slot type and "has free slots" filters), `/parking/<id>/` (colour-coded slot grid), `/parking/slots/<id>/`.
- Admin pages (admin role only): add/edit/delete locations and slots, plus bulk slot creation, from the same pages (buttons appear for admins). Django admin also works.
- Slot status is set by admins for now (available, occupied, unavailable). Later phases update it automatically from bookings and check-in/out.
- Hourly rate is stored per location and used for pricing in Phase 5. Currency is shown as INR.
- Demo data: `python manage.py seed_parking` (safe to run repeatedly).
- API (read: anyone, write: admin role): `/api/parking/locations/` (`?search=&city=&available=1`) and `/api/parking/slots/` (`?location=&status=&slot_type=`); paginated, 20 per page.

## Bookings

- Pages (login required): `/bookings/` (history with status filters), `/bookings/book/<slot_id>/`, `/bookings/<reference>/` (confirmation and cancel). Users only ever see their own bookings.
- Rules (change in `config/settings.py`): minimum 30 minutes, maximum 24 hours, up to 30 days ahead, cancellation allowed until 60 minutes before start.
- Double-booking protection: `apps/bookings/services.py` locks the slot row (`select_for_update`) inside a transaction and rejects overlapping confirmed/checked-in bookings (back-to-back is allowed). The same vehicle cannot overlap itself. SQLite serialises writers at database level; row locking applies on MySQL/PostgreSQL.
- Slots marked `unavailable` or in inactive locations cannot be booked. `occupied` slots can still be booked for a later time.
- Locations, slots, vehicles and users that have bookings cannot be deleted (use inactive/unavailable instead).
- API (login required; token or session): `POST/GET /api/bookings/` (`?status=&slot=&location=`), `GET /api/bookings/<reference>/`, `POST /api/bookings/<reference>/cancel/`, `GET/POST/DELETE /api/bookings/vehicles/`. Admins can read all bookings.

## Pricing, payments, check-in/out

- **Pricing** (`apps/payments/pricing.py`, always computed on the server): hourly rate x hours, rounded up, minimum 1 hour (`BILLING_BLOCK_MINUTES` in settings). The rate is snapshotted on the booking, so later rate changes do not alter existing bookings. Leaving early does not reduce the charge; staying past the end time is billed for the actual time at check-out.
- **Fee check**: the booking form shows a live estimate from `GET /api/payments/estimate/?slot=&start_time=&end_time=`.
- **Payments are SIMULATED.** No payment gateway is configured and no real money moves; the pay page says so. Statuses: pending, paid, failed, refunded, cancelled. The "payment fails" option exists to test the failure path. Cancelling a paid booking records a simulated refund; cancelling an unpaid one cancels the payment. With `PAYMENTS_SIMULATED = False` the pay endpoint refuses until a real gateway is integrated.
- **Check-in / check-out**: check-in opens 15 minutes before the start and until the end time, marks the slot occupied; check-out completes the booking and frees the slot. An overstay on an already-paid booking leaves a balance due. Check-out is never blocked by an unpaid balance.
- **No-shows**: run `python manage.py expire_bookings` periodically (cron). Confirmed bookings that ended unused become `no_show` and are not charged.
- **API**: `GET /api/payments/` (`?status=&booking=`), `GET /api/payments/<id>/`, `POST /api/payments/<id>/pay/` `{method: card|upi|wallet, outcome: success|fail}` (a simulated failure still returns 200; check `status`), `PATCH /api/payments/<id>/status/` (admin: `{status, note}`; allowed: pending->paid/failed/cancelled, failed->pending/paid/cancelled, paid->refunded), `POST /api/bookings/<reference>/check-in/` and `/check-out/` (owner or admin).

## Tests

```bash
python manage.py test
```

## Status

Phases 1-5 (foundation, authentication, locations and slots, bookings, pricing/payments/check-in) complete. See the phase roadmap for upcoming work.
