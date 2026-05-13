from django.contrib import admin

from .models import Athlete, Boat, Booking, BookingCrewMember, Slot, SlotBatch, Workout


@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'date_of_birth', 'sex', 'user', 'is_active']
    list_filter = ['sex', 'is_active']
    search_fields = ['first_name', 'last_name', 'user__username']


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']


@admin.register(SlotBatch)
class SlotBatchAdmin(admin.ModelAdmin):
    list_display = ['day_of_week', 'start_date', 'end_date', 'start_time', 'end_time', 'workout']
    list_filter = ['day_of_week', 'workout']


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ['date', 'start_time', 'end_time', 'workout', 'is_active']
    list_editable = ['is_active']
    list_filter = ['date', 'workout', 'is_active']
    ordering = ['date', 'start_time']


@admin.register(Boat)
class BoatAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'rower_seats', 'requires_cox', 'color', 'is_active']
    list_filter = ['requires_cox', 'is_active']
    search_fields = ['name']


class BookingCrewMemberInline(admin.TabularInline):
    model = BookingCrewMember
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['boat', 'slot', 'crew_summary', 'created_by', 'created_at']
    list_filter = ['boat', 'slot__date']
    inlines = [BookingCrewMemberInline]

    @admin.display(description='Crew')
    def crew_summary(self, obj):
        return obj.crew_names()
