"""Booking maintenance jobs — expiry sweep, reminders."""
from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from .models import Booking
from . import services


@shared_task
def expire_unpaid_bookings() -> int:
    """Release dates for bookings whose payment window has elapsed."""
    expired = Booking.objects.filter(
        status__in=[Booking.Status.PENDING, Booking.Status.AWAITING_PAYMENT],
        expires_at__lt=timezone.now(),
    )
    count = 0
    for booking in expired.iterator():
        services.expire_booking(booking)
        count += 1
    return count


@shared_task
def send_checkin_reminders() -> int:
    from apps.notifications.tasks import notify_checkin_reminder

    today = timezone.now().date()
    bookings = Booking.objects.filter(
        status=Booking.Status.CONFIRMED, check_in=today
    ).values_list("id", flat=True)
    for booking_id in bookings:
        notify_checkin_reminder.delay(str(booking_id))
    return len(bookings)


@shared_task
def send_checkout_reminders() -> int:
    from apps.notifications.tasks import notify_checkout_reminder

    today = timezone.now().date()
    bookings = Booking.objects.filter(
        status=Booking.Status.CHECKED_IN, check_out=today
    ).values_list("id", flat=True)
    for booking_id in bookings:
        notify_checkout_reminder.delay(str(booking_id))
    return len(bookings)


@shared_task
def auto_complete_checkouts() -> int:
    """CHECKED_IN bookings whose checkout date has passed -> COMPLETED.

    Idempotent — complete_booking only transitions CHECKED_IN bookings, so a
    repeated run is a no-op.
    """
    cutoff = timezone.now().date()
    bookings = Booking.objects.filter(
        status=Booking.Status.CHECKED_IN, check_out__lt=cutoff
    )
    count = 0
    for booking in bookings.iterator():
        try:
            services.complete_booking(booking)
            count += 1
        except Exception:
            continue
    return count


@shared_task
def send_review_reminders() -> int:
    from apps.notifications.tasks import notify_review_reminder

    today = timezone.now().date()
    bookings = Booking.objects.filter(
        status=Booking.Status.COMPLETED, check_out=today
    ).values_list("id", flat=True)
    for booking_id in bookings:
        notify_review_reminder.delay(str(booking_id))
    return len(bookings)
