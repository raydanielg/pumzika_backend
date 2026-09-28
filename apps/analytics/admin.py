from django.contrib import admin

from .models import AnalyticsEvent


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "object_type", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("user", "event_type", "object_type", "object_id",
                       "session_id", "metadata")
