from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.http import require_POST
from datetime import date, timedelta
import hashlib
from .models import Boat, BookableSlot, Booking
from .forms import (
    AdminBookingForm,
    BookableSlotForm,
    BookingForm,
    ChangePasswordForm,
    CreateAthleteForm,
)

from collections import defaultdict


def is_admin(user):
    return user.is_staff or user.is_superuser


class ThrottledLoginView(LoginView):
    template_name = 'bookings/login.html'

    def get_client_ip(self):
        forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return self.request.META.get('REMOTE_ADDR', '')

    def get_throttle_key(self):
        username = self.request.POST.get('username', '').strip().lower()
        raw_key = f'{self.get_client_ip()}:{username}'
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        return f'login-throttle:{digest}'

    def is_locked_out(self):
        return cache.get(f'{self.get_throttle_key()}:locked')

    def get_lockout_message(self):
        minutes = max(1, settings.LOGIN_LOCKOUT_SECONDS // 60)
        return f'Too many failed login attempts. Try again in {minutes} minutes.'

    def form_invalid(self, form):
        if self.request.method == 'POST' and not getattr(self, '_skip_throttle_increment', False):
            key = self.get_throttle_key()
            attempts = cache.get(key, 0) + 1
            cache.set(key, attempts, settings.LOGIN_LOCKOUT_SECONDS)
            if attempts >= settings.LOGIN_MAX_ATTEMPTS:
                cache.set(f'{key}:locked', True, settings.LOGIN_LOCKOUT_SECONDS)
                form.add_error(None, self.get_lockout_message())
        return super().form_invalid(form)

    def form_valid(self, form):
        key = self.get_throttle_key()
        cache.delete(key)
        cache.delete(f'{key}:locked')
        return super().form_valid(form)

    def post(self, request, *args, **kwargs):
        if self.is_locked_out():
            self._skip_throttle_increment = True
            form = self.get_form_class()(request=self.request)
            form.add_error(None, self.get_lockout_message())
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)


def get_week_offset(request):
    try:
        return int(request.GET.get('week', 0))
    except ValueError:
        return 0


def build_day_sections(week_days):
    weekly_slots = BookableSlot.objects.filter(is_active=True).order_by(
        'day_of_week',
        'start_time',
        'end_time',
    )
    slots_by_day = defaultdict(list)
    for slot in weekly_slots:
        slots_by_day[slot.day_of_week].append(slot)

    return [
        {
            'date': day,
            'slots': slots_by_day[day.weekday()],
        }
        for day in week_days
    ]


# ─── Calendar ────────────────────────────────────────────────────────────────

@login_required
def calendar_view(request):
    # Determine the week to show (default: current week starting Monday)
    today = date.today()
    week_offset = get_week_offset(request)
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]

    boats = Boat.objects.all()

    bookings_qs = Booking.objects.filter(
        date__gte=week_start,
        date__lte=week_start + timedelta(days=6)
    ).select_related('athlete', 'boat').order_by('start_time')

    # Group as { (boat_id, date_str): [booking, ...] }
    booking_map = defaultdict(list)
    for b in bookings_qs:
        booking_map[(b.boat.id, str(b.date))].append(b)

    return render(request, 'bookings/calendar.html', {
        'boats': boats,
        'day_sections': build_day_sections(week_days),
        'week_days': week_days,
        'week_start': week_start,
        'week_offset': week_offset,
        'booking_map': booking_map,
        'today': today,
        'is_admin': is_admin(request.user),
    })


# ─── Booking actions ─────────────────────────────────────────────────────────

@login_required
def book_slot(request):
    if request.method == 'POST':
        form = BookingForm(request.POST, user=request.user)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.athlete = request.user
            booking.save()
            messages.success(request, f'Booked {booking.boat.name} on {booking.date} {booking.start_time:%H:%M}–{booking.end_time:%H:%M}!')
            return redirect('calendar')
        # if invalid, fall through and re-render calendar with the form errors
    else:
        # Pre-fill date/boat if passed as GET params (from clicking a day)
        initial = {
            'date': request.GET.get('date'),
            'boat': request.GET.get('boat'),
            'start_time': request.GET.get('start_time'),
            'end_time': request.GET.get('end_time'),
        }
        form = BookingForm(initial=initial, user=request.user)

    return render(request, 'bookings/book_slot.html', {'form': form, 'is_admin': is_admin(request.user)})


@login_required
@require_POST
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)

    # Only the owner or admin can cancel
    if booking.athlete != request.user and not is_admin(request.user):
        messages.error(request, 'You can only cancel your own bookings.')
        return redirect('calendar')

    if booking.date < date.today():
        messages.error(request, 'Cannot cancel past bookings.')
        return redirect('calendar')

    booking.delete()
    messages.success(request, 'Booking cancelled.')

    week_offset = request.POST.get('week_offset', 0)
    return redirect(f'/calendar/?week={week_offset}')


# ─── My Bookings ─────────────────────────────────────────────────────────────

@login_required
def my_bookings(request):
    upcoming = request.user.bookings.filter(date__gte=date.today()).order_by('date', 'start_time')
    past = request.user.bookings.filter(date__lt=date.today()).order_by('-date', 'start_time')[:10]
    return render(request, 'bookings/my_bookings.html', {
        'upcoming': upcoming,
        'past': past,
        'is_admin': is_admin(request.user),
    })


