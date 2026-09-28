"""Celery tasks for outbound notifications — nothing blocks a request."""
from __future__ import annotations

from celery import shared_task

from .services import notify, send_sms


@shared_task
def send_verification_code(user_id: str, purpose: str, target: str, code: str) -> None:
    """Deliver an OTP — the code is never stored in plain text server-side."""
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    if purpose == "EMAIL_VERIFY" or purpose == "PASSWORD_RESET":
        from django.core.mail import send_mail

        send_mail(
            "Your Pumzika verification code",
            f"Your code is {code}. It expires in 15 minutes.",
            None, [target], fail_silently=True,
        )
    elif purpose == "PHONE_VERIFY":
        send_sms(target, f"Your Pumzika verification code is {code}")


@shared_task
def notify_booking_created(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest", "property").filter(
        pk=booking_id
    ).first()
    if not booking:
        return
    ctx = {"reference": booking.reference, "property": booking.property.title,
           "check_in": str(booking.check_in), "check_out": str(booking.check_out)}
    notify(booking.guest, "BOOKING_CREATED",
           f"Booking {booking.reference} created",
           f"Your booking for {booking.property.title} is awaiting payment.",
           context=ctx)
    notify(booking.property.host, "BOOKING_CREATED",
           f"New booking {booking.reference}",
           f"{booking.guest.full_name} booked {booking.property.title}.",
           context=ctx)


@shared_task
def notify_booking_confirmed(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest", "property__host").filter(
        pk=booking_id
    ).first()
    if not booking:
        return
    ctx = {"reference": booking.reference, "property": booking.property.title}
    notify(booking.guest, "BOOKING_CONFIRMED",
           f"Booking {booking.reference} confirmed",
           "Your payment was received and your stay is confirmed.",
           context=ctx)
    notify(booking.property.host, "BOOKING_CONFIRMED",
           f"Booking {booking.reference} confirmed",
           "A confirmed booking is on your calendar.",
           context=ctx)


@shared_task
def notify_booking_cancelled(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest", "property__host").filter(
        pk=booking_id
    ).first()
    if not booking:
        return
    ctx = {"reference": booking.reference}
    notify(booking.guest, "BOOKING_CANCELLED",
           f"Booking {booking.reference} cancelled",
           "Your booking was cancelled.", context=ctx)
    notify(booking.property.host, "BOOKING_CANCELLED",
           f"Booking {booking.reference} cancelled",
           "A booking was cancelled.", context=ctx)


@shared_task
def notify_booking_completed(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest").filter(pk=booking_id).first()
    if not booking:
        return
    notify(booking.guest, "BOOKING_COMPLETED",
           f"Booking {booking.reference} completed",
           "Thanks for staying — tell us how it went.",
           context={"reference": booking.reference})


@shared_task
def notify_checkin_reminder(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest").filter(pk=booking_id).first()
    if booking:
        notify(booking.guest, "CHECKIN_REMINDER",
               "Check-in today",
               f"Your check-in for {booking.property.title} is today.")


@shared_task
def notify_checkout_reminder(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest", "property").filter(
        pk=booking_id
    ).first()
    if booking:
        notify(booking.guest, "CHECKOUT_REMINDER",
               "Check-out today",
               f"Your check-out for {booking.property.title} is today.")


@shared_task
def notify_review_reminder(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest").filter(pk=booking_id).first()
    if booking:
        notify(booking.guest, "REVIEW_REMINDER",
               "How was your stay?",
               "Leave a review for your recent stay.")


@shared_task
def notify_payout_completed(payout_id: str) -> None:
    from apps.payouts.models import Payout

    payout = Payout.objects.select_related("user").filter(pk=payout_id).first()
    if payout:
        notify(payout.user, "PAYOUT_COMPLETED",
               f"Payout {payout.reference} completed",
               f"{payout.amount} {payout.currency} has been paid out.")


@shared_task
def notify_new_message(message_id: str) -> None:
    from apps.messaging.models import Message

    message = Message.objects.select_related("conversation", "sender").filter(
        pk=message_id
    ).first()
    if not message:
        return
    for participant in message.conversation.participants.exclude(
        user=message.sender
    ).select_related("user"):
        notify(participant.user, "NEW_MESSAGE",
               f"New message from {message.sender.first_name}",
               message.body[:200])
