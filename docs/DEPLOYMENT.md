# Deployment guide

**What has been verified.** A production-mode server (`DJANGO_DEBUG=False`) running under **gunicorn with WhiteNoise** on SQLite, behind a simulated
HTTPS proxy header: HTTP redirects to HTTPS, hashed and gzip-compressed static files, secure cookies, HSTS, custom error pages, and every page
and admin screen returning 200 with no errors logged. **What has not:** deployment to a real host or provider, and MySQL (see [DATABASE.md](DATABASE.md)).
The steps below are the standard way to run this kind of application; adjust them to your host.

## 1. Requirements

- Python 3.12 (the version everything was tested on) and `pip`.
- A database: SQLite (default; fine for a demo or modest traffic: writers take turns, see [DATABASE.md](DATABASE.md)) or MySQL 8.0.16+ for heavier use.
- HTTPS in front of the app: a reverse proxy (nginx, Caddy) or a platform that provides TLS.

## 2. Configuration

Settings come from environment variables or a `.env` file in the project root (loaded automatically; real environment variables win).
Never commit `.env`. `.env.example` is the template.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | development key | **Required when debug is off**: a random 50+ character value, otherwise the app refuses to start. Generate: `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `DJANGO_DEBUG` | `True` | **Set to `False` in production.** (It defaults to `True` for local development, so it must be switched off explicitly.) |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names the site answers to |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated origins such as `https://parking.example.com` (needed behind a proxy/HTTPS) |
| `DJANGO_BEHIND_PROXY` | `False` | `True` when a reverse proxy terminates HTTPS and sends `X-Forwarded-Proto` |
| `DJANGO_TRUSTED_PROXY_COUNT` | `0` | Number of proxies in front (usually `1`). Used to find the real client IP for login throttling; `X-Forwarded-For` is ignored when `0` |
| `DJANGO_SSL_REDIRECT` | `True` (debug off) | Redirect HTTP to HTTPS |
| `DJANGO_HSTS_SECONDS` | `3600` (debug off) | HSTS lifetime; raise it (for example `31536000`) once HTTPS works everywhere |
| `DJANGO_HSTS_INCLUDE_SUBDOMAINS` | `False` | Only enable if every subdomain also serves HTTPS |
| `DJANGO_AUTH_THROTTLE` | `20/min` | Rate limit for API login/register per client IP |
| `DJANGO_CSP_REPORT_ONLY` | `False` | `True` reports Content-Security-Policy violations without blocking (useful when first deploying) |
| `DB_ENGINE` | `sqlite` | `sqlite` or `mysql` |
| `DJANGO_SQLITE_PATH` | `./db.sqlite3` | Location of the SQLite file (put it on persistent storage) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `smart_parking`, `root`, empty, `127.0.0.1`, `3306` | MySQL connection |

## 3. Steps on a Linux server

```bash
# as an unprivileged user, in the project directory (for example /srv/smartpark)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-prod.txt

cp .env.example .env && nano .env       # set DJANGO_SECRET_KEY, DJANGO_DEBUG=False, DJANGO_ALLOWED_HOSTS, ...

python manage.py check --deploy         # expect only the two HSTS notices (include-subdomains, preload)
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py createsuperuser        # a superuser automatically gets the admin role in the app
```

Run the application with gunicorn, for example as a systemd service (`/etc/systemd/system/smartpark.service`):

