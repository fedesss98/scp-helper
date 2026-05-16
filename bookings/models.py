from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Athlete(models.Model):
    SEX_MALE = 'M'
    SEX_FEMALE = 'F'
    SEX_OTHER = 'O'

    SEX_CHOICES = [
        (SEX_MALE, 'Maschio'),
        (SEX_FEMALE, 'Femmina'),
        (SEX_OTHER, 'Altro'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='athlete_profile',
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def race_category(self, reference_date=None):
        if not self.date_of_birth:
            return ''
        reference_date = reference_date or getattr(self, '_category_reference_date', None)
        if reference_date is None:
            from django.utils import timezone

            reference_date = timezone.localdate()
        age = reference_date.year - self.date_of_birth.year
        if (reference_date.month, reference_date.day) < (self.date_of_birth.month, self.date_of_birth.day):
            age -= 1
        if age < 14:
            return 'U14'
        if age < 17:
            return 'U17'
        if age < 19:
            return 'U19'
        if age < 23:
            return 'U23'
        if age >= 27:
            return 'Master'
        return 'Senior'

    def __str__(self):
        return self.full_name or f'Atleta #{self.pk}'


class Workout(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SlotBatch(models.Model):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    DAY_CHOICES = [
        (MONDAY, 'Lunedi'),
        (TUESDAY, 'Martedi'),
        (WEDNESDAY, 'Mercoledi'),
        (THURSDAY, 'Giovedi'),
        (FRIDAY, 'Venerdi'),
        (SATURDAY, 'Sabato'),
        (SUNDAY, 'Domenica'),
    ]

    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    workout = models.ForeignKey(Workout, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date', 'start_time']

    def clean(self):
        if self.end_date < self.start_date:
            raise ValidationError('End date must be after start date.')
        if self.end_time <= self.start_time:
            raise ValidationError('End time must be after start time.')

    def matching_dates(self):
        cursor = self.start_date
        while cursor <= self.end_date:
            if cursor.weekday() == self.day_of_week:
                yield cursor
            cursor += timedelta(days=1)

    @property
    def linked_slots_are_active(self):
        linked_slots = Slot.objects.filter(batch_link__batch=self)
        if not linked_slots.exists():
            return True
        return not linked_slots.filter(is_active=False).exists()

    def create_slots(self):
        created_slots = []
        for slot_date in self.matching_dates():
            slot, created = Slot.objects.get_or_create(
                date=slot_date,
                start_time=self.start_time,
                end_time=self.end_time,
                defaults={
                    'workout': self.workout,
                    'batch': self,
                    'is_active': True,
                },
            )
            if created:
                SlotBatchSlot.objects.get_or_create(batch=self, slot=slot)
                created_slots.append(slot)
        return created_slots

    def update_linked_slots(self, *, start_time, end_time, workout, is_active):
        linked_slots = Slot.objects.filter(batch_link__batch=self)
        updated = linked_slots.update(
            start_time=start_time,
            end_time=end_time,
            workout=workout,
            is_active=is_active,
        )
        self.start_time = start_time
        self.end_time = end_time
        self.workout = workout
        self.save(update_fields=['start_time', 'end_time', 'workout'])
        return updated

    def __str__(self):
        return (
            f'{self.get_day_of_week_display()} '
            f'{self.start_date:%Y-%m-%d}-{self.end_date:%Y-%m-%d} '
            f'{self.start_time:%H:%M}-{self.end_time:%H:%M}'
        )


class Slot(models.Model):
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    workout = models.ForeignKey(Workout, on_delete=models.SET_NULL, null=True, blank=True, related_name='slots')
    batch = models.ForeignKey(SlotBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='slots')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['date', 'start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['date', 'start_time', 'end_time'],
                name='unique_slot_interval',
            ),
        ]

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError('End time must be after start time.')

    @property
    def is_past(self):
        from django.utils import timezone

        return self.date < timezone.localdate()

    def __str__(self):
        workout = f' - {self.workout.name}' if self.workout else ''
        return f'{self.date:%Y-%m-%d} {self.start_time:%H:%M}-{self.end_time:%H:%M}{workout}'


class SlotBatchSlot(models.Model):
    batch = models.ForeignKey(SlotBatch, on_delete=models.CASCADE, related_name='slot_links')
    slot = models.OneToOneField(Slot, on_delete=models.CASCADE, related_name='batch_link')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['slot__date', 'slot__start_time']
        constraints = [
            models.UniqueConstraint(fields=['batch', 'slot'], name='unique_slot_batch_link'),
        ]

    def __str__(self):
        return f'{self.batch} -> {self.slot}'


class Boat(models.Model):
    name = models.CharField(max_length=100)
    rower_seats = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    requires_cox = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#2196F3', help_text='Hex color for calendar display')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    @property
    def total_crew_size(self):
        return self.rower_seats + (1 if self.requires_cox else 0)

    def __str__(self):
        suffix = '+' if self.requires_cox else 'x'
        return f'{self.name} ({self.rower_seats}{suffix})'


class Booking(models.Model):
    slot = models.ForeignKey(Slot, on_delete=models.CASCADE, related_name='bookings')
    boat = models.ForeignKey(Boat, on_delete=models.CASCADE, related_name='bookings')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_bookings')
    created_at = models.DateTimeField(auto_now_add=True)
    crew = models.ManyToManyField(Athlete, through='BookingCrewMember', related_name='bookings')

    class Meta:
        ordering = ['slot__date', 'slot__start_time', 'boat__name']
        constraints = [
            models.UniqueConstraint(fields=['slot', 'boat'], name='unique_boat_booking_per_slot'),
        ]

    @property
    def date(self):
        return self.slot.date

    @property
    def start_time(self):
        return self.slot.start_time

    @property
    def end_time(self):
        return self.slot.end_time

    def crew_members(self):
        return self.crew_links.select_related('athlete').order_by('role', 'seat_number', 'athlete__last_name')

    def rowers(self):
        return [link.athlete for link in self.crew_members() if link.role == BookingCrewMember.ROLE_ROWER]

    def cox(self):
        link = next((item for item in self.crew_members() if item.role == BookingCrewMember.ROLE_COX), None)
        return link.athlete if link else None

    def crew_names(self):
        return ', '.join(athlete.full_name for athlete in self.crew.all())

    def __str__(self):
        return f'{self.boat.name} on {self.slot}'


class BookingCrewMember(models.Model):
    ROLE_ROWER = 'rower'
    ROLE_COX = 'cox'

    ROLE_CHOICES = [
        (ROLE_ROWER, 'Rower'),
        (ROLE_COX, 'Cox'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='crew_links')
    athlete = models.ForeignKey(Athlete, on_delete=models.PROTECT, related_name='crew_links')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_ROWER)
    seat_number = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['booking', 'role', 'seat_number']
        constraints = [
            models.UniqueConstraint(fields=['booking', 'athlete'], name='unique_athlete_per_booking'),
            models.UniqueConstraint(fields=['booking', 'role', 'seat_number'], name='unique_booking_role_seat'),
        ]

    def __str__(self):
        seat = f' #{self.seat_number}' if self.seat_number else ''
        return f'{self.athlete} as {self.role}{seat}'
