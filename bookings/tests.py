from datetime import date, time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import AdminBookingForm, BookingForm, ChangePasswordForm, CreateAthleteForm
from .models import Boat, BookableSlot, Booking


class BookingCapacityTests(TestCase):
    def setUp(self):
        self.boat = Boat.objects.create(
            name='Test Double',
            category=Boat.CATEGORY_DOUBLE,
            seats=2,
        )
        self.alice = User.objects.create_user(username='alice')
        self.bob = User.objects.create_user(username='bob')
        self.cara = User.objects.create_user(username='cara')
        self.booking_date = date(2026, 6, 1)
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def form_for(self, user, start, end):
        return BookingForm(
            data={
                'boat': self.boat.id,
                'date': self.booking_date.isoformat(),
                'start_time': start,
                'end_time': end,
            },
            user=user,
        )

    def test_allows_bookings_until_boat_seat_capacity_is_full(self):
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

        self.assertTrue(self.form_for(self.bob, '09:00', '10:00').is_valid())

    def test_rejects_booking_when_boat_seat_capacity_is_full(self):
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.bob,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

        self.assertFalse(self.form_for(self.cara, '09:00', '10:00').is_valid())

    def test_checks_capacity_across_partial_overlaps(self):
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(9, 30),
            end_time=time(10, 30),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.bob,
            date=self.booking_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

        self.assertTrue(self.form_for(self.cara, '09:30', '10:30').is_valid())

    def test_rejects_overlapping_booking_for_same_athlete(self):
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(9, 30),
            end_time=time(10, 30),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

        self.assertFalse(self.form_for(self.alice, '09:30', '10:30').is_valid())

    def test_rejects_times_that_are_not_admin_generated_slots(self):
        self.assertFalse(self.form_for(self.alice, '12:00', '13:00').is_valid())


