"""Availability engine — all checks run on the backend, atomically.

Double-booking guarantee:
  1. Booking creation locks the property row (``select_for_update``).
  2. Each night of the stay is written as a BOOKED ``AvailabilityDate``.
  3. The unique (property, date) constraint rejects any concurrent insert
     that survived the lock check — the transaction then rolls back.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction

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


def check_availability(prop: Property, check_in: date, check_out: date) -> None:
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

    blocked = set(
        AvailabilityDate.objects.filter(
            property=prop,
            date__gte=check_in,
            date__lt=check_out,
            status__in=BLOCKING_STATUSES,
        ).values_list("date", flat=True)
    )
    if blocked:
        raise BusinessError(
            "Property is not available for the selected dates.",
            code="PROPERTY_NOT_AVAILABLE",
            details={"unavailable_dates": [str(d) for d in sorted(blocked)]},
        )


@transaction.atomic
def mark_dates_booked(prop: Property, check_in: date, check_out: date, booking) -> None:
    """Write BOOKED rows for each night — unique constraint = hard guarantee."""
    rows = [
        AvailabilityDate(
            property=prop,
            date=day,
            status=AvailabilityStatus.BOOKED,
            booking=booking,
        )
        for day in daterange(check_in, check_out)
    ]
    # IntegrityError on duplicate (property, date) -> booking rolls back.
    AvailabilityDate.objects.bulk_create(rows)


@transaction.atomic
def release_dates(prop: Property, check_in: date, check_out: date) -> None:
    """Free BOOKED rows when a booking is cancelled."""
    AvailabilityDate.objects.filter(
        property=prop,
        date__gte=check_in,
        date__lt=check_out,
        status=AvailabilityStatus.BOOKED,
    ).delete()


@transaction.atomic
def block_dates(prop: Property, start: date, end: date, reason: str = "") -> int:
    """Host blocks dates. Cannot block over an existing booking."""
    existing_booked = AvailabilityDate.objects.filter(
        property=prop, date__gte=start, date__lt=end,
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
            property=prop, date=day,
            defaults={"status": AvailabilityStatus.BLOCKED},
        )
        count += 1
    return count


@transaction.atomic
def unblock_dates(prop: Property, start: date, end: date) -> int:
    """Remove host blocks — booked dates are never touched."""
    deleted, _ = AvailabilityDate.objects.filter(
        property=prop, date__gte=start, date__lt=end,
        status__in=[AvailabilityStatus.BLOCKED, AvailabilityStatus.UNAVAILABLE,
                    AvailabilityStatus.MAINTENANCE],
    ).delete()
    return deleted


@transaction.atomic
def set_date_pricing(prop: Property, start: date, end: date,
                     price, min_nights: int | None = None) -> int:
    count = 0
    for day in daterange(start, end):
        obj, created = AvailabilityDate.objects.get_or_create(
            property=prop, date=day,
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


def nightly_prices(prop: Property, check_in: date, check_out: date) -> dict[date, object]:
    """Return {date: nightly_price} applying special pricing + date overrides.

    Precedence: AvailabilityDate.price_override > PropertyPricing range > base.
    """
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
        price = prop.base_price
        for special in specials:
            if special.start_date <= day <= special.end_date:
                price = special.nightly_price
        prices[day] = price
    return prices


def get_calendar(prop: Property, start: date, end: date) -> list[dict]:
    """Merged calendar view for hosts/guests."""
    records = {
        row.date: row
        for row in AvailabilityDate.objects.filter(
            property=prop, date__gte=start, date__lt=end
        )
    }
    prices = nightly_prices(prop, start, end)
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
