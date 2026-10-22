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

## Tests

```bash
python manage.py test
```

## Status

Phases 1-2 (foundation, authentication) complete. See the phase roadmap for upcoming work.
