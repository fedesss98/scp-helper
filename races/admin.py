from django.contrib import admin

from .models import Race, RaceResult, RaceSubscription


class RaceResultInline(admin.TabularInline):
    model = RaceResult
    extra = 0
    fields = ['race_number', 'position', 'club', 'finish_time', 'event', 'phase']
    readonly_fields = ['race_number', 'position', 'club', 'finish_time', 'event', 'phase']
    can_delete = False
    show_change_link = True


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ['external_id', 'name', 'location', 'date', 'category', 'last_scraped']
    list_filter = ['date', 'category', 'location']
    search_fields = ['external_id', 'name', 'location']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [RaceResultInline]


@admin.register(RaceResult)
class RaceResultAdmin(admin.ModelAdmin):
    list_display = ['race', 'race_number', 'position', 'club', 'finish_time', 'event', 'phase']
    list_filter = ['race', 'phase', 'position']
    search_fields = ['external_id', 'race__external_id', 'club', 'event', 'athletes']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(RaceSubscription)
class RaceSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'race', 'created_at']
    list_filter = ['race']
    search_fields = ['user__username', 'user__email', 'race__external_id', 'race__name']

