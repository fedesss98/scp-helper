"""
Run this once after first deploy to set up boats, workouts, slots, and admin user.
Usage: python setup_initial_data.py
"""

import os
import secrets
from datetime import date, datetime, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vogapp.settings")
django.setup()

from django.conf import settings
from django.contrib.auth.models import User

from bookings.models import Boat, SlotBatch, Workout


workout_names = [
    "Tecnica",
    "S&C",
    "4x3000 rest 10'",
    "Fondo facile",
    "Sprint",
]

workouts = {}
for name in workout_names:
    workout, created = Workout.objects.get_or_create(name=name)
    workouts[name] = workout
    print(f"{'Created' if created else 'Already exists'} workout: {workout.name}")

boats_data = [
    {
        "name": "Salani",
        "rower_seats": 1,
        "requires_cox": False,
        "description": "Singolo Coastal Rowing",
        "color": "#2196F3",
    },
    {
        "name": "Filippi",
        "rower_seats": 1,
        "requires_cox": False,
        "description": "Singolo Coastal Rowing",
        "color": "#F0A500",
    },
    {
        "name": "Coastal Double",
        "rower_seats": 2,
        "requires_cox": False,
        "description": "Doppio Coastal Rowing",
        "color": "#2E7D32",
    },
]

for data in boats_data:
    boat, created = Boat.objects.get_or_create(name=data["name"], defaults=data)
    print(f"{'Created' if created else 'Already exists'}: {boat.name}")

# ── Create weekly bookable slots ─────────────────────────────────────────────
DEFAULT_SLOT_MINUTES = 90


def month_range(start):
    first = start.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1)
    else:
        next_month = first.replace(month=first.month + 1)
    return first, next_month - timedelta(days=1)


this_month_start, this_month_end = month_range(date.today())
weekly_slots = [
    (SlotBatch.MONDAY, "15:30", "17:00", workouts["Tecnica"]),
    (SlotBatch.TUESDAY, "07:00", "08:30", workouts["Fondo facile"]),
    (SlotBatch.TUESDAY, "14:00", "15:30", workouts["S&C"]),
    (SlotBatch.TUESDAY, "15:30", "17:00", workouts["4x3000 rest 10'"]),
    (SlotBatch.WEDNESDAY, "15:30", "17:00", workouts["Tecnica"]),
    (SlotBatch.THURSDAY, "07:00", "08:30", workouts["Fondo facile"]),
    (SlotBatch.THURSDAY, "14:00", "15:30", workouts["S&C"]),
    (SlotBatch.THURSDAY, "15:30", "17:00", workouts["4x3000 rest 10'"]),
    (SlotBatch.FRIDAY, "15:30", "17:00", workouts["Sprint"]),
    (SlotBatch.SATURDAY, "08:00", "09:30", workouts["Fondo facile"]),
    (SlotBatch.SATURDAY, "10:30", "12:00", workouts["Tecnica"]),
    (SlotBatch.SUNDAY, "08:30", "10:00", workouts["Fondo facile"]),
]

for weekday, start_text, end_text, workout in weekly_slots:
    start = datetime.strptime(start_text, "%H:%M").time()
    end = datetime.strptime(end_text, "%H:%M").time()
    batch = SlotBatch.objects.create(
        day_of_week=weekday,
        start_date=this_month_start,
        end_date=this_month_end,
        start_time=start,
        end_time=end,
        workout=workout,
    )
    created_slots = batch.create_slots()
    print(f"Created {len(created_slots)} slots from batch: {batch}")


ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
admin_exists = User.objects.filter(username=ADMIN_USERNAME).exists()

if not admin_exists and not ADMIN_PASSWORD:
    if settings.DEBUG:
        ADMIN_PASSWORD = secrets.token_urlsafe(16)
    else:
        raise RuntimeError("Set ADMIN_PASSWORD before creating the production admin user.")

if not admin_exists:
    User.objects.create_superuser(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"Created admin user: {ADMIN_USERNAME}")
    if settings.DEBUG and "ADMIN_PASSWORD" not in os.environ:
        print(f"Generated one-time admin password: {ADMIN_PASSWORD}")
    print("IMPORTANT: Change the admin password after first login.")
else:
    print(f"Admin user '{ADMIN_USERNAME}' already exists.")

print("\nDone! Run: python manage.py runserver")
