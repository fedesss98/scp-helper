from collections import defaultdict
from datetime import date, timedelta
import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AdminBookingForm, AthleteForm, BookingForm, SlotBatchForm, SlotForm
from .models import Athlete, Boat, Booking, Slot
from .notifications import notify_booking_event, notify_new_booking, snapshot_booking


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


def get_user_athlete(user):
    if not user.is_authenticated:
        return None
    return getattr(user, 'athlete_profile', None)


def booking_queryset():
    return Booking.objects.select_related('slot', 'boat', 'created_by').prefetch_related('crew')


def build_day_sections(week_days):
    slots = Slot.objects.filter(
        is_active=True,
        date__gte=week_days[0],
        date__lte=week_days[-1],
    ).select_related('workout').order_by('date', 'start_time', 'end_time')
    slots_by_day = defaultdict(list)
    for slot in slots:
        slots_by_day[slot.date].append(slot)

    return [
        {
            'date': day,
            'slots': slots_by_day[day],
        }
        for day in week_days
    ]


@login_required
def calendar_view(request):
    today = date.today()
    week_offset = get_week_offset(request)
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]

    boats = Boat.objects.filter(is_active=True)
    bookings_qs = booking_queryset().filter(
        slot__date__gte=week_start,
        slot__date__lte=week_start + timedelta(days=6),
    )

    booking_map = {
        (booking.boat_id, booking.slot_id): booking
        for booking in bookings_qs
    }

    return render(request, 'bookings/calendar.html', {
        'boats': boats,
        'day_sections': build_day_sections(week_days),
        'week_days': week_days,
        'week_start': week_start,
        'week_offset': week_offset,
        'booking_map': booking_map,
        'today': today,
        'current_athlete': get_user_athlete(request.user),
        'is_admin': is_admin(request.user),
    })


@login_required
def book_slot(request):
    if request.method == 'POST':
        form = BookingForm(request.POST, user=request.user)
        if form.is_valid():
            booking = form.save()
            transaction.on_commit(lambda booking=booking: notify_new_booking(booking))
            messages.success(request, f'Prenotazione creata: {booking.boat.name} - {booking.slot}.')
            return redirect('calendar')
    else:
        form = BookingForm(initial={
            'slot': request.GET.get('slot'),
            'boat': request.GET.get('boat'),
        }, user=request.user)

    return render(request, 'bookings/book_slot.html', {
        'form': form,
        'is_admin': is_admin(request.user),
    })


@login_required
@require_POST
def cancel_booking(request, booking_id):
    booking = get_object_or_404(booking_queryset(), pk=booking_id)
    previous_booking = snapshot_booking(booking)
    current_athlete = get_user_athlete(request.user)

    if not is_admin(request.user) and current_athlete not in booking.crew.all():
        messages.error(request, 'Puoi cancellare solo le tue prenotazioni.')
        return redirect('calendar')

    if booking.slot.date < date.today():
        messages.error(request, 'Non puoi cancellare prenotazioni passate.')
        return redirect('calendar')

    booking.delete()
    transaction.on_commit(
        lambda booking=booking, previous_booking=previous_booking: notify_booking_event(
            booking,
            'cancelled',
            previous_booking,
        )
    )
    messages.success(request, 'Prenotazione cancellata.')

    week_offset = request.POST.get('week_offset', 0)
    return redirect(f'/calendar/?week={week_offset}')


@login_required
def my_bookings(request):
    athlete = get_user_athlete(request.user)
    if athlete:
        base_qs = booking_queryset().filter(crew=athlete).distinct()
        upcoming = list(base_qs.filter(slot__date__gte=date.today()).order_by('slot__date', 'slot__start_time'))
        past = list(base_qs.filter(slot__date__lt=date.today()).order_by('-slot__date', 'slot__start_time')[:10])
    else:
        upcoming = []
        past = []
    return render(request, 'bookings/my_bookings.html', {
        'upcoming': upcoming,
        'past': past,
        'is_admin': is_admin(request.user),
    })


