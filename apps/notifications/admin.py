from django.contrib import admin

from .models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    UserDevice,
    UserNotificationSettings,
)


class DeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    readonly_fields = ("channel", "status", "attempts", "provider_reference",
                       "error", "sent_at")
    can_delete = False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "event_type", "status", "created_at")
    list_filter = ("channel", "status", "event_type")
    search_fields = ("user__email", "title")
    inlines = [DeliveryInline]


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "device_id", "is_active", "last_seen_at")
    list_filter = ("platform", "is_active")
    search_fields = ("user__email", "device_id")


admin.site.register([NotificationTemplate, NotificationPreference,
                     UserNotificationSettings])
