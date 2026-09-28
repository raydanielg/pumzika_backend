"""Reviews — only for eligible completed bookings, one per booking."""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import UUIDModel


class RatingField(models.PositiveSmallIntegerField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("validators", [MinValueValidator(1), MaxValueValidator(5)])
        super().__init__(*args, **kwargs)


class BaseReview(UUIDModel):
    """Shared fields for all review kinds."""

    booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.PROTECT,
        related_name="%(class)s",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="%(class)s_written",
    )
    rating = RatingField()
    comment = models.TextField(blank=True)
    is_published = models.BooleanField(default=True, db_index=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="%(class)s_moderated",
    )

    class Meta:
        abstract = True


class PropertyReview(BaseReview):
    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE, related_name="reviews"
    )
    cleanliness = RatingField(null=True, blank=True)
    communication = RatingField(null=True, blank=True)
    location = RatingField(null=True, blank=True)
    value = RatingField(null=True, blank=True)
    accuracy = RatingField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["property", "is_published", "-created_at"])]


class HostReview(BaseReview):
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="reviews_received",
    )
    communication = RatingField(null=True, blank=True)
    hospitality = RatingField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["host", "is_published"])]


class GuestReview(BaseReview):
    """A host reviewing a guest after the stay."""

    guest = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="guest_reviews_received",
    )
    cleanliness = RatingField(null=True, blank=True)
    communication = RatingField(null=True, blank=True)
    house_rules_respect = RatingField(null=True, blank=True)
