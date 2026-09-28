"""Bookings, price snapshots, status history and cancellations."""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel


class CancellationPolicy(TimeStampedModel):
    """Configurable cancellation policies — rules are data, not code."""

    class Code(models.TextChoices):
        FLEXIBLE = "FLEXIBLE", "Flexible"
        MODERATE = "MODERATE", "Moderate"
        STRICT = "STRICT", "Strict"
        CUSTOM = "CUSTOM", "Custom"

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, choices=Code.choices, default=Code.CUSTOM)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "cancellation policies"

    def __str__(self) -> str:
        return self.name


class CancellationRule(TimeStampedModel):
    """Refund tiers — e.g. ``>=168h before check-in -> 100% refund``."""

    policy = models.ForeignKey(
        CancellationPolicy, on_delete=models.CASCADE, related_name="rules"
    )
    hours_before_check_in = models.PositiveIntegerField(
        help_text="Cancel at least this many hours before check-in"
    )
    guest_refund_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    refund_service_fee = models.BooleanField(default=False)

    class Meta:
        ordering = ["-hours_before_check_in"]
        unique_together = ("policy", "hours_before_check_in")

    def __str__(self) -> str:
        return f"{self.policy.name}: {self.hours_before_check_in}h -> {self.guest_refund_percent}%"


class Booking(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending"
        AWAITING_PAYMENT = "AWAITING_PAYMENT", "Awaiting Payment"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        CHECKED_IN = "CHECKED_IN", "Checked In"
        COMPLETED = "COMPLETED", "Completed"
        REFUNDED = "REFUNDED", "Refunded"
        DISPUTED = "DISPUTED", "Disputed"
        EXPIRED = "EXPIRED", "Expired"

    #: allowed transitions: {from: {to, ...}}
    TRANSITIONS = {
        Status.DRAFT: {Status.PENDING, Status.CANCELLED},
        Status.PENDING: {Status.AWAITING_PAYMENT, Status.CONFIRMED,
                         Status.CANCELLED, Status.EXPIRED},
        Status.AWAITING_PAYMENT: {Status.CONFIRMED, Status.CANCELLED,
                                  Status.EXPIRED},
        Status.CONFIRMED: {Status.CHECKED_IN, Status.CANCELLED,
                           Status.DISPUTED, Status.REFUNDED},
        Status.CHECKED_IN: {Status.COMPLETED, Status.DISPUTED, Status.REFUNDED},
        Status.COMPLETED: {Status.DISPUTED, Status.REFUNDED},
        Status.DISPUTED: {Status.CONFIRMED, Status.REFUNDED, Status.CANCELLED},
        Status.CANCELLED: set(),
        Status.REFUNDED: set(),
        Status.EXPIRED: set(),
    }

    PAYMENT_WINDOW_MINUTES = 30

    reference = models.CharField(max_length=20, unique=True, db_index=True)
    guest = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.PROTECT, related_name="bookings"
    )
    unit = models.ForeignKey(
        "properties.PropertyUnit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="bookings",
        help_text="Optional unit/room booked inside a multi-unit property.",
    )
    check_in = models.DateField(db_index=True)
    check_out = models.DateField(db_index=True)
    guests_count = models.PositiveIntegerField(default=1)
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    infants = models.PositiveIntegerField(
        default=0, help_text="Infants do not count toward max occupancy"
    )
    # Ownership snapshot — survives later property/host changes.
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="hosted_bookings", null=True, blank=True,
    )
    property_title = models.CharField(max_length=200, blank=True)
    unit_name = models.CharField(max_length=120, blank=True)
    property_address = models.CharField(max_length=255, blank=True)
    property_city_name = models.CharField(max_length=100, blank=True)
    cancellation_policy_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    currency = models.CharField(max_length=3)

    cancellation_policy = models.ForeignKey(
        CancellationPolicy, on_delete=models.SET_NULL, null=True, blank=True
    )
    cancellation_policy_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Policy name + rules at booking time",
    )

    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Deadline to pay before the booking auto-expires",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    promo_code = models.CharField(max_length=50, blank=True)
    special_requests = models.TextField(blank=True)
    idempotency_key = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
        help_text="Client-supplied Idempotency-Key; retries return the same booking",
    )

    class Meta:
        indexes = [
            models.Index(fields=["guest", "status", "-created_at"]),
            models.Index(fields=["property", "check_in", "check_out"]),
            models.Index(fields=["property", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} ({self.status})"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS.get(self.status, set())

    def payment_deadline(self):
        return timezone.now() + timedelta(minutes=self.PAYMENT_WINDOW_MINUTES)


class BookingGuest(TimeStampedModel):
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="guests"
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    is_primary = models.BooleanField(default=False)


class BookingPrice(TimeStampedModel):
    """Immutable pricing snapshot — survives later price changes by the host."""

    booking = models.OneToOneField(
        Booking, on_delete=models.CASCADE, related_name="price"
    )
    currency = models.CharField(max_length=3)
    nights = models.PositiveIntegerField()
    nightly_subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    cleaning_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Platform commission % snapshot",
    )
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    host_payout_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    nightly_detail = models.JSONField(
        default=list, help_text="[{date, price}] breakdown per night"
    )


class BookingEvent(TimeStampedModel):
    """Non-status business events — payment steps, modifications, refunds.

    Complements BookingStatusHistory (status transitions) with an ordered
    audit trail that includes the request_id for debugging.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=50, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="booking_events",
    )
    note = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["booking", "event_type"])]


class BookingNote(TimeStampedModel):
    """Notes on a booking. Internal notes are never exposed to guests."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="booking_notes",
    )
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal notes are staff/host only",
    )

    class Meta:
        ordering = ["-created_at"]


class BookingStatusHistory(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="booking_status_changes",
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class BookingCancellation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.OneToOneField(
        Booking, on_delete=models.CASCADE, related_name="cancellation"
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cancellations_made",
    )
    reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(auto_now_add=True)
    refund_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    host_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    policy_snapshot = models.JSONField(default=dict)
