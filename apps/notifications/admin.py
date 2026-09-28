from django.contrib import admin

from .models import Notification, NotificationPreference, NotificationTemplate


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "event_type", "status", "created_at")
    list_filter = ("channel", "status", "event_type")
    search_fields = ("user__email", "title")


admin.site.register([NotificationTemplate, NotificationPreference])
