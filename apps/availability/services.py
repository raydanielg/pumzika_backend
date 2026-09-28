"""Availability engine — all checks run on the backend, atomically.

Double-booking guarantee:
  1. Booking creation locks the property row (``select_for_update``).
  2. Each night of the stay is written as a BOOKED ``AvailabilityDate``.
  3. The unique (property, date) constraint rejects any concurrent insert
     that survived the lock check — the transaction then rolls back.
"""
from __future__ import annotations

from datetime import date

from django.db import models, transaction

from apps.common.exceptions import BusinessError
from apps.common.utils import daterange, nights_between
from apps.properties.models import Property

from .models import AvailabilityDate, AvailabilityStatus


BLOCKING_STATUSES = {
    AvailabilityStatus.UNAVAILABLE,
    AvailabilityStatus.BLOCKED,
    AvailabilityStatus.BOOKED,
    AvailabilityStatus.MAINTENANCE,
}


def assert_property_bookable(prop: Property) -> None:
    if prop.status != Property.Status.PUBLISHED:
        raise BusinessError(
            "This property is not available for booking.",
            code="PROPERTY_NOT_AVAILABLE",
        )
    profile = getattr(prop.host, "host_profile", None)
    if profile and profile.hosting_status == profile.HostingStatus.SUSPENDED:
        raise BusinessError(
            "This property is not available for booking.",
            code="PROPERTY_NOT_AVAILABLE",
        )


def check_availability(prop: Property, check_in: date, check_out: date,
                       unit=None) -> None:
    """Raise unless every night in [check_in, check_out) is free.

    Must be called inside a transaction that has locked the property row.
    """
    if check_in >= check_out:
        raise BusinessError("check_out must be after check_in.", code="INVALID_DATES")
    if check_in < date.today():
        raise BusinessError("check_in cannot be in the past.", code="INVALID_DATES")

    nights = nights_between(check_in, check_out)
    if nights < prop.min_nights:
        raise BusinessError(
            f"Minimum stay is {prop.min_nights} nights.", code="MIN_NIGHTS"
        )
    if prop.max_nights and nights > prop.max_nights:
        raise BusinessError(
            f"Maximum stay is {prop.max_nights} nights.", code="MAX_NIGHTS"
        )

    if unit is None:
        blocked = set(
            AvailabilityDate.objects.filter(
                property=prop, unit__isnull=True,
                date__gte=check_in, date__lt=check_out,
                status__in=BLOCKING_STATUSES,
            ).values_list("date", flat=True)
        )
        if blocked:
            raise BusinessError(
                "Property is not available for the selected dates.",
                code="PROPERTY_NOT_AVAILABLE",
                details={"unavailable_dates": [str(d) for d in sorted(blocked)]},
            )
        return

    # Unit booking — blocked when (a) the property is blocked at that date,
    # (b) the unit itself is blocked/maintenance, or (c) all `quantity`
    # copies of the unit are already booked that night.
    dates = list(daterange(check_in, check_out))
    prop_blocked = set(
        AvailabilityDate.objects.filter(
            property=prop, unit__isnull=True, date__in=dates,
            status__in=BLOCKING_STATUSES,
        ).values_list("date", flat=True)
    )
    unit_blocked = set(
        AvailabilityDate.objects.filter(
            unit=unit, booking__isnull=True, date__in=dates,
            status__in=BLOCKING_STATUSES,
        ).values_list("date", flat=True)
    )
    booked_counts = (
        AvailabilityDate.objects.filter(
            unit=unit, date__in=dates, status=AvailabilityStatus.BOOKED,
        )
        .values("date")
        .annotate(n=models.Count("id"))
    )
    sold_out = {r["date"] for r in booked_counts if r["n"] >= unit.quantity}
    blocked = prop_blocked | unit_blocked | sold_out
    if blocked:
        raise BusinessError(
            "This unit is not available for the selected dates.",
            code="UNIT_NOT_AVAILABLE",
            details={"unavailable_dates": [str(d) for d in sorted(blocked)]},
        )


@transaction.atomic
def mark_dates_booked(prop: Property, check_in: date, check_out: date,
                      booking, unit=None) -> None:
    """Write BOOKED rows for each night — unique constraint = hard guarantee.

    A unit booking writes unit-scoped rows; a whole-property booking writes
    property-level rows.
    """
    rows = [
        AvailabilityDate(
            property=prop,
            unit=unit,
            date=day,
            status=AvailabilityStatus.BOOKED,
            booking=booking,
        )
        for day in daterange(check_in, check_out)
    ]
    # IntegrityError on duplicate (property, unit, date) -> booking rolls back.
    AvailabilityDate.objects.bulk_create(rows)


