# 🚣 Rowing Club Booking App

A simple Django web app for athletes to book coastal rowing boat sessions.

## Features

- **Athletes** can browse a weekly calendar and book/cancel time slots
- **Admin** can create athletes, change passwords, and manage all bookings
- **Multiple boats** side-by-side in a single calendar view
- No self-registration — admin controls all accounts

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

### 4. Create boats + admin user
```bash
python setup_initial_data.py
```
This creates:
- Starter boats from `setup_initial_data.py`
- Admin user `admin`

Set `ADMIN_PASSWORD` before running the script to choose the initial password.
If it is not set, the script generates and prints a one-time password.

### 5. Run the dev server
```bash
python manage.py runserver
```

Open http://localhost:8000 and log in as `admin`.

---

## Admin Tasks

### Create an athlete
1. Log in as admin
2. Go to **Athletes** in the nav
3. Click **+ Add Athlete**, fill in username and password

### Change boat names/colors
Use Django's built-in admin panel at `/django-admin/` or edit `setup_initial_data.py`.

---

## Deploying to Render (free tier)

1. Push this folder to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Render will auto-detect `render.yaml` and configure the build
5. After first deploy, open the Render **Shell** and run:
   ```bash
   python setup_initial_data.py
   ```

> **SQLite note**: Render's free tier has an ephemeral disk — your SQLite data
> will reset on each deploy. For a persistent club app, either:
> - Add a Render **Disk** (paid), or
> - Switch to PostgreSQL (Render provides a free PG instance — just change `DATABASES` in `settings.py`)

---

## Customising Calendar Slots

Edit the slot constants in `bookings/views.py`. Bookings themselves store `start_time` and `end_time`.

## Boat Categories and Seats

Boats have a category such as `1xC`, `2xC`, `2x`, `4x`, or `4+`, plus a seat count. Multiple athletes can book the same boat at overlapping times until all seats are full.

## Adding More Boats

Just add them via `/django-admin/bookings/boat/add/` or edit `setup_initial_data.py`.
