from datetime import date, time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import BookingForm, ChangePasswordForm, CreateAthleteForm
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
