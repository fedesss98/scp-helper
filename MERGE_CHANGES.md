# Django Race Scraper and Telegram Merge

This document explains the merge that moved the former FastAPI scraper API and
Telegram bot into the Django project.

## Summary

The project now has one Django runtime and one shared database. Race data,
subscriptions, and Telegram notification state are no longer stored in the old
bot SQLite database or served through the old FastAPI API.

The old `fic-scraper/` folder has been replaced by Django apps and a worker:

- `races/`: race models, scraper, sync helpers, views, templates, and management command.
- `accounts/`: user profile data, including Telegram chat/user fields.
- `notifications/`: Telegram send helpers.
- `bot/run_bot.py`: standalone Django-aware worker.

## New Django Apps

### `accounts`

Adds `UserProfile`, linked one-to-one with Django `auth.User`.

Fields:

- `telegram_chat_id`
- `telegram_username`
- `phone`

A `post_save` signal creates a profile automatically when a user is created.
The profile is editable inline from the Django User admin page.

### `races`

Adds the race domain model:

- `Race`: canottaggioservice regatta, keyed by `external_id`.
- `RaceResult`: published result rows, keyed by deterministic `external_id`.
- `RaceSubscription`: user subscriptions to races, unique per `(user, race)`.

The app also adds logged-in pages under `/races/`:

- `/races/`: upcoming race calendar with subscribe/unsubscribe actions.
- `/races/<external_id>/`: race detail page with program and results.

The race detail page has two program modes:

- **Programma SCP**: default view. Shows only races where at least one program
  row has club `PALERMO SC` and highlights the matching row.
- **Programma Completo**: full saved program for the regatta.

The target club is configurable with `RACE_CLUB_NAME`, defaulting to
`PALERMO SC`. The short UI label is configurable with `RACE_CLUB_SHORT_NAME`,
defaulting to `SCP`.

All new templates extend `bookings/base.html` and share the existing navigation
and visual style.

### `notifications`

Adds Telegram notification utilities:

- `send_telegram(chat_id, message)`: sends with plain `requests`.
- `notify_new_results(race, new_results)`: sends one formatted notification to
  every subscriber of a race who has `profile.telegram_chat_id`.

## Scraper Changes

The FastAPI service layer was converted into framework-free scraper code in
`races/scraper.py`.

Preserved behavior includes:

- canottaggioservice base URL and consent-cookie bootstrap.
- ISO-8859-1 response encoding.
- BeautifulSoup/lxml parsing.
- calendar scraping from `calendario.php` and `menu_nazionali_cal.php`.
- program discovery and priority ordering.
- result parsing, including finishers, clubs, athletes, bibs, lanes, status,
  and guest clubs.
- live-race parsing.

The scraper exposes plain Python methods and helper functions. It has no
FastAPI, uvicorn, SQLAlchemy, aiosqlite, or APScheduler dependency.

## Database Sync

`races/sync.py` is the shared persistence layer for ingestion.

It uses Django ORM `update_or_create` for idempotency:

- `Race.external_id` is the lookup key for races.
- `RaceResult.external_id` is the lookup key for result rows.

`RaceResult.external_id` is built deterministically from the regatta ID, result
source, race number, bib/lane/club, event, phase, and athletes. This lets the
management command and worker run repeatedly without duplicate results.

## Management Command

Run:

```bash
python manage.py scrape_races
```

Useful options:

```bash
python manage.py scrape_races --season 2026
python manage.py scrape_races --skip-program
python manage.py scrape_races --skip-results
python manage.py scrape_races --all
python manage.py scrape_races --limit 10
```

The command syncs calendar rows first, then hydrates upcoming races with program
and result data when those upstream pages are available.

## Telegram Worker

Run:

```bash
python bot/run_bot.py
```

The worker calls `django.setup()` at startup, then polls every 180 seconds by
default.

Each cycle:

1. Finds races with at least one `RaceSubscription` and `date >= today`.
2. Fetches fresh results through `races/scraper.py`.
3. Saves new result rows with `update_or_create`.
4. Sends Telegram notifications for newly created result rows matching the
   configured club, defaulting to `PALERMO SC`.
5. Catches exceptions per race so one upstream failure does not stop the loop.

If `TELEGRAM_BOT_TOKEN` is configured and `aiogram` is installed, the same
script also starts simple command handlers:

- `/start`
- `/status`
- `/calendar`
- `/subscribe <reg_id>`
- `/unsubscribe <reg_id>`
- `/stop`

The command handlers use Django users and `UserProfile`, not the old SQLite bot
subscription tables.

## Settings and Deployment

`vogapp/settings.py` now includes:

- `accounts`
- `races`
- `notifications`
- `TELEGRAM_BOT_TOKEN`
- `SCRAPER_POLL_INTERVAL = 180`

`vogapp/urls.py` now includes:

```python
path('races/', include('races.urls'))
```

`Procfile` now includes:

```text
worker: python bot/run_bot.py
```

`requirements.txt` keeps scraper and Telegram command dependencies and removes
FastAPI-specific runtime needs:

- kept: `httpx`, `beautifulsoup4`, `lxml`, `requests`
- kept: `aiogram` because command handlers still exist
- removed/not required: `fastapi`, `uvicorn`, `sqlalchemy`, `aiosqlite`,
  `apscheduler`

## What Happened to `fic-scraper/`

The Django project no longer imports or depends on `fic-scraper/`.

The folder can be deleted after you are comfortable that the new Django scraper
and worker cover your production needs. Keeping it temporarily can still be
useful as a historical reference for old tests and fixtures.

## Verification Performed

The new migration files were generated:

- `accounts/migrations/0001_initial.py`
- `races/migrations/0001_initial.py`

Checks run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

Both passed with the project virtual environment.

The full existing test suite currently has unrelated legacy failures in booking
tests and email-copy assertions. Those failures predate this merge path:

- several booking tests use June 1, 2026 slots, which are now past as of June 4, 2026;
- email tests expect old `SCP Helper` copy while templates currently render `VogApp`.
