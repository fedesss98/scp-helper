from datetime import date, time

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import AthleteForm, BookingForm, SlotBatchForm, SlotForm
from .models import (
    Athlete,
    Boat,
    Booking,
    BookingCrewMember,
    Slot,
    SlotBatch,
    SlotBatchSlot,
    Workout,
)
from .notifications import notify_booking_event, notify_new_booking, snapshot_booking


class DomainFactoryMixin:
    def create_athlete(self, name, **kwargs):
        first_name, _, last_name = name.partition(' ')
        return Athlete.objects.create(
            first_name=first_name,
            last_name=last_name or 'Example',
            **kwargs,
        )

    def create_slot(self, **kwargs):
        defaults = {
            'date': date(2026, 6, 1),
            'start_time': time(9, 0),
            'end_time': time(10, 0),
        }
        defaults.update(kwargs)
        return Slot.objects.create(**defaults)

    def create_booking(self, *, boat, slot, rowers, cox=None, created_by=None):
        booking = Booking.objects.create(boat=boat, slot=slot, created_by=created_by)
        for index, athlete in enumerate(rowers, start=1):
            BookingCrewMember.objects.create(
                booking=booking,
                athlete=athlete,
                role=BookingCrewMember.ROLE_ROWER,
                seat_number=index,
            )
        if cox:
            BookingCrewMember.objects.create(
                booking=booking,
                athlete=cox,
                role=BookingCrewMember.ROLE_COX,
            )
        return booking


class SlotBatchTests(TestCase):
    def test_batch_creates_concrete_slots_for_matching_weekdays(self):
        workout = Workout.objects.create(name='4x3000 rest 10')
        batch = SlotBatch.objects.create(
            day_of_week=SlotBatch.WEDNESDAY,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            start_time=time(11, 0),
            end_time=time(13, 0),
            workout=workout,
        )

        created_slots = batch.create_slots()

        self.assertEqual(len(created_slots), 4)
        self.assertEqual(SlotBatchSlot.objects.filter(batch=batch).count(), 4)
        self.assertTrue(Slot.objects.filter(date=date(2026, 6, 3), workout=workout).exists())
        self.assertTrue(all(slot.start_time == time(11, 0) for slot in created_slots))

    def test_batch_updates_linked_slots_together(self):
        workout = Workout.objects.create(name='Tecnica')
        updated_workout = Workout.objects.create(name='Sprint')
        batch = SlotBatch.objects.create(
            day_of_week=SlotBatch.WEDNESDAY,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            start_time=time(11, 0),
            end_time=time(13, 0),
            workout=workout,
        )
        batch.create_slots()

        updated = batch.update_linked_slots(
            start_time=time(12, 0),
            end_time=time(14, 0),
            workout=updated_workout,
            is_active=False,
        )

        self.assertEqual(updated, 4)
        self.assertEqual(
            Slot.objects.filter(start_time=time(12, 0), workout=updated_workout, is_active=False).count(),
            4,
        )


class SlotTimeFormTests(TestCase):
    def test_slot_forms_use_24_hour_selects_for_times(self):
        for form in (SlotForm(), SlotBatchForm()):
            for field_name in ('start_time', 'end_time'):
                field = form.fields[field_name]
                rendered_field = form[field_name].as_widget()
                self.assertEqual(field.widget.__class__.__name__, 'Select')
                self.assertIn(('13:00', '13:00'), list(field.widget.choices))
                self.assertNotIn('AM', rendered_field)
                self.assertNotIn('PM', rendered_field)
                self.assertNotIn('type="time"', rendered_field)