@login_required
@user_passes_test(is_admin)
def admin_athletes(request):
    athletes = Athlete.objects.select_related('user').order_by('last_name', 'first_name')
    return render(request, 'bookings/admin_athletes.html', {
        'athletes': athletes,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_athlete(request):
    if request.method == 'POST':
        form = AthleteForm(request.POST)
        if form.is_valid():
            athlete = form.save()
            messages.success(request, f'Atleta "{athlete.full_name}" creato.')
            return redirect('admin_athletes')
    else:
        form = AthleteForm()
    return render(request, 'bookings/admin_athlete_form.html', {
        'form': form,
        'title': 'Crea Atleta',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_edit_athlete(request, athlete_id):
    athlete = get_object_or_404(Athlete, pk=athlete_id)
    if request.method == 'POST':
        form = AthleteForm(request.POST, instance=athlete)
        if form.is_valid():
            athlete = form.save()
            messages.success(request, f'Atleta "{athlete.full_name}" aggiornato.')
            return redirect('admin_athletes')
    else:
        form = AthleteForm(instance=athlete)
    return render(request, 'bookings/admin_athlete_form.html', {
        'form': form,
        'title': f'Modifica {athlete.full_name}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_athlete(request, athlete_id):
    athlete = get_object_or_404(Athlete, pk=athlete_id)
    label = athlete.full_name
    try:
        athlete.delete()
    except ProtectedError:
        messages.error(request, f'Non puoi eliminare "{label}" perche ha prenotazioni collegate.')
    else:
        messages.success(request, f'Atleta "{label}" eliminato.')
    return redirect('admin_athletes')


@login_required
@user_passes_test(is_admin)
def admin_slots(request):
    slots = Slot.objects.select_related('workout').order_by('date', 'start_time', 'end_time')
    slots_by_day = defaultdict(list)
    for slot in slots:
        slots_by_day[slot.date].append(slot)

    slot_groups = [
        {
            'date': slot_date,
            'label': slot_date,
            'slots': day_slots,
        }
        for slot_date, day_slots in sorted(slots_by_day.items())
    ]

    return render(request, 'bookings/admin_slots.html', {
        'slot_groups': slot_groups,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_slot(request):
    mode = request.GET.get('mode')
    if request.method == 'POST':
        if request.POST.get('create_mode') == 'batch':
            batch_form = SlotBatchForm(request.POST, prefix='batch')
            slot_form = SlotForm(prefix='single')
            if batch_form.is_valid():
                batch = batch_form.save()
                created_slots = batch.create_slots()
                messages.success(request, f'Creati {len(created_slots)} slot.')
                return redirect('admin_slots')
        else:
            slot_form = SlotForm(request.POST, prefix='single')
            batch_form = SlotBatchForm(prefix='batch')
            if slot_form.is_valid():
                slot = slot_form.save()
                messages.success(request, f'Slot "{slot}" creato.')
                return redirect('admin_slots')
    else:
        slot_form = SlotForm(prefix='single')
        batch_form = SlotBatchForm(prefix='batch')

    return render(request, 'bookings/admin_slot_form.html', {
        'form': batch_form if mode == 'batch' else slot_form,
        'single_form': slot_form,
        'batch_form': batch_form,
        'title': 'Crea Slot',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_edit_slot(request, slot_id):
    slot = get_object_or_404(Slot, pk=slot_id)
    if request.method == 'POST':
        form = SlotForm(request.POST, instance=slot)
        if form.is_valid():
            slot = form.save()
            messages.success(request, f'Slot "{slot}" aggiornato.')
            return redirect('admin_slots')
    else:
        form = SlotForm(instance=slot)

    return render(request, 'bookings/admin_slot_form.html', {
        'form': form,
        'title': f'Modifica {slot}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_toggle_slot(request, slot_id):
    slot = get_object_or_404(Slot, pk=slot_id)
    slot.is_active = not slot.is_active
    slot.save(update_fields=['is_active'])
    state = 'attivo' if slot.is_active else 'nascosto'
    messages.success(request, f'Slot "{slot}" {state}.')
    return redirect('admin_slots')


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_slot(request, slot_id):
    slot = get_object_or_404(Slot, pk=slot_id)
    label = str(slot)
    slot.delete()
    messages.success(request, f'Slot "{label}" eliminato.')
    return redirect('admin_slots')


@login_required
@user_passes_test(is_admin)
def admin_all_bookings(request):
    bookings = booking_queryset().filter(slot__date__gte=date.today()).order_by('slot__date', 'slot__start_time')
    return render(request, 'bookings/admin_bookings.html', {
        'bookings': bookings,
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_create_booking(request):
    if request.method == 'POST':
        form = AdminBookingForm(request.POST, user=request.user)
        if form.is_valid():
            booking = form.save()
            transaction.on_commit(lambda booking=booking: notify_new_booking(booking))
            messages.success(request, f'Prenotazione creata: {booking.boat.name} - {booking.slot}.')
            return redirect('admin_all_bookings')
    else:
        form = AdminBookingForm(initial={
            'slot': request.GET.get('slot'),
            'boat': request.GET.get('boat'),
        }, user=request.user)

    return render(request, 'bookings/admin_booking_form.html', {
        'form': form,
        'title': 'Crea Prenotazione',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
def admin_edit_booking(request, booking_id):
    booking = get_object_or_404(booking_queryset(), pk=booking_id)
    if request.method == 'POST':
        previous_booking = snapshot_booking(booking)
        form = AdminBookingForm(request.POST, instance=booking, user=request.user)
        if form.is_valid():
            booking = form.save()
            transaction.on_commit(
                lambda booking=booking, previous_booking=previous_booking: notify_booking_event(
                    booking,
                    'updated',
                    previous_booking,
                )
            )
            messages.success(request, f'Prenotazione aggiornata: {booking.boat.name} - {booking.slot}.')
            return redirect('admin_all_bookings')
    else:
        form = AdminBookingForm(instance=booking, user=request.user)

    return render(request, 'bookings/admin_booking_form.html', {
        'form': form,
        'title': f'Modifica Prenotazione {booking.boat.name}',
        'is_admin': True,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_booking(request, booking_id):
    booking = get_object_or_404(booking_queryset(), pk=booking_id)
    previous_booking = snapshot_booking(booking)
    label = f'{booking.boat.name} - {booking.slot}'
    booking.delete()
    transaction.on_commit(
        lambda booking=booking, previous_booking=previous_booking: notify_booking_event(
            booking,
            'cancelled',
            previous_booking,
        )
    )
    messages.success(request, f'Prenotazione "{label}" eliminata.')
    return redirect('admin_all_bookings')