```ini
[Unit]
Description=SmartPark (gunicorn)
After=network.target

[Service]
User=smartpark
WorkingDirectory=/srv/smartpark
ExecStart=/srv/smartpark/venv/bin/gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3 --access-logfile -
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

and put nginx in front for HTTPS (certificates from Let's Encrypt/certbot). Static files are served by WhiteNoise inside the app, so nginx needs no static configuration:

```nginx
server {
    listen 80;
    server_name parking.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name parking.example.com;
    # ssl_certificate / ssl_certificate_key: managed by certbot
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

With that nginx, set `DJANGO_BEHIND_PROXY=True`, `DJANGO_TRUSTED_PROXY_COUNT=1` and `DJANGO_CSRF_TRUSTED_ORIGINS=https://parking.example.com`.

## 4. Platform-as-a-service (Render, Railway, Heroku-style)

A `Procfile` is included (`release:` runs migrations, `web:` runs gunicorn). Set the environment variables above, use
`pip install -r requirements-prod.txt && python manage.py collectstatic --noinput` as the build command, and `DJANGO_TRUSTED_PROXY_COUNT=1`.
Most platforms have an **ephemeral disk**, so SQLite data would be lost on redeploy: use the platform's managed MySQL or attach a persistent disk and point
`DJANGO_SQLITE_PATH` at it. This has not been tried on any provider.

## 5. MySQL

```sql
CREATE DATABASE smart_parking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'smartpark'@'localhost' IDENTIFIED BY '...';
GRANT ALL ON smart_parking.* TO 'smartpark'@'localhost';
```

Install the client library (`pip install mysqlclient`; it needs the MySQL client development libraries on the machine), set `DB_ENGINE=mysql` and the `DB_*`
variables, and **load the time-zone tables** once, otherwise the dashboard's per-day charts are empty: `mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root -p mysql`.
Then `python manage.py migrate`. MySQL 8.0.16 or newer is needed for the check constraints.

## 6. Scheduled work and backups

Bookings that were never used should be closed regularly (marks them `no_show`, cancels their payment, charges nothing):

```cron
*/15 * * * * cd /srv/smartpark && venv/bin/python manage.py expire_bookings
```

Back up the database daily: `sqlite3 db.sqlite3 ".backup '/backups/smartpark-$(date +%F).sqlite3'"` or `mysqldump smart_parking > ...`.

**Several workers or servers:** login throttling counters live in Django's cache, which by default is per process. Use a shared cache so limits apply everywhere,
for example the database cache (no extra package): set `CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'django_cache_table'}}`
in `config/settings.py` and run `python manage.py createcachetable`.

## 7. First admin and demo data

- Create the first administrator with `createsuperuser`; promote others on the dashboard (Users, **Make admin**). The `admin` role gives access to the dashboard
  but not to Django's own `/admin/` site (that needs staff status).
- `python manage.py seed_demo` creates demo locations, bookings and accounts (`admin_demo`, `user_demo`) with **well-known passwords**. It refuses to run with
  `DJANGO_DEBUG=False` unless you add `--force`; use that only on a throw-away demo site and never on a real one.

## 8. After deploying

1. Open `/`, `/accounts/login/`, then log in as the admin and open the dashboard.
2. Check the browser console on the dashboard, the booking form and a booking page: there must be no Content-Security-Policy errors (if there are, set `DJANGO_CSP_REPORT_ONLY=True` while you look into it).
3. Confirm `http://` redirects to `https://`.
4. Run the API tests against a **staging** copy, not production (the collection registers users and creates bookings): `bash tools/run_postman.sh` runs it against a throw-away local database, or point the Postman environment's `base_url` at staging.

## 9. Troubleshooting

| Symptom | Cause |
|---|---|
| Every page returns 500 right after deploying | `collectstatic` was not run (the hashed static manifest is missing) |
| Login or any form gives "403 Your session expired" behind a proxy | Set `DJANGO_CSRF_TRUSTED_ORIGINS` and `DJANGO_BEHIND_PROXY=True`; make sure the proxy sends `X-Forwarded-Proto` |
| `400 Bad Request` for every request | The host name is missing from `DJANGO_ALLOWED_HOSTS` |
| App refuses to start: "Set DJANGO_SECRET_KEY..." | Debug is off and the secret key is missing, short or the development key |
| One failed login locks out many people | The proxy count is wrong, so everyone looks like the same IP: set `DJANGO_TRUSTED_PROXY_COUNT` correctly |
| Dashboard daily charts empty on MySQL | Time-zone tables are not loaded (section 5) |
