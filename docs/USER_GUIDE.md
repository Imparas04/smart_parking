# User guide and demonstration script

Screenshots of every main page, on desktop and phone, are in [screenshots/](screenshots/).

## For drivers (users)

1. **Create an account.** *Register* (top right): username, name, email, optional phone, password. You are logged in straight away.
2. **Find parking.** *Parking* lists locations with free slots out of the total and the hourly price. Search by name, address or city, narrow by city or slot type
   (car, bike, EV, accessible) and tick *Has free slots*. Open a location to see its slots: **green = available, red = occupied, grey = unavailable**.
3. **Pick a slot.** Click a slot for its details (type, rate, opening hours). If you are not logged in it says *Login to book*.
4. **Book.** Choose the start and end time (shown in India time), then either a saved vehicle or a new plate number and type. The page shows the
   **estimated charge** as you type: the hourly rate times the hours, rounded up, at least one hour. Press *Confirm booking*.
   Rules: starts in the future, 30 minutes to 24 hours, up to 30 days ahead, inside the opening hours, a slot that is free for the whole time, and a vehicle that fits the
   slot (bikes in bike slots, EV slots for EVs). If a rule is broken you get a clear message.
5. **Confirmation.** The booking page shows your reference (like `PK-1A2B3C4D`), times, vehicle and the charge.
6. **Pay.** *Pay now (simulated)*. **No real money is taken**: the page says so. Pick a method; the test option "Payment fails" shows what a failed payment looks like, and you can retry.
7. **Arrive and check in.** From 15 minutes before the start you can press *Check in*; the slot turns red for everyone.
8. **Leave and check out.** Press *Check out* to finish. The final charge is the booked period; staying past the end time is billed for the extra hours (and leaves a balance to pay),
   leaving early does not reduce the charge.
9. **Cancel.** *Cancel booking* works while the booking is still confirmed and starts in more than 60 minutes. A paid booking shows *Refunded* (simulated); an unpaid one is cancelled.
10. **History.** *My Bookings* lists everything with status tabs, amount and payment status. *Your name* in the menu opens your profile (change details or password).

If you never show up, the booking is eventually marked **No show** and is not charged.

## For administrators

Log in with an account that has the admin role; a **Dashboard** link appears in the menu.

- **Overview.** Revenue (today, last N days, all time), pending dues, bookings, slot availability and occupancy, five charts and a table per location. Choose 7, 14, 30 or 90 days for the daily charts.
  *Revenue* is money actually received; refunded and cancelled payments are not counted.
- **Locations and slots.** *Parking* shows admin buttons: **+ Add location**, then on a location *Edit*, *+ Slot*, *+ Many slots* (for example prefix `G-`, start 1, count 20) and *Delete*.
  Mark a slot **Unavailable** for maintenance. A location or slot that has bookings cannot be deleted; make the location inactive (hidden from the public) or the slot unavailable.
- **Bookings.** Filter by status, payment, location, date or text (reference, user, email, plate) and *Export CSV*. Open a booking to **update its status** (check in, check out, cancel, mark no-show:
  only valid changes are offered, refunds and slot status follow automatically) and its **payment status** (for example mark *Paid* when cash is taken at the gate).
- **Users.** Search and filter registered users; *Deactivate* (they are logged out immediately), *Activate*, *Make admin* or *Make user*. You cannot change your own account or a superuser.
- **Housekeeping.** Run `python manage.py expire_bookings` regularly (cron) to mark unused, finished bookings as no-shows.

The REST API for all of this is in [API.md](API.md).

## Demonstration script (about 10 minutes)

Preparation, once:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # demo locations, 20+ bookings and accounts (prints the logins)
python manage.py runserver
```

Accounts: **admin_demo / DemoAdmin#2026**, **user_demo / DemoUser#2026** (demo data only, never on a real site).

| Step | Do | Say / show |
|---|---|---|
| 1. The public site (1 min) | Open `http://127.0.0.1:8000`, go to *Parking*, search `mall`, open a location | Live availability colours; the slot page asks you to log in |
| 2. Book (2 min) | Log in as `user_demo`, open a green slot, **Book this slot**. Choose a start **5 minutes from now**, 2 hours long, plate `MH15XY0001` | The estimated charge appears; try an overlapping or past time to show the validation |
| 3. Pay (1 min) | On the confirmation page, *Pay now*, choose "Payment fails", then retry with "Payment succeeds" | The SIMULATED banner; statuses pending, failed, paid |
| 4. Check in and out (1 min) | *Check in*, show the slot turned red on the location page, then *Check out* | The booking completes; the slot is free again; the final amount |
| 5. Cancel and refund (1 min) | Book tomorrow, pay, then *Cancel booking* | Cancelled and Refunded; a booking inside the hour explains why it cannot be cancelled |
| 6. Admin (3 min) | Log in as `admin_demo`, open **Dashboard**: cards and charts, switch to 30 days. *Bookings*: filter by status, open the new booking, mark its payment paid, *Export CSV*. *Users*: deactivate and reactivate `user2_demo`. *Parking*: add a location and bulk-add slots | Reports, status management, user management |
| 7. The API and tests (1 min) | `bash tools/run_postman.sh`, then `python manage.py test` | 64 API requests and 109 assertions pass; the automated suite passes |

Tip for step 2: the 15-minute check-in window is why the demo booking starts in 5 minutes.
