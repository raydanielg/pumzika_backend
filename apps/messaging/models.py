"""Guest-host messaging — participants-only access."""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel
from apps.common.validators import validate_image_file


class Conversation(UUIDModel):
    property = models.ForeignKey(
        "properties.Property", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="conversations",
    )
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="conversations",
    )
    subject = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["property"]), models.Index(fields=["booking"])]


class ConversationParticipant(TimeStampedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="conversations",
    )
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("conversation", "user")


class Message(UUIDModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_messages"
    )
    body = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]


class MessageAttachment(UUIDModel):
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.ImageField(
        upload_to="messages/%Y/%m/", validators=[validate_image_file]
    )
    name = models.CharField(max_length=200, blank=True)
