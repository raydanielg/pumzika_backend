"""Payments, transactions, refunds and webhook events."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class PaymentProvider(TimeStampedModel):
    """Provider configuration is data-driven — providers are pluggable."""

    class Code(models.TextChoices):
        MOCK = "MOCK", "Mock (development)"
        SELCOM = "SELCOM", "Selcom"
        AZAMPAY = "AZAMPAY", "AzamPay"
        CARD = "CARD", "Card"
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
        STRIPE = "STRIPE", "Stripe"

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    supports_refund = models.BooleanField(default=True)
    supported_currencies = models.JSONField(default=list, blank=True)
    countries = models.JSONField(default=list, blank=True)
    config = models.JSONField(
        default=dict, blank=True,
        help_text="Non-secret config; credentials come from env vars only.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({'active' if self.is_active else 'off'})"


class Payment(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"
        REFUNDED = "REFUNDED", "Refunded"
        PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, related_name="payments"
    )
    provider = models.ForeignKey(
        PaymentProvider, on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    idempotency_key = models.CharField(max_length=64, unique=True)
    reference = models.CharField(max_length=64, unique=True, db_index=True)
    external_reference = models.CharField(
        max_length=128, blank=True, db_index=True,
        help_text="Provider-side transaction id",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["booking", "status"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["external_reference"]),
        ]

    @property
    def refundable_amount(self):
        refunded = self.refunds.filter(
            status__in=[Refund.Status.SUCCESS, Refund.Status.PROCESSING]
        ).aggregate(models.Sum("amount"))["amount__sum"] or 0
        return self.amount - refunded


class PaymentTransaction(TimeStampedModel):
    """Immutable ledger of state changes for a payment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="transactions"
    )
    event_type = models.CharField(max_length=50)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    provider_reference = models.CharField(max_length=128, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["payment", "-created_at"])]


class PaymentAttempt(TimeStampedModel):
    """Each initiation attempt — supports retries without duplicates."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="attempts"
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default="PENDING")
    error = models.TextField(blank=True)


class Refund(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="refunds"
    )
    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, related_name="refunds"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reason = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="refunds_requested",
    )
    external_reference = models.CharField(max_length=128, blank=True)
    idempotency_key = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
    )
    processed_at = models.DateTimeField(null=True, blank=True)


class RefundTransaction(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    refund = models.ForeignKey(
        Refund, on_delete=models.CASCADE, related_name="transactions"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    provider_reference = models.CharField(max_length=128, blank=True)
    raw = models.JSONField(default=dict, blank=True)


class WebhookEvent(UUIDModel):
    """Every inbound webhook — idempotency + retry bookkeeping."""

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        FAILED = "FAILED", "Failed"
        IGNORED = "IGNORED", "Ignored"

    provider = models.CharField(max_length=20, db_index=True)
    event_type = models.CharField(max_length=100, blank=True)
    external_event_id = models.CharField(max_length=128, db_index=True)
    payload_hash = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    raw_body = models.BinaryField(null=True, blank=True)
    raw_signature = models.CharField(max_length=512, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    error = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("provider", "external_event_id")
        indexes = [models.Index(fields=["status", "-received_at"])]
