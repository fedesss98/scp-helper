from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0003_alter_bookableslot_day_of_week'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Athlete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=150)),
                ('last_name', models.CharField(max_length=150)),
                ('date_of_birth', models.DateField(blank=True, null=True)),
                ('sex', models.CharField(blank=True, choices=[('M', 'Maschile'), ('F', 'Femminile'), ('O', 'Altro')], max_length=1)),
                ('is_active', models.BooleanField(default=True)),
                ('user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='athlete_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['last_name', 'first_name'],
            },
        ),
        migrations.CreateModel(
            name='Workout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.DeleteModel(
            name='Booking',
        ),
        migrations.RemoveConstraint(
            model_name='bookableslot',
            name='unique_bookable_slot',
        ),
        migrations.DeleteModel(
            name='BookableSlot',
        ),
        migrations.RemoveField(
            model_name='boat',
            name='category',
        ),
        migrations.RenameField(
            model_name='boat',
            old_name='seats',
            new_name='rower_seats',
        ),
        migrations.AddField(
            model_name='boat',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='boat',
            name='requires_cox',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='boat',
            name='rower_seats',
            field=models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.CreateModel(
            name='SlotBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day_of_week', models.PositiveSmallIntegerField(choices=[(0, 'Lunedi'), (1, 'Martedi'), (2, 'Mercoledi'), (3, 'Giovedi'), (4, 'Venerdi'), (5, 'Sabato'), (6, 'Domenica')])),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workout', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='bookings.workout')),
            ],
            options={
                'ordering': ['-start_date', 'start_time'],
            },
        ),
        migrations.CreateModel(
            name='Slot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('is_active', models.BooleanField(default=True)),
                ('batch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slots', to='bookings.slotbatch')),
                ('workout', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slots', to='bookings.workout')),
            ],
            options={
                'ordering': ['date', 'start_time'],
            },
        ),
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('boat', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bookings', to='bookings.boat')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_bookings', to=settings.AUTH_USER_MODEL)),
                ('slot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bookings', to='bookings.slot')),
            ],
            options={
                'ordering': ['slot__date', 'slot__start_time', 'boat__name'],
            },
        ),
        migrations.CreateModel(
            name='BookingCrewMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('rower', 'Rower'), ('cox', 'Cox')], default='rower', max_length=10)),
                ('seat_number', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('athlete', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='crew_links', to='bookings.athlete')),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='crew_links', to='bookings.booking')),
            ],
            options={
                'ordering': ['booking', 'role', 'seat_number'],
            },
        ),
        migrations.AddField(
            model_name='booking',
            name='crew',
            field=models.ManyToManyField(related_name='bookings', through='bookings.BookingCrewMember', to='bookings.athlete'),
        ),
        migrations.AddConstraint(
            model_name='slot',
            constraint=models.UniqueConstraint(fields=('date', 'start_time', 'end_time'), name='unique_slot_interval'),
        ),
        migrations.AddConstraint(
            model_name='bookingcrewmember',
            constraint=models.UniqueConstraint(fields=('booking', 'athlete'), name='unique_athlete_per_booking'),
        ),
        migrations.AddConstraint(
            model_name='bookingcrewmember',
            constraint=models.UniqueConstraint(fields=('booking', 'role', 'seat_number'), name='unique_booking_role_seat'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=models.UniqueConstraint(fields=('slot', 'boat'), name='unique_boat_booking_per_slot'),
        ),
    ]
