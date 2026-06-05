from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fields = ['telegram_chat_id', 'telegram_username', 'phone']

    def get_extra(self, request, obj=None, **kwargs):
        if obj and not hasattr(obj, 'profile'):
            return 1
        return 0


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_username', 'telegram_chat_id', 'phone']
    search_fields = ['user__username', 'user__email', 'telegram_username', 'telegram_chat_id', 'phone']

