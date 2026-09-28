"""Disputes — guest/host raise; staff resolve. Every step auditable."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class Dispute(UUIDModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        WAITING_FOR_USER = "WAITING_FOR_USER", "Waiting for User"
        RESOLVED = "RESOLVED", "Resolved"
        REJECTED = "REJECTED", "Rejected"
        CLOSED = "CLOSED", "Closed"

    class Category(models.TextChoices):
        PROPERTY_MISREPRESENTED = "PROPERTY_MISREPRESENTED"
        CLEANLINESS = "CLEANLINESS"
        HOST_NO_SHOW = "HOST_NO_SHOW"
        GUEST_DAMAGE = "GUEST_DAMAGE"
        PAYMENT_ISSUE = "PAYMENT_ISSUE"
        SAFETY = "SAFETY"
        OTHER = "OTHER"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, related_name="disputes"
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="disputes_opened",
    )
    category = models.CharField(max_length=40, choices=Category.choices,
                                default=Category.OTHER)
    description = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True
    )

    class Meta:
        indexes = [models.Index(fields=["booking", "status"]),
                   models.Index(fields=["status", "-created_at"])]


class DisputeMessage(UUIDModel):
    dispute = models.ForeignKey(
        Dispute, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    body = models.TextField()


class DisputeEvidence(UUIDModel):
    dispute = models.ForeignKey(
        Dispute, on_delete=models.CASCADE, related_name="evidence"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    file = models.FileField(upload_to="disputes/%Y/%m/")
    description = models.CharField(max_length=255, blank=True)


class DisputeStatusHistory(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispute = models.ForeignKey(
        Dispute, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class DisputeResolution(UUIDModel):
    """Final staff decision — append-only."""

    class Outcome(models.TextChoices):
        REFUND_GUEST = "REFUND_GUEST", "Refund Guest"
        PARTIAL_REFUND = "PARTIAL_REFUND", "Partial Refund"
        PAY_HOST = "PAY_HOST", "Pay Host"
        NO_ACTION = "NO_ACTION", "No Action"

    dispute = models.OneToOneField(
        Dispute, on_delete=models.CASCADE, related_name="resolution"
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="disputes_resolved",
    )
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    refund_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    notes = models.TextField(blank=True)
