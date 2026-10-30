# Requirements checklist

Status of every item in the *Smart Parking Management System* internship assignment. ✅ done and verified, ⚠️ done with a stated limit, ❌ not done.

## Technology choices (a deliberate deviation)

| Assignment says | Delivered | Why |
|---|---|---|
| Frontend: React.js, HTML, CSS, JavaScript | Django Templates, HTML, CSS, JavaScript (Chart.js for charts) | The project brief for this build was Python/Django with no React or Node.js |
| Backend: Node.js, Express.js | Python, Django, Django REST Framework | Same |
| Database: MongoDB or MySQL | SQLite by default; MySQL supported by configuration | ⚠️ MySQL was **not tested** here (see [DEPLOYMENT.md](DEPLOYMENT.md)) |
| API testing: Postman | Postman collection, run with Newman | ✅ |
| Version control: Git and GitHub | Git commands per phase; CI workflow | ⚠️ The pushes are yours to run |

## Task 1: Frontend

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Responsive Home Page | ✅ | `/`; landing page with search, live numbers and illustrations. Checked in headless Chrome at 1366, 1024, 768 and 390 px with no overflow. ⚠️ not tried on a physical phone |
| 2 | Login and Registration pages | ✅ | `/accounts/login/`, `/accounts/register/` |
| 3 | Parking Locations page | ✅ | `/parking/` with search and filters |
| 4 | Display available and occupied slots | ✅ | Colour-coded grid on `/parking/<id>/` |
| 5 | Parking Slot Details page | ✅ | `/parking/slots/<id>/` |
| 6 | Parking Booking page | ✅ | `/bookings/book/<slot>/` with live fee estimate |
| 7 | Booking History page | ✅ | `/bookings/` |
| 8 | User Profile page | ✅ | `/accounts/profile/` |
| 9 | Admin Dashboard | ✅ | `/dashboard/` and its Bookings and Users pages |
| 10 | Availability and booking statistics in charts | ✅ | Five Chart.js charts, verified drawing in headless Chromium (see `docs/screenshots/dashboard.png`) |

## Task 2: Backend (REST APIs)

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Registration and login APIs | ✅ | `POST /api/auth/register/`, `/login/` |
| 2 | Authentication and role-based authorization | ✅ | Token auth; `user`/`admin` roles checked on every request |
| 3 | CRUD for parking locations | ✅ | `/api/parking/locations/` (admin writes) |
| 4 | CRUD for parking slots | ✅ | `/api/parking/slots/` (admin writes) |
| 5 | Slot booking | ✅ | `POST /api/bookings/` with double-booking protection |
| 6 | Booking cancellation | ✅ | `POST /api/bookings/{reference}/cancel/` |
| 7 | Charges from parking duration | ✅ | Server-side pricing, estimate endpoint |
| 8 | Check-in and check-out | ✅ | `/check-in/`, `/check-out/` (overstay billed) |
| 9 | Booking history APIs | ✅ | `GET /api/bookings/` with filters and pagination |
| 10 | Payment status management | ✅ | `/api/payments/...`; admin `PATCH .../status/`. ⚠️ Payments are **simulated** |
| 11 | Input validation and error handling | ✅ | Consistent 400/401/403/404/409/429 responses; hostile-input sweep finds no 5xx |

## Task 3: Database

| Required table | Status | Table |
|---|---|---|
| Parking_Locations | ✅ | `parking_parkinglocation` |
| Parking_Slots | ✅ | `parking_parkingslot` |
| Parking_Bookings | ✅ | `bookings_booking` |
| Vehicles | ✅ | `bookings_vehicle` |
| Payments | ✅ | `payments_payment` |
| (users) | ✅ | `auth_user` + `accounts_profile` |

Schema, constraints and an ER diagram: [DATABASE.md](DATABASE.md).

## Task 4: Admin module

| Requirement | Status | Where |
|---|---|---|
| Add, update, view, delete parking locations | ✅ | `/parking/` admin buttons; API |
| Manage parking slots | ✅ | Add, bulk-add, edit, delete; mark unavailable |
| View registered users | ✅ | `/dashboard/users/` (also activate/deactivate, roles) |
| View all bookings | ✅ | `/dashboard/bookings/` with filters and CSV export |
| Update booking and payment statuses | ✅ | Booking detail page; API |
| View total bookings and parking revenue | ✅ | Dashboard cards and charts |
| Monitor slot availability | ✅ | Dashboard table and chart per location |

## Task 5: User module

| Requirement | Status | Where |
|---|---|---|
| Register and log in | ✅ | |
| Search parking locations | ✅ | Name/address/city, city, slot type, free slots |
| View available slots | ✅ | |
| Book a parking slot | ✅ | |
| View booking confirmation | ✅ | `/bookings/<reference>/` |
| Cancel eligible bookings | ✅ | Up to 60 minutes before the start |
| View booking history | ✅ | |
| Check parking fees | ✅ | Live estimate on the booking form; `GET /api/payments/estimate/` |
| View and update profile | ✅ | |

## Task 6: Testing and deployment

| Requirement | Status | Evidence |
|---|---|---|
| Test the APIs using Postman | ✅ | `docs/postman/`: 64 requests, 109 assertions, 0 failures (Newman) |
| Test frontend and backend integration | ✅ | End-to-end user, admin and API journeys in `apps/core/test_workflows.py` |
| Validate form inputs | ✅ | Server-side validation on every form and API; hostile-input sweep |
| Handle database and server errors | ✅ | Protected deletes (409), friendly 403/404/500/CSRF pages, no 5xx on bad input |
| Maintain source code using Git and GitHub | ⚠️ | Commands for each phase were provided; you run them. CI workflow included |
| Deploy the application | ❌ | **Not deployed to a live host.** It is deployment-ready and was verified in production mode locally (gunicorn + WhiteNoise); follow [DEPLOYMENT.md](DEPLOYMENT.md) |

## Expected deliverables

| Deliverable | Status | Where |
|---|---|---|
| Complete frontend application | ✅ | `templates/`, `static/` |
| Backend REST APIs | ✅ | [API.md](API.md) |
| Database schema | ✅ | [DATABASE.md](DATABASE.md) |
| Authentication and authorization | ✅ | |
| Admin and user modules | ✅ | [USER_GUIDE.md](USER_GUIDE.md) |
| API testing documentation | ✅ | [TESTING.md](TESTING.md), Postman collection |
| GitHub repository | ⚠️ | Yours to create and push |
| Deployed application | ❌ | See above |
| Final documentation and demonstration | ✅ / ⚠️ | Documentation done; a scripted 10-minute demo is in [USER_GUIDE.md](USER_GUIDE.md), but the live demonstration is yours to give |

## Known limitations

- **Payments are simulated**: no gateway, no real money; a real gateway would need integrating.
- **No password-reset or email-verification flow**; no email/SMS notifications.
- **API tokens do not expire** (logging out revokes them).
- **Not tested on MySQL**, on a real hosting provider, or on Firefox, Safari or a physical phone (headless Chrome only).
- **Login throttling uses a per-process cache** by default; use a shared cache when running several workers.
- A booking cannot be edited, only cancelled and rebooked. One time zone (India) for the whole site.
- The CSV export is capped at 10,000 rows. No images, maps or geolocation for locations.
- The `admin` role does not include Django's own `/admin/` site (that needs staff status): deliberate least privilege.