# ─── Admin: User Management ──────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def admin_users(request):
    athletes = User.objects.filter(is_superuser=False).order_by('username')
    return render(request, 'bookings/admin_users.html', {
        'athletes': athletes,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_user(request):
    if request.method == 'POST':
        form = CreateAthleteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Athlete "{form.cleaned_data["username"]}" created successfully.')
            return redirect('admin_users')
    else:
        form = CreateAthleteForm()
    return render(request, 'bookings/admin_user_form.html', {
        'form': form,
        'title': 'Create Athlete',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_change_password(request, user_id):
    athlete = get_object_or_404(User, pk=user_id, is_superuser=False)
    if request.method == 'POST':
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            athlete.set_password(form.cleaned_data['password'])
            athlete.save()
            messages.success(request, f'Password updated for {athlete.username}.')
            return redirect('admin_users')
    else:
        form = ChangePasswordForm()
    return render(request, 'bookings/admin_user_form.html', {
        'form': form,
        'title': f'Change Password for {athlete.username}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_user(request, user_id):
    athlete = get_object_or_404(User, pk=user_id, is_superuser=False)
    username = athlete.username
    athlete.delete()
    messages.success(request, f'Athlete "{username}" deleted.')
    return redirect('admin_users')


@login_required
@user_passes_test(is_admin)
def admin_slots(request):
    slots = BookableSlot.objects.all().order_by('day_of_week', 'start_time', 'end_time')
    slots_by_day = defaultdict(list)
    for slot in slots:
        slots_by_day[slot.day_of_week].append(slot)

    slot_groups = [
        {
            'day': day,
            'label': label,
            'slots': slots_by_day[day],
        }
        for day, label in BookableSlot.DAY_CHOICES
    ]

    return render(request, 'bookings/admin_slots.html', {
        'slot_groups': slot_groups,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_slot(request):
    if request.method == 'POST':
        form = BookableSlotForm(request.POST)
        if form.is_valid():
            slot = form.save()
            messages.success(request, f'Slot "{slot}" created.')
            return redirect('admin_slots')
    else:
        form = BookableSlotForm()

    return render(request, 'bookings/admin_slot_form.html', {
        'form': form,
        'title': 'Create Slot',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_edit_slot(request, slot_id):
    slot = get_object_or_404(BookableSlot, pk=slot_id)
    if request.method == 'POST':
        form = BookableSlotForm(request.POST, instance=slot)
        if form.is_valid():
            slot = form.save()
            messages.success(request, f'Slot "{slot}" updated.')
            return redirect('admin_slots')
    else:
        form = BookableSlotForm(instance=slot)

    return render(request, 'bookings/admin_slot_form.html', {
        'form': form,
        'title': f'Edit {slot}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_toggle_slot(request, slot_id):
    slot = get_object_or_404(BookableSlot, pk=slot_id)
    slot.is_active = not slot.is_active
    slot.save(update_fields=['is_active'])
    state = 'enabled' if slot.is_active else 'disabled'
    messages.success(request, f'Slot "{slot}" {state}.')
    return redirect('admin_slots')


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_slot(request, slot_id):
    slot = get_object_or_404(BookableSlot, pk=slot_id)
    label = str(slot)
    slot.delete()
    messages.success(request, f'Slot "{label}" deleted.')
    return redirect('admin_slots')


@login_required
@user_passes_test(is_admin)
def admin_all_bookings(request):
    bookings = Booking.objects.filter(date__gte=date.today()).order_by('date', 'start_time').select_related('athlete', 'boat')
    return render(request, 'bookings/admin_bookings.html', {
        'bookings': bookings,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_booking(request):
    if request.method == 'POST':
        form = AdminBookingForm(request.POST)
        if form.is_valid():
            booking = form.save()
            messages.success(
                request,
                f'Booking created for {booking.athlete.username}: {booking.boat.name} on '
                f'{booking.date} {booking.start_time:%H:%M}–{booking.end_time:%H:%M}.',
            )
            return redirect('admin_all_bookings')
    else:
        form = AdminBookingForm(initial={
            'athlete': request.GET.get('athlete'),
            'boat': request.GET.get('boat'),
            'date': request.GET.get('date'),
            'start_time': request.GET.get('start_time'),
            'end_time': request.GET.get('end_time'),
        })

    return render(request, 'bookings/admin_booking_form.html', {
        'form': form,
        'title': 'Create Booking',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_edit_booking(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related('athlete', 'boat'), pk=booking_id)
    if request.method == 'POST':
        form = AdminBookingForm(request.POST, instance=booking)
        if form.is_valid():
            booking = form.save()
            messages.success(
                request,
                f'Booking updated for {booking.athlete.username}: {booking.boat.name} on '
                f'{booking.date} {booking.start_time:%H:%M}–{booking.end_time:%H:%M}.',
            )
            return redirect('admin_all_bookings')
    else:
        form = AdminBookingForm(instance=booking)

    return render(request, 'bookings/admin_booking_form.html', {
        'form': form,
        'title': f'Edit Booking for {booking.athlete.username}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_booking(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related('athlete', 'boat'), pk=booking_id)
    label = f'{booking.athlete.username} - {booking.boat.name} on {booking.date}'
    booking.delete()
    messages.success(request, f'Booking "{label}" deleted.')
    return redirect('admin_all_bookings')
