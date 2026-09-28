"""Per-date availability records.

A row exists for a (property, date) only when it deviates from the default
(available at the property's base price). BOOKED rows are written inside the
booking transaction — the unique constraint is the database-level guarantee
against double booking.
"""
from __future__ import annotations

import uuid

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel


class AvailabilityStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"
    BLOCKED = "BLOCKED", "Blocked"          # host-defined
    BOOKED = "BOOKED", "Booked"
    MAINTENANCE = "MAINTENANCE", "Maintenance"


class AvailabilityDate(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE, related_name="availability_dates"
    )
    unit = models.ForeignKey(
        "properties.PropertyUnit", on_delete=models.CASCADE,
        null=True, blank=True, related_name="availability_dates",
        help_text="When set, this row applies to one unit inside the property.",
    )
    date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=20, choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.AVAILABLE,
    )
    price_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    min_nights_override = models.PositiveIntegerField(null=True, blank=True)
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="booked_dates",
    )

    class Meta:
        constraints = [
            # Postgres treats NULL as distinct, so split the uniqueness:
            # unit-scoped rows unique per (property, unit, date);
            # property-level rows unique per (property, date).
            # Property-level rows (booked, blocked, priced): one per date.
            models.UniqueConstraint(
                fields=["property", "date"],
                name="uniq_avail_prop_date_no_unit",
                condition=models.Q(unit__isnull=True),
            ),
            # Unit booking rows: one per booking per night — a unit with
            # quantity>1 can hold that many overlapping bookings.
            models.UniqueConstraint(
                fields=["unit", "date", "booking"],
                name="uniq_avail_unit_date_booking",
                condition=models.Q(unit__isnull=False, booking__isnull=False),
            ),
            # Unit-level host rows (blocked, maintenance, date pricing):
            # one per date, never colliding with booking rows.
            models.UniqueConstraint(
                fields=["unit", "date"],
                name="uniq_avail_unit_date_no_booking",
                condition=models.Q(unit__isnull=False, booking__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["property", "date", "status"]),
            models.Index(fields=["property", "status"]),
            models.Index(fields=["unit", "date"]),
        ]

    def __str__(self) -> str:
        return f"{self.property_id}:{self.unit_id}:{self.date}:{self.status}"
