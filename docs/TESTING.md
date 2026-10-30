# Testing guide

At delivery: **240 automated tests, all passing, 97% line coverage** of `apps/` and `config/` (SQLite; measured over everything including the test files, with no exclusions. The production-settings branch, `wsgi.py`/`asgi.py` and the concurrency helper run in subprocesses that the coverage tool cannot see, but are tested that way). Plus a 64-request Postman/Newman API run and the manual
checklist at the end of this page.

## Running the checks

```bash
python manage.py test                                  # the whole automated suite (about 30 seconds)
python manage.py test apps.bookings                    # one app
python manage.py test apps.core.test_workflows         # the end-to-end journeys

python manage.py check && python manage.py makemigrations --check --dry-run
DJANGO_DEBUG=False DJANGO_SECRET_KEY=<50+ random characters> python manage.py check --deploy

python tools/build_docs.py --check                     # API.md / DATABASE.md / Postman files match the code
bash tools/run_postman.sh                              # API tests (needs Node.js): throw-away DB + server + Newman

pip install coverage                                   # optional
coverage run --source=apps,config manage.py test && coverage report -m
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs the checks above on every push. (It was written to match these commands but has not been run on GitHub from here.)

## What the automated tests cover

| Area | Where | What is checked |
|---|---|---|
| Accounts | `apps/accounts/tests.py` | Registration (duplicate/weak/invalid input), login/logout, open-redirect protection, profile ownership, password change, roles, token API |
| Parking | `apps/parking/tests.py` | Model constraints, search and filters, public vs admin visibility, admin CRUD and permissions, bulk slots, API shapes and errors |
| Bookings | `apps/bookings/tests.py` | Every booking rule (time limits, hours, types, overlaps, back-to-back), vehicles, history, cancellation rules, delete protection, API |
| Payments | `apps/payments/tests.py` | Pricing maths and rounding, simulated payments and retries, refunds, check-in/out rules, overstay balance, no-shows, API and admin transitions |
| Dashboard | `apps/dashboard/tests.py` | Access control on every URL, statistics (revenue excludes refunds), filters, CSV safety, booking/payment status changes, user management guards, query counts |
| Security | `apps/core/test_security.py` | Login lockout and throttling, spoofed headers, CSRF on every state-changing endpoint, ownership of every private resource (web and API), deactivated accounts, security headers, no inline scripts, production settings, `.env` loading |
| Bad input | `apps/core/test_inputs.py` | A sweep of 19 hostile values over every list endpoint and form: nothing may return a 5xx |
| UI | `apps/core/test_ui.py` | Error pages, accessibility markup, form error linking, empty states, double submit safety |
| Journeys | `apps/core/test_workflows.py` | A complete user journey, a complete admin journey and a complete API journey, plus 8 simultaneous bookings of one slot (exactly one wins) |
| Concurrency | `apps/core/test_concurrency_file_db.py` | The same race on a real SQLite file: one booking, seven clean refusals, no lock errors |
| Deployment | `apps/core/test_deploy.py`, `apps/core/test_docs.py` | `collectstatic` with the production storage, every template static reference resolves, docs match the code, links and commands in the docs exist |
| Demo data | `apps/parking/test_seed_demo.py` | The demo command, its safety refusal when debug is off |
| Design | `apps/core/test_design.py` | Live home page data, template helpers, every illustration well-formed and safe, every icon used exists in the sprite, image alt text |

**The tests are checked against deliberately broken code.** Several were verified by putting a bug back and confirming the test fails: removing the slot-overlap
check (the concurrency test fails on "never more than one booking"), restoring the unsafe query-parameter handling (the regression and fuzz tests fail), and
restoring a broken vendored script (the production-static test fails). The simultaneous-booking tests were run hundreds of times, including 100 runs under deliberate CPU contention, without a double booking.

**A bug this found.** On the default SQLite file database, when several people booked the same slot at the same instant, one succeeded but the others crashed with a raw
`database is locked` error (a 500 page) instead of the friendly "already booked" message. No double booking ever happened, but the failure was ugly. It was reproduced (12 of 12 runs),
fixed by starting SQLite transactions in `IMMEDIATE` mode with a 20-second wait, and is now guarded by `apps/core/test_concurrency_file_db.py`, which books one slot from 8 threads
against a real database file and requires exactly one booking and seven clean refusals (removing the fix makes it fail).

## API tests (Postman)

`docs/postman/` holds a Postman collection (10 folders, 64 requests, 109 assertions) and an environment file. It walks the whole business flow: register, login, browse, fee check,
book, overlap refused, pay (simulated failure then success), check in and out, cancel and refund, admin dashboard and status changes, ownership and token security, logout.

- **Postman app:** import both files, select the *SmartPark local* environment, set `base_url`, start the server with demo data (`python manage.py seed_demo`) and run the collection in order.
- **Command line:** `bash tools/run_postman.sh` does everything on a throw-away database. Result at delivery: **64 requests, 109 assertions, 0 failures**, and it can be re-run repeatedly (it leaves only completed and cancelled bookings behind, so it never blocks slots).
- Run it against a development or staging copy, never production: each run registers users and creates bookings.

The collection is generated by `tools/postman_collection.py` (`python tools/build_docs.py`); a test fails if the committed files fall behind.

## Performance sanity check

Measured once in the build sandbox (SQLite, one process) with **6,025 bookings, 6,025 payments, 1,030 slots, 23 locations and 503 users**:

| Page | Queries | Time |
|---|---|---|
| Dashboard overview (first load / second view) | 17 | 380 ms / 70 ms |
| All bookings (page 1) / filtered / search | 6 | 84 / 19 / 27 ms |
| Users list | 5 | 24 ms |
| CSV export of 6,025 bookings | 4 | 852 ms |
| Parking list / location page / my bookings | 4-6 | 8-11 ms |
| API: dashboard summary / bookings | 17 / 5 | 59 / 28 ms |

Query counts do not grow with the number of rows. The CSV export is capped at 10,000 rows. This is a sanity check, not a load test.

## Browser checks

`tools/screenshots.mjs` drives a real (headless) Chrome through the main pages as a visitor, a user and an admin, at desktop and phone width, and fails if the browser reports anything:
console errors (including Content-Security-Policy violations), failed requests, HTTP errors, horizontal page overflow, a missing fee estimate, or fewer than 5 dashboard charts. It also writes the screenshots in `docs/screenshots/`.

```bash
npm install puppeteer-core
python manage.py seed_demo && python manage.py runserver
BASE=http://127.0.0.1:8000 CHROME_PATH="/path/to/chrome" node tools/screenshots.mjs
```

Result at delivery, Chromium 131: **no console or CSP errors, no failed requests, all 5 charts created and drawn, the live fee estimate works, and no horizontal overflow on any key page at 1366, 1024, 768 and 390 px.**
Data tables fit at laptop width and scroll inside their own container on narrower screens.

## What is not covered

- **Limited browser coverage.** Pages were checked in headless Chromium only (see above). Firefox, Safari, older browsers and a physical phone were not tried, and the sandbox browser could not run animations, so chart animations were switched off for the screenshots. Please also do the manual checklist below on your own devices.
- **MySQL** was never run. **Real concurrency on MySQL/PostgreSQL** (row locking) is untested; the simultaneous-booking tests ran on SQLite.
- **No load or stress testing** beyond the sanity check above, and no external security audit.
- Payments are simulated, so no payment gateway behaviour is tested.

## Manual acceptance checklist

Use a fresh database with `python manage.py seed_demo`. Tick each item in a real browser (try a phone-sized window too).

**Visitor**
- [ ] Home page loads, the navigation collapses behind the menu button on a narrow screen
- [ ] Parking page lists locations with free/total slots; search, city, slot-type and "Has free slots" filters work; an impossible search shows a friendly empty message
- [ ] A location shows green/red/grey slots with a legend; the slot-type filter works
- [ ] A slot page shows details and "Login to book"
- [ ] Register with a weak password and a duplicate email: clear errors; then register properly (you are logged in)
- [ ] Five wrong passwords on login lock that username for 15 minutes with a clear message

**User**
- [ ] Booking form: pick times, the estimate appears ("Calculating..." then the amount); a past time or overlap gives a clear error
- [ ] Confirmation page shows the reference, times, vehicle and charge; the booking is in "My Bookings"
- [ ] Pay now: "SIMULATED PAYMENT" banner; the failure option shows an error and allows a retry; success shows a transaction id
- [ ] A booking starting in the next 15 minutes can be checked in; the slot turns red for visitors; check out completes it and frees the slot
- [ ] Booking tomorrow, paying and cancelling shows Cancelled / Refunded; a booking starting within the hour cannot be cancelled and says why
- [ ] Profile and password change work; Logout works; the buttons show "Please wait..." while submitting

**Administrator** (`admin_demo`)
- [ ] Dashboard: cards, five charts (draw correctly, no console errors), the 7/14/30/90-day selector, the locations table
- [ ] Bookings list: filters, search by plate, Export CSV opens in a spreadsheet; a booking page offers only valid status changes; marking a payment paid works
- [ ] Add a location, add one slot and several slots in bulk; edit a slot to "unavailable" and see it grey for visitors; deleting a location that has bookings is refused with an explanation
- [ ] Users: search, deactivate a user (they are logged out), reactivate, make admin and back; you cannot change yourself
- [ ] A normal user opening `/dashboard/` sees "Access denied"

**Deployment**
- [ ] `check --deploy` shows only the two HSTS notices; HTTP redirects to HTTPS; pages and static files load with `DJANGO_DEBUG=False`