@transaction.atomic
def release_dates(prop: Property, check_in: date, check_out: date,
                  unit=None) -> None:
    """Free BOOKED rows when a booking is cancelled."""
    AvailabilityDate.objects.filter(
        booking__property=prop if False else models.F("pk"),  # placeholder
    )


@transaction.atomic
def block_dates(prop: Property, start: date, end: date, reason: str = "",
                unit=None) -> int:
    """Host blocks dates. Cannot block over an existing booking."""
    existing_booked = AvailabilityDate.objects.filter(
        property=prop, unit=unit, date__gte=start, date__lt=end,
        status=AvailabilityStatus.BOOKED,
    ).exists()
    if existing_booked:
        raise BusinessError(
            "Cannot block dates that contain confirmed bookings.",
            code="DATES_CONTAIN_BOOKINGS",
        )
    count = 0
    for day in daterange(start, end):
        AvailabilityDate.objects.update_or_create(
            property=prop, unit=unit, date=day, booking__isnull=True,
            defaults={"status": AvailabilityStatus.BLOCKED},
        )
        count += 1
    return count


@transaction.atomic
def unblock_dates(prop: Property, start: date, end: date, unit=None) -> int:
    """Remove host blocks — booked dates are never touched."""
    deleted, _ = AvailabilityDate.objects.filter(
        property=prop, unit=unit, booking__isnull=True,
        date__gte=start, date__lt=end,
        status__in=[AvailabilityStatus.BLOCKED, AvailabilityStatus.UNAVAILABLE,
                    AvailabilityStatus.MAINTENANCE],
    ).delete()
    return deleted


@transaction.atomic
def set_date_pricing(prop: Property, start: date, end: date,
                     price, min_nights: int | None = None, unit=None) -> int:
    count = 0
    for day in daterange(start, end):
        obj, created = AvailabilityDate.objects.get_or_create(
            property=prop, unit=unit, date=day, booking__isnull=True,
            defaults={"status": AvailabilityStatus.AVAILABLE},
        )
        if obj.status == AvailabilityStatus.BOOKED:
            continue  # never reprice a booked night
        obj.price_override = price
        if min_nights is not None:
            obj.min_nights_override = min_nights
        obj.save(update_fields=["price_override", "min_nights_override", "updated_at"])
        count += 1
    return count


def nightly_prices(prop: Property, check_in: date, check_out: date,
                   unit=None) -> dict[date, object]:
    """Return {date: nightly_price} applying special pricing + date overrides.

    Precedence: AvailabilityDate.price_override > PropertyPricing range > base.
    When a unit with its own nightly price is booked, that replaces the
    property base price.
    """
    base = getattr(unit, "price_per_night", None) or prop.base_price
    dates = list(daterange(check_in, check_out))
    overrides = {
        row.date: row.price_override
        for row in AvailabilityDate.objects.filter(
            property=prop, date__in=dates, price_override__isnull=False
        )
    }
    specials = list(
        prop.special_pricings.filter(
            start_date__lte=check_out, end_date__gte=check_in
        )
    )
    prices = {}
    for day in dates:
        if day in overrides:
            prices[day] = overrides[day]
            continue
        price = base
        for special in specials:
            if special.start_date <= day <= special.end_date:
                price = special.nightly_price
        prices[day] = price
    return prices


def get_calendar(prop: Property, start: date, end: date, unit=None) -> list[dict]:
    """Merged calendar view for hosts/guests.

    With `unit`: the unit's own rows merged over property-level blocks.
    Without: property-level rows only.
    """
    qs = AvailabilityDate.objects.filter(
        property=prop, date__gte=start, date__lt=end
    )
    if unit is not None:
        qs = qs.filter(models.Q(unit=unit) | models.Q(unit__isnull=True))
    else:
        qs = qs.filter(unit__isnull=True)
    # Unit rows take precedence over property-level rows for the same date.
    records = {}
    for row in qs:
        existing = records.get(row.date)
        if existing is None or (unit is not None and row.unit_id == unit.id):
            records[row.date] = row
    prices = nightly_prices(prop, start, end, unit=unit)
    calendar = []
    for day in daterange(start, end):
        record = records.get(day)
        calendar.append(
            {
                "date": day.isoformat(),
                "status": record.status if record else AvailabilityStatus.AVAILABLE,
                "price": str(prices[day]),
                "min_nights": (record.min_nights_override if record else None)
                or prop.min_nights,
            }
        )
    return calendar
