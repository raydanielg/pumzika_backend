"""Booking lifecycle — creation, confirmation, check-in/out, cancellation.

Concurrency strategy: booking creation takes a row lock on the Property
(``select_for_update``) inside a transaction, validates availability, then
writes BOOKED ``AvailabilityDate`` rows whose unique (property, date)
constraint is the database-level guarantee against double booking.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.admin_panel import services as settings_service
from apps.admin_panel.services import audit
from apps.availability import services as availability
from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError
from apps.common.utils import generate_reference
from apps.properties.models import Property

from .cancellation import compute_cancellation, policy_snapshot
from .models import (
    Booking,
    BookingCancellation,
    BookingPrice,
    BookingStatusHistory,
)
from .pricing import compute_quote


def get_booking(booking_id) -> Booking:
    booking = (
        Booking.objects.select_related("property__host__host_profile", "guest", "price")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    return booking


def get_booking_for_user(booking_id, user) -> Booking:
    booking = get_booking(booking_id)
    if not (
        booking.guest_id == user.id
        or booking.property.host_id == user.id
        or user.is_staff_role
    ):
        raise PermissionDeniedError("You cannot access this booking.")
    return booking


def _record(booking: Booking, to_status: str, changed_by=None, note: str = "") -> None:
    BookingStatusHistory.objects.create(
        booking=booking, from_status=booking.status, to_status=to_status,
        changed_by=changed_by, note=note,
    )


def _transition(booking: Booking, to_status: str, changed_by=None, note: str = "") -> None:
    if not booking.can_transition_to(to_status):
        raise BusinessError(
            f"Cannot move booking from {booking.status} to {to_status}.",
            code="INVALID_BOOKING_TRANSITION",
        )
    _record(booking, to_status, changed_by, note)
    booking.status = to_status


def quote_for_property(prop: Property, check_in: date, check_out: date,
                       promo_code: str = "", guest=None) -> dict:
    """Public price preview — same engine used at booking creation."""
    availability.check_availability(prop, check_in, check_out)
    discount = Decimal("0")
    promo = None
    if promo_code:
        from apps.promotions import services as promo_service

        promo, discount = promo_service.validate_for_booking(
            promo_code, prop, guest, check_in, check_out
        )
    breakdown = compute_quote(prop, check_in, check_out, discount)
    return breakdown.as_dict()


@transaction.atomic
def create_booking(guest, *, property_id, check_in: date, check_out: date,
                   guests_count: int, promo_code: str = "",
                   special_requests: str = "", guest_details: list | None = None,
                   request=None) -> Booking:
    """Create a PENDING booking and lock the dates atomically."""
    prop = (
        Property.objects.select_for_update()
        .select_related("host__host_profile", "country", "property_type")
        .filter(pk=property_id)
        .first()
    )
    if prop is None:
        raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
    if prop.host_id == guest.id:
        raise BusinessError("You cannot book your own property.", code="SELF_BOOKING")

    availability.assert_property_bookable(prop)
    if guests_count > prop.max_guests:
        raise BusinessError(
            f"This property allows at most {prop.max_guests} guests.",
            code="TOO_MANY_GUESTS",
        )
    availability.check_availability(prop, check_in, check_out)

    promo = None
    discount = Decimal("0")
    if promo_code:
        from apps.promotions import services as promo_service

        promo, discount = promo_service.validate_for_booking(
            promo_code, prop, guest, check_in, check_out
        )

    breakdown = compute_quote(prop, check_in, check_out, discount)

    min_amount = settings_service.min_booking_amount()
    max_amount = settings_service.max_booking_amount()
    if breakdown.total < min_amount:
        raise BusinessError("Booking total is below the minimum.",
                            code="BELOW_MIN_BOOKING_AMOUNT")
    if breakdown.total > max_amount:
        raise BusinessError("Booking total exceeds the maximum.",
                            code="ABOVE_MAX_BOOKING_AMOUNT")

    booking = Booking.objects.create(
        reference=generate_reference("BKG"),
        guest=guest,
        property=prop,
        check_in=check_in,
        check_out=check_out,
        guests_count=guests_count,
        currency=prop.currency,
        cancellation_policy=prop.cancellation_policy,
        cancellation_policy_snapshot=policy_snapshot(prop.cancellation_policy),
        expires_at=booking_payment_deadline(),
        promo_code=promo.code if promo else "",
        special_requests=special_requests,
    )
    BookingPrice.objects.create(
        booking=booking,
        currency=breakdown.currency,
        nights=breakdown.nights,
        nightly_subtotal=breakdown.nightly_subtotal,
        cleaning_fee=breakdown.cleaning_fee,
        service_fee=breakdown.service_fee,
        tax=breakdown.tax,
        discount=breakdown.discount,
        total=breakdown.total,
        commission_rate=breakdown.commission_rate,
        commission_amount=breakdown.commission_amount,
        host_payout_amount=breakdown.host_payout_amount,
        nightly_detail=breakdown.nightly_detail,
    )
    if guest_details:
        booking.guests.bulk_create(
            [booking.guests.model(booking=booking, **g) for g in guest_details]
        )

    # DB-level double-booking guard — IntegrityError aborts the transaction.
    availability.mark_dates_booked(prop, check_in, check_out, booking)

    if promo:
        promo_service = __import__("apps.promotions.services", fromlist=["x"])
        promo_service.record_usage(promo, guest, booking)

    _record(booking, Booking.Status.PENDING, changed_by=guest)
    audit(actor=guest, action="booking.created", target=booking, request=request)

    from apps.notifications.tasks import notify_booking_created

    notify_booking_created.delay(str(booking.id))
    return booking


def booking_payment_deadline():
    minutes = int(settings_service.PlatformSetting.get(
        "BOOKING_PAYMENT_WINDOW_MINUTES", Booking.PAYMENT_WINDOW_MINUTES
    ))
    return timezone.now() + timedelta(minutes=minutes)


@transaction.atomic
def mark_awaiting_payment(booking: Booking) -> None:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _transition(booking, Booking.Status.AWAITING_PAYMENT)
    booking.save(update_fields=["status", "updated_at"])


@transaction.atomic
def confirm_booking(booking: Booking, changed_by=None, note: str = "") -> Booking:
    """Called by the payment layer when payment succeeds — never by clients."""
    booking = (
        Booking.objects.select_for_update()
        .select_related("property__host")
        .get(pk=booking.pk)
    )
    if booking.status == Booking.Status.CONFIRMED:
        return booking  # idempotent — a duplicate webhook is a no-op
    _transition(booking, Booking.Status.CONFIRMED, changed_by, note)
    booking.confirmed_at = timezone.now()
    booking.expires_at = None
    booking.save(update_fields=["status", "confirmed_at", "expires_at", "updated_at"])

    host = booking.property.host
    from apps.accounts.models import HostProfile

    HostProfile.objects.filter(user=host).update(
        total_bookings=models_f("total_bookings") + 1
    )

    from apps.notifications.tasks import notify_booking_confirmed

    notify_booking_confirmed.delay(str(booking.id))
    return booking


def models_f(field: str):
    from django.db.models import F

    return F(field)


@transaction.atomic
def cancel_booking(booking: Booking, cancelled_by, reason: str = "") -> Booking:
    """Guest/host/admin cancellation — refund computed by the engine."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    result = compute_cancellation(booking)
    if not result.allowed:
        raise BusinessError(result.reason, code="CANCELLATION_NOT_ALLOWED")

    _transition(booking, Booking.Status.CANCELLED, cancelled_by, reason)
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    BookingCancellation.objects.create(
        booking=booking,
        cancelled_by=cancelled_by,
        reason=reason,
        refund_amount=result.refund_amount,
        host_amount=result.host_amount,
        policy_snapshot=booking.cancellation_policy_snapshot,
    )
    availability.release_dates(booking.property, booking.check_in, booking.check_out)

    # Money only moves if a payment was actually captured.
    if result.refund_amount > 0:
        from apps.payments import services as payment_service

        payment_service.initiate_refund(
            booking=booking, amount=result.refund_amount,
            reason=f"Cancellation: {result.reason}", requested_by=cancelled_by,
        )

    from apps.notifications.tasks import notify_booking_cancelled

    notify_booking_cancelled.delay(str(booking.id))
    return booking


