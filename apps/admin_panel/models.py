"""Platform configuration + audit trail — all business values live here."""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel


class PlatformSetting(TimeStampedModel):
    """Key/value store for database-driven configuration."""

    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.JSONField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key

    @classmethod
    def get(cls, key: str, default=None):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default

    @classmethod
    def get_decimal(cls, key: str, default: str = "0") -> Decimal:
        value = cls.get(key, default)
        return Decimal(str(value))

    @classmethod
    def set(cls, key: str, value, description: str = "") -> "PlatformSetting":
        row, _ = cls.objects.update_or_create(
            key=key, defaults={"value": value, "description": description}
        )
        return row


# Well-known keys (documented, not hardcoded values)
SETTING_SERVICE_FEE_PERCENT = "SERVICE_FEE_PERCENT"
SETTING_DEFAULT_COMMISSION_PERCENT = "DEFAULT_COMMISSION_PERCENT"
SETTING_MIN_BOOKING_AMOUNT = "MIN_BOOKING_AMOUNT"
SETTING_MAX_BOOKING_AMOUNT = "MAX_BOOKING_AMOUNT"
SETTING_SUPPORTED_CURRENCIES = "SUPPORTED_CURRENCIES"
SETTING_MAINTENANCE_MODE = "MAINTENANCE_MODE"
SETTING_BOOKING_PAYMENT_WINDOW_MINUTES = "BOOKING_PAYMENT_WINDOW_MINUTES"
SETTING_PAYOUT_MINIMUM = "PAYOUT_MINIMUM"


class CommissionRule(TimeStampedModel):
    """Commission resolution order: HOST > PROPERTY_TYPE > COUNTRY > global."""

    class Scope(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        COUNTRY = "COUNTRY", "Country"
        PROPERTY_TYPE = "PROPERTY_TYPE", "Property Type"
        HOST = "HOST", "Host"

    scope = models.CharField(max_length=20, choices=Scope.choices)
    percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    country = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.CASCADE
    )
    property_type = models.ForeignKey(
        "properties.PropertyType", null=True, blank=True, on_delete=models.CASCADE
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["scope", "is_active"])]


class TaxRule(TimeStampedModel):
    """Country-level tax configuration (VAT, tourism levy, ...)."""

    name = models.CharField(max_length=100)
    country = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.CASCADE,
        help_text="NULL = applies globally",
    )
    percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["country", "is_active"])]


class AuditLog(TimeStampedModel):
    """Append-only audit trail for security/admin actions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_events",
    )
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
