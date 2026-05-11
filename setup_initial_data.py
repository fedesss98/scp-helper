"""
Run this once after first deploy to set up boats and create the admin user.
Usage: python setup_initial_data.py
"""

import os
import secrets
import django
from datetime import datetime, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vogapp.settings")
django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from bookings.models import Boat, BookableSlot


# ── Create boats ──────────────────────────────────────────────────────────────
boats_data = [
    {
        "name": "Salani",
        "category": Boat.CATEGORY_SINGLE_COASTAL,
        "seats": 1,
        "description": "Singolo Coastal Rowing",
        "color": "#2196F3",
    },
    {
        "name": "Filippi",
        "category": Boat.CATEGORY_SINGLE_COASTAL,
        "seats": 1,
        "description": "Singolo Coastal Rowing",
        "color": "#F0A500",
    },
    {
        "name": "Coastal Double",
        "category": Boat.CATEGORY_DOUBLE_COASTAL,
        "seats": 2,
        "description": "Doppio Coastal Rowing",
        "color": "#2E7D32",
    },
]

for data in boats_data:
    boat, created = Boat.objects.get_or_create(name=data["name"], defaults=data)
    print(f"{'Created' if created else 'Already exists'}: {boat.name}")

# ── Create weekly bookable slots ─────────────────────────────────────────────
DEFAULT_SLOT_MINUTES = 90


def add_minutes(value, minutes):
    cursor = datetime.combine(datetime.today(), value)
    return (cursor + timedelta(minutes=minutes)).time()


weekly_slots = {
    BookableSlot.MONDAY: ["15:30"],
    BookableSlot.TUESDAY: ["07:00", "14:00", "15:30"],
    BookableSlot.WEDNESDAY: ["15:30"],
    BookableSlot.THURSDAY: ["07:00", "14:00", "15:30"],
    BookableSlot.FRIDAY: ["15:30"],
    BookableSlot.SATURDAY: ["08:00", "10:30"],
    BookableSlot.SUNDAY: ["08:30"],
}

for day_of_week, starts in weekly_slots.items():
    for start_text in starts:
        start = datetime.strptime(start_text, "%H:%M").time()
        end = add_minutes(start, DEFAULT_SLOT_MINUTES)
        slot, created = BookableSlot.objects.get_or_create(
            day_of_week=day_of_week,
            start_time=start,
            end_time=end,
            defaults={"is_active": True},
        )
        print(f"{'Created' if created else 'Already exists'}: {slot}")

# ── Create admin user ─────────────────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
admin_exists = User.objects.filter(username=ADMIN_USERNAME).exists()

if not admin_exists and not ADMIN_PASSWORD:
    if settings.DEBUG:
        ADMIN_PASSWORD = secrets.token_urlsafe(16)
    else:
        raise RuntimeError(
            "Set ADMIN_PASSWORD before creating the production admin user."
        )

if not admin_exists:
    User.objects.create_superuser(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"Created admin user: {ADMIN_USERNAME}")
    if settings.DEBUG and "ADMIN_PASSWORD" not in os.environ:
        print(f"Generated one-time admin password: {ADMIN_PASSWORD}")
    print("IMPORTANT: Change the admin password after first login.")
else:
    print(f"Admin user '{ADMIN_USERNAME}' already exists.")

print("\nDone! Run: python manage.py runserver")
