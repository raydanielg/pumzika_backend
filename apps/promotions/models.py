"""Configurable promotions — codes, scopes, limits."""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class Promotion(UUIDModel):
    class DiscountType(models.TextChoices):
        PERCENT = "PERCENT", "Percent"
        FIXED = "FIXED", "Fixed Amount"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    value = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    currency = models.CharField(
        max_length=3, blank=True,
        help_text="Required for FIXED discounts",
    )
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    per_user_limit = models.PositiveIntegerField(default=1)
    min_booking_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    max_discount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Cap for PERCENT discounts",
    )
    country = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.CASCADE,
        help_text="NULL = all countries",
    )
    properties = models.ManyToManyField(
        "properties.Property", blank=True, related_name="promotions",
        help_text="Empty = applies to all properties",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    times_used = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["code", "is_active"])]

    def __str__(self) -> str:
        return self.code


class PromotionUsage(TimeStampedModel):
    """Every application of a promo — one per booking, prevents re-use."""

    promotion = models.ForeignKey(
        Promotion, on_delete=models.CASCADE, related_name="usages"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="promotion_usages",
    )
    booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.PROTECT,
        related_name="promotion_usage",
    )
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        unique_together = ("promotion", "booking")
        indexes = [models.Index(fields=["promotion", "user"])]
