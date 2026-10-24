# Changelog

## 1.0.0

Delivered phase by phase.

- **Phase 8, testing, documentation, delivery.** End-to-end user/admin/API journey tests and a threaded double-booking test; Postman collection (64 requests, 109 assertions) run with Newman;
  generated API and database documentation that tests keep in sync with the code; deployment, testing and user guides; requirements checklist; CI workflow. Production serving (gunicorn, WhiteNoise)
  verified in production mode. Fixes found on the way: the vendored Chart.js source-map reference that made every page fail under production static storage, location create responses
  missing slot counts, an undocumented API root and `.json` variants on the parking API, an unfriendly duplicate-slot error, `"vehicle": null` rejected, an unused variable causing an extra query, and simultaneous bookings on the default SQLite file crashing with `database is locked` instead of being refused cleanly (now queued with IMMEDIATE transactions).
- **Phase 7, UI polish, validation, security.** Login lockout and API throttling, Content-Security-Policy and security headers, production settings guard, CSRF and ownership test matrices,
  fuzz tests, custom error pages, accessibility improvements, loading states. Fixed 500 errors on malformed query parameters, `.env` never being loaded, host lists with spaces.
- **Phase 6, admin dashboard and reports.** Statistics, five charts, bookings management and CSV export, user management, admin booking/payment status updates, summary API.
- **Phase 5, pricing, payments, check-in/out.** Server-side pricing with rate snapshot, simulated payments, refunds, overstay balances, no-shows, check-in/out.
- **Phase 4, bookings.** Vehicles, booking with double-booking protection, cancellation, history, delete protection, API.
- **Phase 3, locations and slots.** Models, search and filters, colour-coded slots, admin CRUD, bulk slots, API.
- **Phase 2, authentication and profiles.** Registration, login, roles, profile, token API.
- **Phase 1, foundation.** Django project, apps, base layout, configuration.
