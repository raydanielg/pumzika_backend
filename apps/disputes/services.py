"""Dispute workflow."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.bookings.models import Booking
from apps.bookings.services import mark_disputed
from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError

from .models import (
    Dispute,
    DisputeResolution,
    DisputeStatusHistory,
)


def _record(dispute: Dispute, to_status: str, changed_by, note: str = "") -> None:
    DisputeStatusHistory.objects.create(
        dispute=dispute, from_status=dispute.status, to_status=to_status,
        changed_by=changed_by, note=note,
    )


def get_dispute_for_user(user, dispute_id) -> Dispute:
    dispute = (
        Dispute.objects.select_related("booking__guest", "booking__property__host",
                                       "opened_by")
        .filter(pk=dispute_id)
        .first()
    )
    if dispute is None:
        raise NotFoundError("Dispute not found.", code="DISPUTE_NOT_FOUND")
    if not user.is_staff_role and user.id not in (
        dispute.booking.guest_id, dispute.booking.property.host_id
    ):
        raise PermissionDeniedError("You are not a party to this dispute.")
    return dispute


@transaction.atomic
def open_dispute(user, booking_id, category: str, description: str) -> Dispute:
    booking = (
        Booking.objects.select_related("property")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    if user.id not in (booking.guest_id, booking.property.host_id):
        raise PermissionDeniedError("Only parties to the booking can dispute it.")
    if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN,
                              Booking.Status.COMPLETED):
        raise BusinessError("This booking cannot be disputed in its current state.",
                            code="BOOKING_NOT_DISPUTABLE")
    if Dispute.objects.filter(booking=booking, status__in=[
        Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW,
        Dispute.Status.WAITING_FOR_USER,
    ]).exists():
        raise BusinessError("An open dispute already exists for this booking.",
                            code="DISPUTE_EXISTS")

    dispute = Dispute.objects.create(
        booking=booking, opened_by=user, category=category,
        description=description,
    )
    _record(dispute, Dispute.Status.OPEN, user)
    mark_disputed(booking, user)
    return dispute


@transaction.atomic
def update_status(dispute: Dispute, to_status: str, changed_by, note: str = "") -> None:
    if dispute.status in (Dispute.Status.RESOLVED, Dispute.Status.CLOSED,
                          Dispute.Status.REJECTED):
        raise BusinessError("Dispute is already closed.", code="DISPUTE_CLOSED")
    _record(dispute, to_status, changed_by, note)
    dispute.status = to_status
    dispute.save(update_fields=["status", "updated_at"])


@transaction.atomic
def resolve_dispute(staff, dispute_id, outcome: str, notes: str = "",
                    refund_amount: Decimal = Decimal("0")) -> DisputeResolution:
    dispute = Dispute.objects.select_for_update().filter(pk=dispute_id).first()
    if dispute is None:
        raise NotFoundError("Dispute not found.", code="DISPUTE_NOT_FOUND")
    if dispute.status in (Dispute.Status.RESOLVED, Dispute.Status.CLOSED):
        raise BusinessError("Dispute already resolved.", code="DISPUTE_CLOSED")

    resolution = DisputeResolution.objects.create(
        dispute=dispute, resolved_by=staff, outcome=outcome,
        refund_amount=refund_amount, notes=notes,
    )
    _record(dispute, Dispute.Status.RESOLVED, staff, notes)
    dispute.status = Dispute.Status.RESOLVED
    dispute.save(update_fields=["status", "updated_at"])

    if refund_amount > 0:
        from apps.payments import services as payment_service

        payment_service.initiate_refund(
            booking=dispute.booking, amount=refund_amount,
            reason=f"Dispute resolution {dispute.id}", requested_by=staff,
        )
    return resolution
