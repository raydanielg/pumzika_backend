from rest_framework import serializers

from .models import (
    Notification,
    NotificationPreference,
    UserDevice,
    UserNotificationSettings,
)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "channel", "event_type", "title", "body", "data",
                  "status", "sent_at", "read_at", "created_at"]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["event_type", "channel", "enabled"]


class UserNotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationSettings
        fields = ["email_notifications", "sms_notifications",
                  "push_notifications", "marketing_notifications",
                  "booking_notifications", "message_notifications"]


class UserDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDevice
        fields = ["id", "device_id", "platform", "app_version",
                  "is_active", "last_seen_at", "created_at"]
        read_only_fields = ["id", "is_active", "last_seen_at", "created_at"]


class DeviceRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDevice
        fields = ["device_id", "platform", "push_token", "app_version"]
