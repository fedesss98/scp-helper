from datetime import date as current_date

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Athlete, Boat, Booking, BookingCrewMember, Slot, SlotBatch


PASSWORD_MIN_LENGTH = 8


class CreateUserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        label='Password',
        min_length=PASSWORD_MIN_LENGTH,
        help_text=f'At least {PASSWORD_MIN_LENGTH} characters.',
    )
    confirm_password = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')
    is_staff = forms.BooleanField(required=False, label='Staff')
    athlete = forms.ModelChoiceField(
        queryset=Athlete.objects.filter(user__isnull=True, is_active=True),
        required=False,
        label='Existing athlete',
        help_text='Leave empty to create and link a new athlete from the user name.',
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='Date of birth',
    )
    sex = forms.ChoiceField(required=False, choices=[('', '---------'), *Athlete.SEX_CHOICES], label='Sex')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_staff']
        labels = {
            'username': 'Username',
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email (optional)',
        }

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        cpw = cleaned_data.get('confirm_password')
        if pw and cpw and pw != cpw:
            raise forms.ValidationError('Passwords do not match.')
        if not cleaned_data.get('athlete') and not (
            cleaned_data.get('first_name') or cleaned_data.get('last_name')
        ):
            raise forms.ValidationError('Provide a name or link an existing athlete.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_staff = self.cleaned_data.get('is_staff', False)
        if commit:
            with transaction.atomic():
                user.save()
                athlete = self.cleaned_data.get('athlete')
                if athlete:
                    athlete.user = user
                    athlete.save(update_fields=['user'])
                else:
                    Athlete.objects.create(
                        user=user,
                        first_name=user.first_name or user.username,
                        last_name=user.last_name,
                        date_of_birth=self.cleaned_data.get('date_of_birth'),
                        sex=self.cleaned_data.get('sex') or '',
                    )
        return user


class ChangePasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput,
        label='New Password',
        min_length=PASSWORD_MIN_LENGTH,
        help_text=f'At least {PASSWORD_MIN_LENGTH} characters.',
    )
    confirm_password = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        cpw = cleaned_data.get('confirm_password')
        if pw and cpw and pw != cpw:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned_data


class SlotForm(forms.ModelForm):
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
            'start_time': forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start and end and end <= start:
            raise ValidationError('End time must be after start time.')
        return cleaned


class SlotBatchForm(forms.ModelForm):
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
            'start_time': forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),
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


def active_athletes():
    return Athlete.objects.filter(is_active=True).order_by('last_name', 'first_name')


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
