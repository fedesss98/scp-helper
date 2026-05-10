from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from datetime import date as current_date
from .models import Booking


PASSWORD_MIN_LENGTH = 8


class CreateAthleteForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        label='Password',
        min_length=PASSWORD_MIN_LENGTH,
        help_text=f'At least {PASSWORD_MIN_LENGTH} characters.',
    )
    confirm_password = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
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
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_staff = False
        if commit:
            user.save()
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
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data


class BookingForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    class Meta:
        model = Booking
        fields = ['boat', 'date', 'start_time', 'end_time']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),  # 30-min steps
            'end_time':   forms.TimeInput(attrs={'type': 'time', 'step': '1800'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end   = cleaned.get('end_time')
        boat  = cleaned.get('boat')
        date  = cleaned.get('date')

        if date and date < current_date.today():
            raise ValidationError("Cannot book a past date.")

        if start and end:
            if end <= start:
                raise ValidationError("End time must be after start time.")

            if boat and date:
                if self.user and Booking.objects.filter(
                    athlete=self.user,
                    date=date,
                    start_time__lt=end,
                    end_time__gt=start,
                ).exclude(pk=self.instance.pk).exists():
                    raise ValidationError("You already have a booking during this time.")

                overlapping_bookings = list(Booking.objects.filter(
                    boat=boat,
                    date=date,
                    start_time__lt=end,
                    end_time__gt=start,
                ).exclude(pk=self.instance.pk))

                boundaries = {start, end}
                for booking in overlapping_bookings:
                    if start < booking.start_time < end:
                        boundaries.add(booking.start_time)
                    if start < booking.end_time < end:
                        boundaries.add(booking.end_time)

                ordered_boundaries = sorted(boundaries)
                for index, segment_start in enumerate(ordered_boundaries[:-1]):
                    segment_end = ordered_boundaries[index + 1]
                    booked_seats = sum(
                        existing.start_time < segment_end and existing.end_time > segment_start
                        for existing in overlapping_bookings
                    )
                    if booked_seats >= boat.seats:
                        raise ValidationError(
                            f"{boat.name} already has all {boat.seats} seat(s) booked during this time."
                        )

        return cleaned