class AthleteFormTests(TestCase):
    def test_athlete_form_creates_athlete_without_creating_user(self):
        form = AthleteForm(data={
            'first_name': 'Mario',
            'last_name': 'Rossi',
            'date_of_birth': '01/01/2000',
            'sex': Athlete.SEX_MALE,
            'is_active': 'on',
        })

        self.assertTrue(form.is_valid(), form.errors)
        athlete = form.save()

        self.assertEqual(athlete.full_name, 'Mario Rossi')
        self.assertEqual(athlete.date_of_birth, date(2000, 1, 1))
        self.assertEqual(athlete.sex, Athlete.SEX_MALE)
        self.assertIsNone(athlete.user)
        self.assertEqual(User.objects.count(), 0)

    def test_athlete_form_renders_date_of_birth_in_italian_format(self):
        athlete = Athlete(first_name='Mario', last_name='Rossi', date_of_birth=date(2000, 1, 31))
        form = AthleteForm(instance=athlete)
        rendered_field = str(form['date_of_birth'])

        self.assertIn('value="31/01/2000"', rendered_field)
        self.assertIn('placeholder="dd/mm/yyyy"', rendered_field)
        self.assertNotIn('type="date"', rendered_field)

    def test_athlete_form_can_link_existing_user(self):
        user = User.objects.create_user(username='coach', first_name='Alice', last_name='Bianchi')
        form = AthleteForm(data={
            'first_name': 'Alice',
            'last_name': 'Bianchi',
            'is_active': 'on',
            'user': user.id,
        })

        self.assertTrue(form.is_valid(), form.errors)
        athlete = form.save()

        self.assertEqual(athlete.user, user)


class BookingCrewValidationTests(DomainFactoryMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='password123')
        self.alice = self.create_athlete('Alice Example', user=self.user)
        self.bob = self.create_athlete('Bob Example')
        self.cara = self.create_athlete('Cara Example')
        self.cox = self.create_athlete('Cox Example')
        self.slot = self.create_slot()
        self.other_slot = self.create_slot(date=date(2026, 6, 2))
        self.double = Boat.objects.create(name='Double', rower_seats=2)
        self.four_plus = Boat.objects.create(name='Four Plus', rower_seats=4, requires_cox=True)

    def form_for(self, **overrides):
        payload = {
            'slot': self.slot.id,
            'boat': self.double.id,
            'rower_1': self.alice.id,
            'rower_2': self.bob.id,
        }
        payload.update(overrides)
        return BookingForm(data=payload, user=self.user)

    def test_complete_booking_creates_crew_links(self):
        form = self.form_for()

        self.assertTrue(form.is_valid(), form.errors)
        booking = form.save()

        self.assertEqual(booking.crew.count(), 2)
        self.assertEqual(booking.created_by, self.user)
        self.assertEqual(
            list(booking.crew_links.order_by('seat_number').values_list('athlete', flat=True)),
            [self.alice.id, self.bob.id],
        )

    def test_rejects_incomplete_crew(self):
        form = self.form_for(rower_2='')

        self.assertFalse(form.is_valid())
        self.assertIn('rower_2', form.errors)

    def test_rejects_duplicate_athlete_in_same_booking(self):
        form = self.form_for(rower_2=self.alice.id)

        self.assertFalse(form.is_valid())
        self.assertIn('same athlete', str(form.errors))

    def test_rejects_boat_already_booked_for_slot(self):
        self.create_booking(boat=self.double, slot=self.slot, rowers=[self.alice, self.bob])

        form = self.form_for(rower_1=self.cara.id)

        self.assertFalse(form.is_valid())
        self.assertIn('already booked', str(form.errors))

    def test_rejects_athlete_already_booked_in_same_slot(self):
        other_boat = Boat.objects.create(name='Other Double', rower_seats=2)
        self.create_booking(boat=other_boat, slot=self.slot, rowers=[self.alice, self.bob])

        form = self.form_for(rower_1=self.alice.id, rower_2=self.cara.id)

        self.assertFalse(form.is_valid())
        self.assertIn('already booked in this slot', str(form.errors))

    def test_coxed_boat_requires_rowers_and_cox(self):
        payload = {
            'slot': self.other_slot.id,
            'boat': self.four_plus.id,
            'rower_1': self.alice.id,
            'rower_2': self.bob.id,
            'rower_3': self.cara.id,
            'rower_4': self.create_athlete('Dan Example').id,
            'cox': self.cox.id,
        }
        form = BookingForm(data=payload, user=self.user)

        self.assertEqual(form.fields['cox'].label, 'Timoniere')
        self.assertTrue(form.is_valid(), form.errors)
        booking = form.save()

        self.assertEqual(booking.crew.count(), 5)
        self.assertEqual(booking.cox(), self.cox)
        self.assertEqual(
            [member.display_name for member in booking.crew_members()],
            [
                '1 Alice Example',
                '2 Bob Example',
                '3 Cara Example',
                '4 Dan Example',
                'Tim. Cox Example',
            ],
        )


