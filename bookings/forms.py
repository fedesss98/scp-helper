from datetime import date as current_date, time

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import Athlete, Boat, Booking, BookingCrewMember, Slot, SlotBatch, Workout


def build_time_choices(step_minutes=30):
    choices = [('', '---------')]
    for total_minutes in range(0, 24 * 60, step_minutes):
        hour, minute = divmod(total_minutes, 60)
        value = f'{hour:02d}:{minute:02d}'
        choices.append((value, value))
    return choices


TIME_CHOICES = build_time_choices()


class TwentyFourHourTimeField(forms.TimeField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('input_formats', ['%H:%M'])
        kwargs.setdefault('widget', forms.Select(choices=TIME_CHOICES))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, time):
            return value.strftime('%H:%M')
        return super().prepare_value(value)


class AthleteForm(forms.ModelForm):
    date_of_birth = forms.DateField(
        required=False,
        input_formats=['%d/%m/%Y'],
        widget=forms.DateInput(
            format='%d/%m/%Y',
            attrs={
                'placeholder': 'dd/mm/yyyy',
            },
        ),
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Utente collegato (opzionale)',
        help_text='Qui puoi solo collegare un utente esistente, per la crezione di un nuovo utente rivolgiti all\'admin.',
    )

    class Meta:
        model = Athlete
        fields = ['first_name', 'last_name', 'date_of_birth', 'sex', 'is_active', 'user']
        labels = {
            'first_name': 'Nome',
            'last_name': 'Cognome',
            'date_of_birth': 'Data di nascita',
            'sex': 'Sesso',
            'is_active': 'Atleta attivo',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_filter = Q(is_superuser=False, athlete_profile__isnull=True)
        if self.instance.pk and self.instance.user_id:
            user_filter |= Q(pk=self.instance.user_id)
        self.fields['user'].queryset = User.objects.filter(user_filter).order_by(
            'last_name',
            'first_name',
            'username',
        )


class SlotForm(forms.ModelForm):
    start_time = TwentyFourHourTimeField(label='Ora inizio')
    end_time = TwentyFourHourTimeField(label='Ora fine')

    class Meta:
        model = Slot
        fields = ['date', 'start_time', 'end_time', 'workout', 'is_active']
        labels = {
            'date': 'Data',
            'start_time': 'Ora inizio',
            'end_time': 'Ora fine',
            'workout': 'Workout',
            'is_active': 'Mostra in calendario',
        }
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start and end and end <= start:
            raise ValidationError('End time must be after start time.')
        return cleaned


class SlotBatchForm(forms.ModelForm):
    start_time = TwentyFourHourTimeField(label='Ora inizio')
    end_time = TwentyFourHourTimeField(label='Ora fine')

    class Meta:
        model = SlotBatch
        fields = ['day_of_week', 'start_date', 'end_date', 'start_time', 'end_time', 'workout']
        labels = {
            'day_of_week': 'Giorno',
            'start_date': 'Dal',
            'end_date': 'Al',
            'start_time': 'Ora inizio',
            'end_time': 'Ora fine',
            'workout': 'Workout',
        }
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start_date and end_date and end_date < start_date:
            raise ValidationError('End date must be after start date.')
        if start and end and end <= start:
            raise ValidationError('End time must be after start time.')
        return cleaned


class SlotBatchEditForm(forms.Form):
    start_time = TwentyFourHourTimeField(label='Ora inizio')
    end_time = TwentyFourHourTimeField(label='Ora fine')
    workout = forms.ModelChoiceField(
        queryset=Workout.objects.none(),
        required=False,
        label='Workout',
    )
    is_active = forms.BooleanField(required=False, label='Mostra in calendario')

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch = batch
        self.fields['workout'].queryset = Workout.objects.all()
        if batch and not self.is_bound:
            self.initial.update({
                'start_time': batch.start_time,
                'end_time': batch.end_time,
                'workout': batch.workout,
                'is_active': batch.linked_slots_are_active,
            })

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start and end and end <= start:
            raise ValidationError('End time must be after start time.')
        return cleaned


def active_athletes():
    return Athlete.objects.filter(is_active=True).order_by('last_name', 'first_name')


class BookingSelectionForm(forms.Form):
    slot = forms.ModelChoiceField(
        queryset=Slot.objects.none(),
        label='Slot',
    )
    boat = forms.ModelChoiceField(
        queryset=Boat.objects.none(),
        label='Imbarcazione',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slot'].queryset = Slot.objects.filter(is_active=True).order_by('date', 'start_time')
        self.fields['boat'].queryset = Boat.objects.filter(is_active=True).order_by('name')

    def clean(self):
        cleaned = super().clean()
        slot = cleaned.get('slot')
        boat = cleaned.get('boat')
        if not slot or not boat:
            return cleaned

        if slot.date < current_date.today():
            raise ValidationError('Cannot book a past slot.')

        if Booking.objects.filter(slot=slot, boat=boat).exists():
            raise ValidationError(f'{boat.name} is already booked in this slot.')

        return cleaned


class BookingForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.selected_boat = self._get_selected_boat()
        self.fields['slot'].queryset = Slot.objects.filter(is_active=True).order_by('date', 'start_time')
        self.fields['boat'].queryset = Boat.objects.filter(is_active=True).order_by('name')
        self._add_crew_fields()

    class Meta:
        model = Booking
        fields = ['slot', 'boat']
        labels = {
            'slot': 'Slot',
            'boat': 'Imbarcazione',
        }

    def _get_selected_boat(self):
        value = self.data.get('boat') if self.is_bound else self.initial.get('boat')
        if not value and self.instance.pk:
            value = self.instance.boat_id
        try:
            return Boat.objects.get(pk=value)
        except (Boat.DoesNotExist, TypeError, ValueError):
            return None

    def _add_crew_fields(self):
        if not self.selected_boat:
            return

        initial_rowers = []
        initial_cox = None
        if self.instance.pk:
            for link in self.instance.crew_links.select_related('athlete'):
                if link.role == BookingCrewMember.ROLE_COX:
                    initial_cox = link.athlete_id
                else:
                    initial_rowers.append((link.seat_number or 0, link.athlete_id))
        rower_initial_by_seat = {
            seat: athlete_id for seat, athlete_id in sorted(initial_rowers)
        }

        for seat in range(1, self.selected_boat.rower_seats + 1):
            self.fields[f'rower_{seat}'] = forms.ModelChoiceField(
                queryset=active_athletes(),
                required=True,
                label=f'Rower {seat}',
                initial=rower_initial_by_seat.get(seat),
            )

        if self.selected_boat.requires_cox:
            self.fields['cox'] = forms.ModelChoiceField(
                queryset=active_athletes(),
                required=True,
                label='Cox',
                initial=initial_cox,
            )

    def clean(self):
        cleaned = super().clean()
        slot = cleaned.get('slot')
        boat = cleaned.get('boat')
        if not slot or not boat:
            return cleaned

        if slot.date < current_date.today():
            raise ValidationError('Cannot book a past slot.')

        if Booking.objects.filter(slot=slot, boat=boat).exclude(pk=self.instance.pk).exists():
            raise ValidationError(f'{boat.name} is already booked in this slot.')

        athletes = []
        for seat in range(1, boat.rower_seats + 1):
            athlete = cleaned.get(f'rower_{seat}')
            if athlete:
                athletes.append(athlete)

        cox = cleaned.get('cox')
        if boat.requires_cox and cox:
            athletes.append(cox)

        if len(athletes) != boat.total_crew_size:
            raise ValidationError('The booking crew must be complete.')

        if len({athlete.pk for athlete in athletes}) != len(athletes):
            raise ValidationError('The same athlete cannot appear twice in the same booking.')

        overlapping_bookings = Booking.objects.filter(slot=slot, crew__in=athletes).exclude(pk=self.instance.pk)
        if overlapping_bookings.exists():
            raise ValidationError('One or more athletes are already booked in this slot.')

        return cleaned

    def save(self, commit=True):
        booking = super().save(commit=False)
        if self.user and not booking.created_by_id:
            booking.created_by = self.user
        if commit:
            with transaction.atomic():
                booking.save()
                booking.crew_links.all().delete()
                for seat in range(1, booking.boat.rower_seats + 1):
                    BookingCrewMember.objects.create(
                        booking=booking,
                        athlete=self.cleaned_data[f'rower_{seat}'],
                        role=BookingCrewMember.ROLE_ROWER,
                        seat_number=seat,
                    )
                if booking.boat.requires_cox:
                    BookingCrewMember.objects.create(
                        booking=booking,
                        athlete=self.cleaned_data['cox'],
                        role=BookingCrewMember.ROLE_COX,
                    )
        return booking


class AdminBookingForm(BookingForm):
    pass
