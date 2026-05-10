from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator


class BookableSlot(models.Model):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    DAY_CHOICES = [
        (MONDAY, 'Monday'),
        (TUESDAY, 'Tuesday'),
        (WEDNESDAY, 'Wednesday'),
        (THURSDAY, 'Thursday'),
        (FRIDAY, 'Friday'),
        (SATURDAY, 'Saturday'),
        (SUNDAY, 'Sunday'),
    ]

    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['day_of_week', 'start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['day_of_week', 'start_time', 'end_time'],
                name='unique_bookable_slot',
            ),
        ]

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time.")

    def __str__(self):
        return f"{self.get_day_of_week_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class Boat(models.Model):
    CATEGORY_SINGLE_COASTAL = '1xC'
    CATEGORY_DOUBLE_COASTAL = '2xC'
    CATEGORY_DOUBLE = '2x'
    CATEGORY_QUAD = '4x'
    CATEGORY_COXED_FOUR = '4+'

    CATEGORY_CHOICES = [
        (CATEGORY_SINGLE_COASTAL, '1xC'),
        (CATEGORY_DOUBLE_COASTAL, '2xC'),
        (CATEGORY_DOUBLE, '2x'),
        (CATEGORY_QUAD, '4x'),
        (CATEGORY_COXED_FOUR, '4+'),
    ]

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default=CATEGORY_SINGLE_COASTAL)
    seats = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#2196F3', help_text='Hex color for calendar display')

    def __str__(self):
        return f"{self.name} ({self.category})"

    class Meta:
        ordering = ['name']


class Booking(models.Model):
    boat = models.ForeignKey(Boat, on_delete=models.CASCADE, related_name='bookings')
    athlete = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']

    def __str__(self):
        return f"{self.athlete.username} — {self.boat.name} on {self.date} {self.start_time:%H:%M}–{self.end_time:%H:%M}"