@override_settings(
    BOOKING_NOTIFICATION_EXTRA_RECIPIENTS=['club@example.com'],
    DEFAULT_FROM_EMAIL='bookings@example.com',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    WELCOME_EMAIL_ENABLED=False,
)
class BookingNotificationTests(DomainFactoryMixin, TestCase):
    def assert_has_html_alternative(self, message, expected_text):
        self.assertEqual(len(message.alternatives), 1)
        html, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn(expected_text, html)
        return html

    def test_notify_new_booking_sends_email_to_staff_and_linked_crew_users(self):
        User.objects.create_user(username='coach', email='coach@example.com', is_staff=True)
        alice_user = User.objects.create_user(username='alice', email='alice@example.com')
        alice = self.create_athlete('Alice Example', user=alice_user)
        bob = self.create_athlete('Bob Example')
        boat = Boat.objects.create(name='Double', rower_seats=2)
        slot = self.create_slot()
        booking = self.create_booking(boat=boat, slot=slot, rowers=[alice, bob])

        sent = notify_new_booking(booking)

        self.assertTrue(sent)
        self.assertEqual(mail.outbox[0].to, ['coach@example.com', 'alice@example.com', 'club@example.com'])
        self.assertIn('Prenotazione creata: Double il 2026-06-01', mail.outbox[0].subject)
        self.assertIn('Equipaggio: Alice Example, Bob Example', mail.outbox[0].body)
        html = self.assert_has_html_alternative(mail.outbox[0], 'Prenotazione creata')
        self.assertIn('Equipaggio', html)
        self.assertIn('Alice Example, Bob Example', html)

    def test_notify_cancelled_booking_uses_snapshot(self):
        alice = self.create_athlete('Alice Example')
        boat = Boat.objects.create(name='Single', rower_seats=1)
        slot = self.create_slot()
        booking = self.create_booking(boat=boat, slot=slot, rowers=[alice])
        snapshot = snapshot_booking(booking)

        sent = notify_booking_event(booking, 'cancelled', snapshot)

        self.assertTrue(sent)
        self.assertIn('Prenotazione cancellata:', mail.outbox[0].body)
        self.assertIn('Equipaggio: Alice Example', mail.outbox[0].body)
        html = self.assert_has_html_alternative(mail.outbox[0], 'Prenotazione cancellata')
        self.assertIn('Single', html)
        self.assertIn('Alice Example', html)

    def test_notify_updated_booking_includes_current_and_previous_details(self):
        alice = self.create_athlete('Alice Example')
        bob = self.create_athlete('Bob Example')
        boat = Boat.objects.create(name='Double', rower_seats=2)
        slot = self.create_slot()
        booking = self.create_booking(boat=boat, slot=slot, rowers=[alice])
        snapshot = snapshot_booking(booking)
        BookingCrewMember.objects.create(
            booking=booking,
            athlete=bob,
            role=BookingCrewMember.ROLE_ROWER,
            seat_number=2,
        )

        sent = notify_booking_event(booking, 'updated', snapshot)

        self.assertTrue(sent)
        self.assertIn('Prenotazione modificata: Double il 2026-06-01', mail.outbox[0].subject)
        self.assertIn('Prenotazione corrente:', mail.outbox[0].body)
        self.assertIn('Prenotazione precedente:', mail.outbox[0].body)
        self.assertIn('Equipaggio: Alice Example, Bob Example', mail.outbox[0].body)
        self.assertIn('Equipaggio: Alice Example', mail.outbox[0].body)
        html = self.assert_has_html_alternative(mail.outbox[0], 'Prenotazione modificata')
        self.assertIn('Prenotazione corrente', html)
        self.assertIn('Prenotazione precedente', html)