@transaction.atomic
def expire_booking(booking: Booking) -> None:
    """Payment window elapsed — release the dates."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status in (Booking.Status.PENDING, Booking.Status.AWAITING_PAYMENT):
        _transition(booking, Booking.Status.EXPIRED, note="Payment window expired")
        booking.save(update_fields=["status", "updated_at"])
        availability.release_dates(booking.property, booking.check_in, booking.check_out)


@transaction.atomic
def check_in(booking: Booking, changed_by) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if timezone.now().date() < booking.check_in:
        raise BusinessError("Cannot check in before the check-in date.",
                            code="TOO_EARLY")
    _transition(booking, Booking.Status.CHECKED_IN, changed_by)
    booking.checked_in_at = timezone.now()
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])
    return booking


@transaction.atomic
def complete_booking(booking: Booking, changed_by=None) -> Booking:
    """Check-out -> completed. Makes host earnings eligible for payout."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _transition(booking, Booking.Status.COMPLETED, changed_by)
    booking.completed_at = timezone.now()
    booking.save(update_fields=["status", "completed_at", "updated_at"])

    from apps.payouts.services import credit_host_for_booking

    credit_host_for_booking(booking)

    from apps.notifications.tasks import notify_booking_completed

    notify_booking_completed.delay(str(booking.id))
    return booking


@transaction.atomic
def mark_disputed(booking: Booking, changed_by=None) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    _transition(booking, Booking.Status.DISPUTED, changed_by)
    booking.save(update_fields=["status", "updated_at"])
    return booking
