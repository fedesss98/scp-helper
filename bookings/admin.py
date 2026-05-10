from django.contrib import admin
from .models import Boat, Booking

@admin.register(Boat)
class BoatAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'category', 'seats', 'color']
    list_filter = ['category']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['athlete', 'boat', 'date', 'time_span', 'created_at']
    list_filter = ['boat', 'date']

    @admin.display(description='Time')
    def time_span(self, obj):
        return f'{obj.start_time:%H:%M} - {obj.end_time:%H:%M}'
