from datetime import date, time

from django.contrib.auth.models import User
from django.test import TestCase

from .forms import BookingForm
from .models import Boat, Booking


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
        Booking.objects.create(
            boat=self.boat,
            athlete=self.alice,
            date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

        self.assertFalse(self.form_for(self.alice, '09:30', '10:30').is_valid())
