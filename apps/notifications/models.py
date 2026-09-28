"""Notification delivery records, templates and user preferences."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class NotificationChannel(models.TextChoices):
    IN_APP = "IN_APP", "In-App"
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"
    PUSH = "PUSH", "Push"
    WHATSAPP = "WHATSAPP", "WhatsApp"


class Notification(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        READ = "READ", "Read"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices)
    event_type = models.CharField(max_length=50, db_index=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "-created_at"])]


class NotificationTemplate(TimeStampedModel):
    """DB-driven message templates with ``{placeholder}`` interpolation."""

    key = models.CharField(max_length=100, db_index=True)
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("key", "channel")

    def render(self, context: dict) -> tuple[str, str]:
        try:
            return self.subject.format(**context), self.body.format(**context)
        except KeyError:
            return self.subject, self.body


class NotificationPreference(TimeStampedModel):
    """Per-user per-(event, channel) override opt-outs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    event_type = models.CharField(max_length=50)
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "event_type", "channel")


class UserNotificationSettings(TimeStampedModel):
    """One row per user — broad channel/category switches.

    Critical security & transaction events bypass these flags.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notification_settings",
    )
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    marketing_notifications = models.BooleanField(default=True)
    booking_notifications = models.BooleanField(default=True)
    message_notifications = models.BooleanField(default=True)

    def channel_allowed(self, channel: str) -> bool:
        return {
            NotificationChannel.EMAIL: self.email_notifications,
            NotificationChannel.SMS: self.sms_notifications,
            NotificationChannel.PUSH: self.push_notifications,
        }.get(channel, True)


class NotificationDelivery(TimeStampedModel):
    """Per-channel delivery attempt — an audit trail of what went where."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=20, choices=NotificationChannel.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    provider_reference = models.CharField(max_length=128, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)


class UserDevice(TimeStampedModel):
    """A device a user has installed the app on — one user, many devices."""

    class Platform(models.TextChoices):
        IOS = "IOS", "iOS"
        ANDROID = "ANDROID", "Android"
        WEB = "WEB", "Web"
        OTHER = "OTHER", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    device_id = models.CharField(max_length=128)
    platform = models.CharField(
        max_length=10, choices=Platform.choices, default=Platform.OTHER
    )
    push_token = models.CharField(max_length=512, blank=True)
    app_version = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "device_id")
        indexes = [models.Index(fields=["user", "is_active"])]