class AdminPasswordFormTests(TestCase):
    def test_create_athlete_rejects_short_passwords(self):
        form = CreateAthleteForm(data={
            'username': 'shortpass',
            'password': 'short',
            'confirm_password': 'short',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)


class LogoutNavigationTests(TestCase):
    def test_nav_uses_post_form_for_logout(self):
        user = User.objects.create_user(username='athlete', password='password123')
        self.client.force_login(user)

        response = self.client.get(reverse('calendar'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<form method="post" action="/logout/" class="logout-form">')
        self.assertContains(response, 'Log out')
        self.assertNotContains(response, 'href="/logout/"')


class AthleteSharedBookingVisibilityTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username='alice', password='password123')
        self.bob = User.objects.create_user(username='bob', password='password123')
        self.booking_date = date.today()
        self.boat = Boat.objects.create(
            name='Shared Double',
            category=Boat.CATEGORY_DOUBLE,
            seats=2,
        )
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        Booking.objects.create(
            boat=self.boat,
            athlete=self.bob,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def test_calendar_shows_other_athletes_when_slot_is_mine(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse('calendar'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Yours')
        self.assertContains(response, 'bob')

    def test_booking_page_shows_existing_people_on_selected_boat(self):
        Booking.objects.filter(athlete=self.alice).delete()
        self.client.force_login(self.alice)

        response = self.client.get(reverse('book_slot'), {
            'boat': self.boat.id,
            'date': self.booking_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
        }, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Already booked on this boat')
        self.assertContains(response, 'bob')

    def test_my_bookings_shows_other_people_on_same_boat(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse('my_bookings'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Same boat')
        self.assertContains(response, 'bob')


class AdminSlotManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin',
            email='',
            password='password123',
        )
        self.athlete = User.objects.create_user(
            username='athlete',
            password='password123',
        )
        self.slot = BookableSlot.objects.create(
            day_of_week=BookableSlot.MONDAY,
            start_time=time(15, 30),
            end_time=time(17, 0),
        )

    def test_slot_manager_requires_admin(self):
        self.client.login(username='athlete', password='password123')

        response = self.client.get(reverse('admin_slots'), secure=True)

        self.assertEqual(response.status_code, 302)

    def test_admin_can_view_slot_manager(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_slots'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bookable Slots')
        self.assertContains(response, '15:30 - 17:00')

    def test_admin_can_create_slot(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_create_slot'), {
            'day_of_week': BookableSlot.TUESDAY,
            'start_time': '07:00',
            'end_time': '08:30',
            'is_active': 'on',
        }, secure=True)

        self.assertRedirects(response, reverse('admin_slots'), fetch_redirect_response=False)
        self.assertTrue(BookableSlot.objects.filter(
            day_of_week=BookableSlot.TUESDAY,
            start_time='07:00',
            end_time='08:30',
            is_active=True,
        ).exists())

    def test_admin_can_toggle_slot_visibility(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_toggle_slot', args=[self.slot.id]), secure=True)
        self.slot.refresh_from_db()

        self.assertRedirects(response, reverse('admin_slots'), fetch_redirect_response=False)
        self.assertFalse(self.slot.is_active)

    def test_admin_can_delete_slot(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_delete_slot', args=[self.slot.id]), secure=True)

        self.assertRedirects(response, reverse('admin_slots'), fetch_redirect_response=False)
        self.assertFalse(BookableSlot.objects.filter(id=self.slot.id).exists())

    def test_change_password_rejects_short_passwords(self):
        form = ChangePasswordForm(data={
            'password': 'short',
            'confirm_password': 'short',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)


class AdminBookingManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin',
            email='',
            password='password123',
        )
        self.athlete = User.objects.create_user(
            username='user1',
            password='password123',
        )
        self.other_athlete = User.objects.create_user(
            username='user2',
            password='password123',
        )
        self.boat = Boat.objects.create(
            name='Admin Single',
            category=Boat.CATEGORY_SINGLE_COASTAL,
            seats=1,
        )
        self.other_boat = Boat.objects.create(
            name='Admin Double',
            category=Boat.CATEGORY_DOUBLE,
            seats=2,
        )
        self.booking_date = date(2026, 6, 1)
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        BookableSlot.objects.create(
            day_of_week=self.booking_date.weekday(),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

    def booking_payload(self, **overrides):
        payload = {
            'athlete': self.athlete.id,
            'boat': self.boat.id,
            'date': self.booking_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
        }
        payload.update(overrides)
        return payload

    def test_booking_manager_requires_admin(self):
        self.client.login(username='user1', password='password123')

        response = self.client.get(reverse('admin_create_booking'), secure=True)

        self.assertEqual(response.status_code, 302)

    def test_admin_can_create_booking_for_athlete(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_create_booking'), self.booking_payload(), secure=True)

        self.assertRedirects(response, reverse('admin_all_bookings'), fetch_redirect_response=False)
        self.assertTrue(Booking.objects.filter(
            athlete=self.athlete,
            boat=self.boat,
            date=self.booking_date,
            start_time='09:00',
            end_time='10:00',
        ).exists())

    def test_admin_can_edit_booking(self):
        booking = Booking.objects.create(
            athlete=self.athlete,
            boat=self.boat,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_edit_booking', args=[booking.id]),
            self.booking_payload(
                athlete=self.other_athlete.id,
                boat=self.other_boat.id,
                start_time='10:00',
                end_time='11:00',
            ),
            secure=True,
        )
        booking.refresh_from_db()

        self.assertRedirects(response, reverse('admin_all_bookings'), fetch_redirect_response=False)
        self.assertEqual(booking.athlete, self.other_athlete)
        self.assertEqual(booking.boat, self.other_boat)
        self.assertEqual(booking.start_time, time(10, 0))
        self.assertEqual(booking.end_time, time(11, 0))

    def test_admin_can_delete_booking(self):
        booking = Booking.objects.create(
            athlete=self.athlete,
            boat=self.boat,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse('admin_delete_booking', args=[booking.id]), secure=True)

        self.assertRedirects(response, reverse('admin_all_bookings'), fetch_redirect_response=False)
        self.assertFalse(Booking.objects.filter(id=booking.id).exists())

    def test_admin_booking_form_rejects_overlapping_booking_for_same_athlete(self):
        Booking.objects.create(
            athlete=self.athlete,
            boat=self.other_boat,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

        form = AdminBookingForm(data=self.booking_payload())

        self.assertFalse(form.is_valid())
        self.assertIn('This athlete already has a booking during this time.', form.non_field_errors())
