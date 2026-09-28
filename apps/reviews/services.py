"""Review rules — eligibility + dedupe enforced server-side."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Avg

from apps.bookings.models import Booking
from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError

from .models import GuestReview, HostReview, PropertyReview


def _eligible_booking(booking_id) -> Booking:
    booking = (
        Booking.objects.select_related("property")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    if booking.status != Booking.Status.COMPLETED:
        raise BusinessError(
            "Only completed stays can be reviewed.", code="BOOKING_NOT_COMPLETED"
        )
    return booking


def _refresh_property_rating(property_id) -> None:
    from apps.properties.models import Property

    stats = PropertyReview.objects.filter(
        property_id=property_id, is_published=True
    ).aggregate(avg=Avg("rating"), count=models_count())
    Property.objects.filter(pk=property_id).update(
        rating=Decimal(str(round(stats["avg"] or 0, 2))),
        review_count=stats["count"],
    )


def models_count():
    from django.db.models import Count

    return Count("id")


def _refresh_host_rating(host_id) -> None:
    from apps.accounts.models import HostProfile

    stats = HostReview.objects.filter(
        host_id=host_id, is_published=True
    ).aggregate(avg=Avg("rating"))
    HostProfile.objects.filter(user_id=host_id).update(
        rating=Decimal(str(round(stats["avg"] or 0, 2)))
    )


@transaction.atomic
def create_property_review(user, booking_id: str, rating: int, comment: str = "",
                           **sub_ratings) -> PropertyReview:
    booking = _eligible_booking(booking_id)
    if booking.guest_id != user.id:
        raise PermissionDeniedError("Only the guest of this booking can review it.")
    if PropertyReview.objects.filter(booking=booking).exists():
        raise BusinessError("This booking has already been reviewed.",
                            code="REVIEW_EXISTS")
    review = PropertyReview.objects.create(
        booking=booking, reviewer=user, property=booking.property,
        rating=rating, comment=comment, **sub_ratings,
    )
    _refresh_property_rating(booking.property_id)
    return review


@transaction.atomic
def create_host_review(user, booking_id: str, rating: int, comment: str = "",
                       **sub_ratings) -> HostReview:
    booking = _eligible_booking(booking_id)
    if booking.guest_id != user.id:
        raise PermissionDeniedError("Only the guest of this booking can review it.")
    if HostReview.objects.filter(booking=booking).exists():
        raise BusinessError("This booking has already been reviewed.",
                            code="REVIEW_EXISTS")
    review = HostReview.objects.create(
        booking=booking, reviewer=user, host=booking.property.host,
        rating=rating, comment=comment, **sub_ratings,
    )
    _refresh_host_rating(booking.property.host_id)
    return review


@transaction.atomic
def create_guest_review(host_user, booking_id: str, rating: int, comment: str = "",
                        **sub_ratings) -> GuestReview:
    booking = _eligible_booking(booking_id)
    if booking.property.host_id != host_user.id:
        raise PermissionDeniedError("Only the host of this booking can review the guest.")
    if GuestReview.objects.filter(booking=booking).exists():
        raise BusinessError("This booking has already been reviewed.",
                            code="REVIEW_EXISTS")
    return GuestReview.objects.create(
        booking=booking, reviewer=host_user, guest=booking.guest,
        rating=rating, comment=comment, **sub_ratings,
    )


@transaction.atomic
def moderate_review(review, publish: bool, moderator) -> None:
    review.is_published = publish
    review.moderated_by = moderator
    review.save(update_fields=["is_published", "moderated_by", "updated_at"])
    if isinstance(review, PropertyReview):
        _refresh_property_rating(review.property_id)
    elif isinstance(review, HostReview):
        _refresh_host_rating(review.host_id)
