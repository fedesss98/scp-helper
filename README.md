# Rowing Club Booking App

A simple Django web app for managing rowing club slots, workouts, boats, athletes, and complete-crew bookings.

## Features

- Athletes can browse a weekly calendar and book/cancel complete boat crews.
- Admin users can create users, link users to athlete profiles, create slots in batch, and manage bookings.
- Slots are concrete date/time intervals, optionally linked to a reusable workout.
- Boats have rower seats and can optionally require a cox.
- Bookings reserve one boat for one slot and must include the full crew.
- No self-registration: admin users control accounts.

---

## Local Development

### 1. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate      # Mac/Linux
# venv\Scripts\activate       # Windows
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run migrations
```bash
python manage.py migrate
```

If you are upgrading from the previous prototype schema, recreate the local
database first because the booking models were intentionally redesigned
destructively.

### 4. Create starter data + admin user
```bash
python setup_initial_data.py
```

This creates:
- Starter workouts from `setup_initial_data.py`
- Starter boats from `setup_initial_data.py`
- Concrete slots for the current month using batch generation
- Admin user `admin`

Set `ADMIN_PASSWORD` before running the script to choose the initial password.
In local development, if it is not set, the script generates and prints a one-time password.
In production, `ADMIN_PASSWORD` is required.

### 5. Run the dev server
```bash
python manage.py runserver
```

Open http://localhost:8000 and log in as `admin`.

---

## Domain Model

- `Athlete`: sports identity with full name, optional date of birth, sex, active flag, and optional linked Django user.
- `User`: login identity and permissions. Creating a user can also create/link an athlete profile.
- `Workout`: reusable text label/description such as `S&C` or `4x3000 rest 10'`.
- `Slot`: concrete date/time interval, optionally linked to one workout.
- `SlotBatch`: helper record used to generate concrete slots for repeated weekdays.
- `Boat`: boat name, rower seat count, optional cox requirement, color, and active flag.
- `Booking`: one boat in one slot with a complete crew.
- `BookingCrewMember`: through model for booking crew, preserving rower seats and cox role.

## Admin Tasks

### Create a user and athlete link
1. Log in as admin.
2. Go to **Utenti** in the nav.
3. Click **+ Aggiungi Utente**.
4. Either link an existing athlete or leave the athlete field empty to create one from the user's name.
5. Use the Staff checkbox for admin privileges.

### Create slots
Use **Slot** in the app nav. You can create a single concrete slot or use the batch form to generate every selected weekday over a date range.

### Manage workouts, boats, and standalone athletes
Use Django's built-in admin panel at `/django-admin/`.

---

## Deploying to Heroku

This repository includes the Heroku deployment files:

- `Procfile` runs database migrations during Heroku release phase and starts Gunicorn.
- `.python-version` pins Heroku builds to Python 3.13.
- `.slugignore` keeps local data, notebooks, SQLite files, and collected static output out of the Heroku slug.

1. Push the `production` branch to your Heroku app:
   ```bash
   git push heroku production:main
   ```

2. Set production config vars before deploying:
   ```bash
   heroku config:set DEBUG=False
   heroku config:set SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
   heroku config:set ALLOWED_HOSTS=your-app.herokuapp.com
   heroku config:set CSRF_TRUSTED_ORIGINS=https://your-app.herokuapp.com
   heroku config:set ADMIN_PASSWORD=replace-with-a-strong-password
   ```

3. Attach PostgreSQL so Heroku provides `DATABASE_URL`:
   ```bash
   heroku addons:create heroku-postgresql:essential-0
   ```

4. After the first deploy, seed boats, bookable slots, and the admin user:
   ```bash
   heroku run python setup_initial_data.py
   ```

For custom domains, add them to both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
After you confirm every production domain is served only over HTTPS, you can enable HSTS with `SECURE_HSTS_SECONDS`.

> **Database note**: Heroku dynos have an ephemeral filesystem. Use PostgreSQL for persistent production data.

## Deploying to Render (free tier)

`render.yaml` is still included for Render deployments.

---

## Customising Calendar Slots

Bookable slots are managed in Django admin at `/django-admin/bookings/bookableslot/`.
The calendar only shows active weekly slots. `setup_initial_data.py` seeds this schedule:

- Monday: 15:30
- Tuesday: 07:00, 14:00, 15:30
- Wednesday: 15:30
- Thursday: 07:00, 14:00, 15:30
- Friday: 15:30
- Saturday: 08:00, 10:30
- Sunday: 08:30

Seeded slots are 30 minutes long by default; edit their end time in Django admin if sessions should last longer.

## Boat Categories and Seats

Boats have a category such as `1xC`, `2xC`, `2x`, `4x`, or `4+`, plus a seat count. Multiple athletes can book the same boat at overlapping times until all seats are full.

## Adding More Boats

Just add them via `/django-admin/bookings/boat/add/` or edit `setup_initial_data.py`.
