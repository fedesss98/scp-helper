# VogApp Rowing Club App

A Django web app for managing rowing club slots, workouts, boats, athletes,
complete-crew bookings, regatta calendars, race results, and Telegram result
notifications.

## Features

- Athletes can browse a weekly calendar and book/cancel complete boat crews.
- Admin users can create athletes, create slots in batch, and manage bookings.
- Slots are concrete date/time intervals, optionally linked to a reusable workout.
- Boats have rower seats and can optionally require a cox.
- Bookings reserve one boat for one slot and must include the full crew.
- Logged-in users can browse upcoming regattas under **Regate**.
- Race detail pages default to **Programma SCP**, showing only races with at least one `PALERMO SC` crew and highlighting that crew row.
- Users can switch to **Programma Completo** to see the full saved race program.
- Users can subscribe/unsubscribe to race result notifications from the web UI.
- Race calendar, program, and result data is scraped from canottaggioservice.canottaggio.net into the Django database.
- A worker process polls subscribed upcoming races and sends Telegram notifications when new results appear.
- No self-registration: admin users control accounts.

See [MERGE_CHANGES.md](MERGE_CHANGES.md) for the scraper/API/bot merge notes.

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

This creates the booking tables plus the new `accounts`, `races`, and
`notifications` app tables.

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

### 6. Load race data
```bash
python manage.py scrape_races
```

The command syncs the current season calendar and hydrates upcoming races with
program/results when available. Useful options:

- `--season 2026`: scrape a specific FIC season.
- `--skip-program`: sync calendar/results only.
- `--skip-results`: sync calendar/program only.
- `--all`: hydrate past races too.
- `--limit 10`: hydrate only the first 10 races after calendar sync.

### 7. Run the Telegram worker
```bash
python bot/run_bot.py
```

The worker uses Django ORM data and polls subscribed upcoming races every 180
seconds by default. Set `TELEGRAM_BOT_TOKEN` to enable Telegram sends and command
handlers.

---

## Domain Model

- `Athlete`: sports identity with full name, optional date of birth, sex, active flag, and optional linked Django user.
- `User`: login identity and permissions, created from Django's built-in admin panel.
- `Workout`: reusable text label/description such as `S&C` or `4x3000 rest 10'`.
- `Slot`: concrete date/time interval, optionally linked to one workout.
- `SlotBatch`: helper record used to generate concrete slots for repeated weekdays.
- `Boat`: boat name, rower seat count, optional cox requirement, color, and active flag.
- `Booking`: one boat in one slot with a complete crew.
- `BookingCrewMember`: through model for booking crew, preserving rower seats and cox role.
- `UserProfile`: one-to-one profile for each Django user, including Telegram chat/user details and phone.
- `Race`: one canottaggioservice regatta, keyed by unique `external_id`.
- `RaceResult`: one published finisher/result row, keyed by unique `external_id` for idempotent sync.
- `RaceSubscription`: many-to-one user subscriptions to races, unique per `(user, race)`.

## Race Scraping and Notifications

Race scraping now lives in the Django project:

- `races/scraper.py`: framework-free scraper functions/classes extracted from the old FastAPI service.
- `races/sync.py`: Django ORM sync helpers using `update_or_create`.
- `races/management/commands/scrape_races.py`: manual/scheduled ingestion command.
- `bot/run_bot.py`: production worker for result polling and optional Telegram commands.
- `notifications/telegram_utils.py`: plain `requests` sender for Telegram Bot API.

The old FastAPI API, SQLite bot database, and APScheduler polling path are no
longer required. Race subscriptions are stored in PostgreSQL/SQLite through the
Django `RaceSubscription` model.

## Environment Variables

Core app variables:

- `DEBUG`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `DATABASE_URL`
- `CSRF_TRUSTED_ORIGINS`
- `ADMIN_PASSWORD`

Race/Telegram variables:

- `TELEGRAM_BOT_TOKEN`: Telegram bot token used by the worker.
- `RACE_CLUB_NAME`: club name used for program filtering and result notifications. Defaults to `PALERMO SC`.
- `RACE_CLUB_SHORT_NAME`: short label used in the UI. Defaults to `SCP`.
- `FIC_BASE_URL`: scraper upstream base URL. Defaults to `https://canottaggioservice.canottaggio.net`.
- `FIC_USER_AGENT`: scraper user agent. Defaults to `Mozilla/5.0`.
- `FIC_TIMEOUT_S`: upstream request timeout in seconds. Defaults to `15`.
- `FIC_CALENDAR_REQUEST_DELAY_S`: delay between calendar manifestation requests. Defaults to `0.5`.

## Admin Tasks

### Create athletes
1. Log in as admin.
2. Go to **Atleti** in the nav.
3. Click **+ Aggiungi Atleta**.
4. Fill in the athlete details.
5. Optionally link an existing user that was already created in Django admin.

User accounts and staff permissions are managed only from Django's built-in admin panel at `/django-admin/`.

## Email Setup with Brevo

Outgoing mail already uses Django's standard SMTP backend, so Brevo works by setting environment variables.

Use these values as a starting point:

- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST=smtp-relay.brevo.com`
- `EMAIL_PORT=587`
- `EMAIL_USE_TLS=True`
- `EMAIL_HOST_USER=your-brevo-login`
- `EMAIL_HOST_PASSWORD=your-brevo-smtp-key`
- `DEFAULT_FROM_EMAIL=your@yourdomain.com`

The `DEFAULT_FROM_EMAIL` address should be a sender verified in Brevo, such as the Hostinger mailbox on your domain.

When a new Django user is created with an email address, the app now sends a welcome email automatically.

### Create slots
Use **Slot** in the app nav. You can create a single concrete slot or use the batch form to generate every selected weekday over a date range.

### Manage workouts, boats, and users
Use Django's built-in admin panel at `/django-admin/`.

### Manage Telegram profiles
Use Django admin to edit a user's inline `UserProfile`. Set
`telegram_username` before the user runs `/start`, or set `telegram_chat_id`
directly if you already know it.

---

## Deploying to Heroku

This repository includes the Heroku deployment files:

- `Procfile` runs database migrations during Heroku release phase and starts Gunicorn.
- `Procfile` also defines `worker: python bot/run_bot.py` for result polling.
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
   heroku config:set TELEGRAM_BOT_TOKEN=replace-with-your-telegram-token
   ```

3. Attach PostgreSQL so Heroku provides `DATABASE_URL`:
   ```bash
   heroku addons:create heroku-postgresql:essential-0
   ```

4. After the first deploy, seed boats, bookable slots, and the admin user:
   ```bash
   heroku run python setup_initial_data.py
   ```

5. Load the race calendar:
   ```bash
   heroku run python manage.py scrape_races
   ```

For custom domains, add them to both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
After you confirm every production domain is served only over HTTPS, you can enable HSTS with `SECURE_HSTS_SECONDS`.

> **Database note**: Heroku dynos have an ephemeral filesystem. Use PostgreSQL for persistent production data.

## Deploying to Render (free tier)

`render.yaml` is still included for Render deployments.

---

## Customising Calendar Slots

Slots are managed in Django admin at `/django-admin/bookings/slot/`.
The calendar only shows active concrete slots. `setup_initial_data.py` seeds this schedule:

- Monday: 15:30
- Tuesday: 07:00, 14:00, 15:30
- Wednesday: 15:30
- Thursday: 07:00, 14:00, 15:30
- Friday: 15:30
- Saturday: 08:00, 10:30
- Sunday: 08:30

Seeded slots are 30 minutes long by default; edit their end time in Django admin if sessions should last longer.

## Boat Categories and Seats

Boats have a name, rower seat count, optional cox requirement, color, and active flag.
A booking reserves the whole boat for one slot and must include the complete crew.

## Adding More Boats

Just add them via `/django-admin/bookings/boat/add/` or edit `setup_initial_data.py`.