@override_settings(
    DEFAULT_FROM_EMAIL='bookings@example.com',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    WELCOME_EMAIL_ENABLED=True,
)
class WelcomeEmailTests(TransactionTestCase):
    reset_sequences = True

    def assert_has_html_alternative(self, message, expected_text):
        self.assertEqual(len(message.alternatives), 1)
        html, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn(expected_text, html)
        return html

    def test_creating_user_with_email_sends_welcome_email(self):
        user = User.objects.create_user(
            username='newmember',
            email='newmember@example.com',
            password='password123',
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Benvenuto in SCP Helper')
        self.assertEqual(mail.outbox[0].to, ['newmember@example.com'])
        self.assertIn(user.get_username(), mail.outbox[0].body)
        html = self.assert_has_html_alternative(mail.outbox[0], 'Benvenuto in SCP Helper')
        self.assertIn(user.get_username(), html)

    def test_creating_user_without_email_does_not_send_welcome_email(self):
        User.objects.create_user(username='nomail', password='password123')

        self.assertEqual(len(mail.outbox), 0)


class BookingViewsTests(DomainFactoryMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='password123')
        self.alice = self.create_athlete('Alice Example', user=self.user)
        self.bob = self.create_athlete('Bob Example')
        self.boat = Boat.objects.create(name='Double', rower_seats=2)
        self.slot = self.create_slot(date=date.today())
        self.booking = self.create_booking(boat=self.boat, slot=self.slot, rowers=[self.alice, self.bob])

    def test_calendar_marks_current_athlete_booking_and_shows_crew(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('calendar'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tuo')
        self.assertContains(response, '1</span> Alice Example')
        self.assertContains(response, '2</span> Bob Example')

    def test_my_bookings_shows_complete_crew(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_bookings'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Equipaggio')
        self.assertContains(response, '2</span> Bob Example')

    def test_calendar_shows_cox_with_tim_label(self):
        cox = self.create_athlete('Cox Example')
        coxed_boat = Boat.objects.create(name='Coxed Double', rower_seats=2, requires_cox=True)
        self.create_booking(boat=coxed_boat, slot=self.slot, rowers=[self.alice, self.bob], cox=cox)
        self.client.force_login(self.user)

        response = self.client.get(reverse('calendar'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tim.</span> Cox Example')


class AdminBookingCreateFlowTests(DomainFactoryMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', email='', password='password123')
        self.alice = self.create_athlete('Alice Example')
        self.bob = self.create_athlete('Bob Example')
        self.boat = Boat.objects.create(name='Double', rower_seats=2)
        self.slot = self.create_slot(date=date.today())

    def test_admin_create_booking_starts_with_slot_and_boat_only(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_create_booking'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scegli Slot e Imbarcazione')
        self.assertContains(response, 'Slot')
        self.assertContains(response, 'Imbarcazione')
        self.assertNotContains(response, 'Rower 1')

    def test_admin_create_booking_valid_selection_loads_seat_form(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            f'{reverse("admin_create_booking")}?slot={self.slot.id}&boat={self.boat.id}',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Completa Equipaggio')
        self.assertContains(response, 'Rower 1')
        self.assertContains(response, 'Rower 2')

    def test_admin_create_booking_rejects_already_booked_boat_before_seat_form(self):
        self.create_booking(boat=self.boat, slot=self.slot, rowers=[self.alice, self.bob])
        self.client.force_login(self.admin)

        response = self.client.get(
            f'{reverse("admin_create_booking")}?slot={self.slot.id}&boat={self.boat.id}',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Double is already booked in this slot.')
        self.assertNotContains(response, 'Rower 1')

    def test_admin_create_booking_final_phase_creates_booking(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_create_booking'), {
            'phase': 'crew',
            'slot': self.slot.id,
            'boat': self.boat.id,
            'rower_1': self.alice.id,
            'rower_2': self.bob.id,
        }, secure=True)

        self.assertRedirects(response, reverse('admin_all_bookings'), fetch_redirect_response=False)
        booking = Booking.objects.get(slot=self.slot, boat=self.boat)
        self.assertEqual(list(booking.crew.order_by('last_name')), [self.alice, self.bob])
        self.assertEqual(booking.crew_names_with_seats(), '1 Alice Example, 2 Bob Example')

    def test_admin_bookings_show_ordered_seat_labels(self):
        self.create_booking(boat=self.boat, slot=self.slot, rowers=[self.bob, self.alice])
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_all_bookings'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1 Bob Example, 2 Alice Example')


class AdminSlotManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', email='', password='password123')
        self.user = User.objects.create_user(username='athlete', password='password123')

    def test_slot_manager_requires_admin(self):
        self.client.login(username='athlete', password='password123')

        response = self.client.get(reverse('admin_slots'), secure=True)

        self.assertEqual(response.status_code, 302)

    def test_admin_can_create_batch_slots(self):
        workout = Workout.objects.create(name='Tecnica')
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_create_slot'), {
            'create_mode': 'batch',
            'batch-day_of_week': SlotBatch.WEDNESDAY,
            'batch-start_date': '2026-06-01',
            'batch-end_date': '2026-06-30',
            'batch-start_time': '11:00',
            'batch-end_time': '13:00',
            'batch-workout': workout.id,
        }, secure=True)

        self.assertRedirects(response, reverse('admin_slots'), fetch_redirect_response=False)
        self.assertEqual(Slot.objects.filter(workout=workout).count(), 4)

    def test_admin_can_edit_batch_slots(self):
        workout = Workout.objects.create(name='Tecnica')
        updated_workout = Workout.objects.create(name='Sprint')
        batch = SlotBatch.objects.create(
            day_of_week=SlotBatch.WEDNESDAY,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            start_time=time(11, 0),
            end_time=time(13, 0),
            workout=workout,
        )
        batch.create_slots()
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_edit_slot_batch', args=[batch.id]), {
            'start_time': '12:00',
            'end_time': '14:00',
            'workout': updated_workout.id,
            'is_active': '',
        }, secure=True)

        self.assertRedirects(response, reverse('admin_slots'), fetch_redirect_response=False)
        self.assertEqual(Slot.objects.filter(batch_link__batch=batch, start_time=time(12, 0)).count(), 4)
        self.assertEqual(Slot.objects.filter(batch_link__batch=batch, workout=updated_workout).count(), 4)
        self.assertEqual(Slot.objects.filter(batch_link__batch=batch, is_active=False).count(), 4)


class AdminAthleteManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', email='', password='password123')

    def test_admin_can_create_athlete_without_creating_user(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_create_athlete'), {
            'first_name': 'Mario',
            'last_name': 'Rossi',
            'date_of_birth': '01/01/2000',
            'sex': Athlete.SEX_MALE,
            'is_active': 'on',
        }, secure=True)

        self.assertRedirects(response, reverse('admin_athletes'), fetch_redirect_response=False)
        athlete = Athlete.objects.get(last_name='Rossi')
        self.assertEqual(athlete.first_name, 'Mario')
        self.assertEqual(athlete.date_of_birth, date(2000, 1, 1))

        self.assertIsNone(athlete.user)
        self.assertEqual(User.objects.exclude(pk=self.admin.pk).count(), 0)

    def test_admin_can_edit_athlete_and_link_existing_user(self):
        user = User.objects.create_user(username='mrossi', first_name='Mario', last_name='Rossi')
        athlete = Athlete.objects.create(first_name='M.', last_name='Rossi')
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_edit_athlete', args=[athlete.id]), {
            'first_name': 'Mario',
            'last_name': 'Rossi',
            'date_of_birth': '',
            'sex': '',
            'is_active': 'on',
            'user': user.id,
        }, secure=True)

        self.assertRedirects(response, reverse('admin_athletes'), fetch_redirect_response=False)
        athlete.refresh_from_db()
        self.assertEqual(athlete.first_name, 'Mario')
        self.assertEqual(athlete.user, user)

    def test_legacy_user_creation_route_is_not_available(self):
        self.client.force_login(self.admin)

        response = self.client.get('/admin/users/create/', secure=True)

        self.assertEqual(response.status_code, 404)


class LogoutNavigationTests(TestCase):
    def test_nav_uses_post_form_for_logout(self):
        user = User.objects.create_user(username='athlete', password='password123')
        self.client.force_login(user)

        response = self.client.get(reverse('calendar'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<form method="post" action="/logout/" class="logout-form">')
        self.assertContains(response, 'Log out')
        self.assertNotContains(response, 'href="/logout/"')
