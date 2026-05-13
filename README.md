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

## Deploying to Render

1. Push this folder to a GitHub repo.
2. Go to https://render.com and create a Web Service.
3. Connect your GitHub repo.
4. Render will auto-detect `render.yaml` and configure the build.
5. After first deploy, open the Render shell and run:
   ```bash
   python setup_initial_data.py
   ```

Set production environment variables before deploying:
- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `ADMIN_PASSWORD`

Optional email notification settings:
- Staff users with an email address are notified automatically.
- Crew athletes are notified when they have a linked user with an email address.
- `BOOKING_NOTIFICATION_EXTRA_RECIPIENTS`: optional comma-separated extra email addresses.
- `DEFAULT_FROM_EMAIL`: sender address shown in notification emails.
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: SMTP provider settings.
- `EMAIL_USE_TLS` or `EMAIL_USE_SSL`: enable the security mode required by the SMTP provider.

In local development, `DEBUG=True` uses Django's console email backend by default.

> SQLite note: Render's free tier has an ephemeral disk, so SQLite data resets on deploy.
> For a persistent club app, use a Render Disk or switch to PostgreSQL.

---

## Tests

```bash
python manage.py test
```
