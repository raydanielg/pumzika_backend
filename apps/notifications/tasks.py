"""Celery tasks for outbound notifications — nothing blocks a request."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .providers import send_sms
from .services import notify

logger = logging.getLogger("pumzika.notifications")


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


# ---------------------------------------------------------------------------
# Account events
# ---------------------------------------------------------------------------

@shared_task
def notify_welcome(user_id: str) -> None:
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if user:
        notify(user, "WELCOME", "Welcome to Pumzika Africa",
               f"Hi {user.first_name}, your account is ready.",
               context={"name": user.first_name})


@shared_task
def notify_security_alert(user_id: str, event: str) -> None:
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if user:
        notify(user, "SECURITY_ALERT", "Security alert",
               f"A security event occurred on your account: {event}. "
               "If this wasn't you, reset your password immediately.",
               context={"event": event})


# ---------------------------------------------------------------------------
# KYC / host events
# ---------------------------------------------------------------------------

@shared_task
def notify_kyc_submitted(user_id: str) -> None:
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if user:
        notify(user, "KYC_SUBMITTED", "KYC submitted",
               "Your verification documents are under review.")


@shared_task
def notify_kyc_decision(user_id: str, approved: bool, reason: str = "") -> None:
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if not user:
        return
    if approved:
        notify(user, "KYC_DECISION", "Verification approved",
               "Your identity verification was approved.")
    else:
        notify(user, "KYC_DECISION", "Verification rejected",
               f"Your verification was rejected. {reason}",
               context={"reason": reason})


# ---------------------------------------------------------------------------
# Property events
# ---------------------------------------------------------------------------

@shared_task
def notify_property_event(property_id: str, event_type: str,
                          reason: str = "") -> None:
    from apps.properties.models import Property

    prop = Property.objects.select_related("host").filter(pk=property_id).first()
    if not prop:
        return
    titles = {
        "PROPERTY_SUBMITTED": f"'{prop.title}' submitted for review",
        "PROPERTY_APPROVED": f"'{prop.title}' approved",
        "PROPERTY_REJECTED": f"'{prop.title}' rejected",
        "PROPERTY_SUSPENDED": f"'{prop.title}' suspended",
    }
    bodies = {
        "PROPERTY_SUBMITTED": "Our team will review your listing shortly.",
        "PROPERTY_APPROVED": "Your listing is approved and ready to publish.",
        "PROPERTY_REJECTED": f"Reason: {reason}",
        "PROPERTY_SUSPENDED": f"Reason: {reason}",
    }
    notify(prop.host, event_type, titles.get(event_type, event_type),
           bodies.get(event_type, ""), context={"reason": reason})


# ---------------------------------------------------------------------------
# Payment / payout / refund events
# ---------------------------------------------------------------------------

@shared_task
def notify_payment_pending(payment_id: str) -> None:
    from apps.payments.models import Payment

    payment = Payment.objects.select_related("booking__guest").filter(
        pk=payment_id
    ).first()
    if payment:
        notify(payment.booking.guest, "PAYMENT_PENDING",
               f"Payment {payment.reference} pending",
               f"Complete your payment of {payment.amount} {payment.currency} "
               f"to confirm booking {payment.booking.reference}.",
               context={"payment_reference": payment.reference})


@shared_task
def notify_payment_success(payment_id: str) -> None:
    from apps.payments.models import Payment

    payment = Payment.objects.select_related(
        "booking__guest", "booking__property__host"
    ).filter(pk=payment_id).first()
    if not payment:
        return
    ctx = {"payment_reference": payment.reference,
           "booking_reference": payment.booking.reference}
    notify(payment.booking.guest, "PAYMENT_SUCCESS",
           f"Payment {payment.reference} received",
           f"Receipt: {payment.amount} {payment.currency} for "
           f"{payment.booking.property.title}.", context=ctx)
    notify(payment.booking.property.host, "PAYMENT_SUCCESS",
           "Payment received",
           f"Guest payment for booking {payment.booking.reference} confirmed.",
           context=ctx)


@shared_task
def notify_payment_failed(payment_id: str) -> None:
    from apps.payments.models import Payment

    payment = Payment.objects.select_related("booking__guest").filter(
        pk=payment_id
    ).first()
    if payment:
        notify(payment.booking.guest, "PAYMENT_FAILED",
               f"Payment {payment.reference} failed",
               "Your payment could not be completed. You can retry while "
               "your booking is still held.",
               context={"payment_reference": payment.reference})


@shared_task
def notify_payout_requested(payout_id: str) -> None:
    from apps.payouts.models import Payout

    payout = Payout.objects.select_related("user").filter(pk=payout_id).first()
    if payout:
        notify(payout.user, "PAYOUT_REQUESTED",
               f"Payout {payout.reference} requested",
               f"Your payout of {payout.amount} {payout.currency} is being "
               "reviewed.")


@shared_task
def notify_payout_failed(payout_id: str) -> None:
    from apps.payouts.models import Payout

    payout = Payout.objects.select_related("user").filter(pk=payout_id).first()
    if payout:
        notify(payout.user, "PAYOUT_FAILED",
               f"Payout {payout.reference} failed",
               f"Your payout was not completed. Reason: "
               f"{payout.rejection_reason or 'contact support'}.")


@shared_task
def notify_refund_initiated(refund_id: str) -> None:
    from apps.payments.models import Refund

    refund = Refund.objects.select_related("booking__guest").filter(
        pk=refund_id
    ).first()
    if refund:
        notify(refund.booking.guest, "REFUND_INITIATED",
               "Refund initiated",
               f"A refund of {refund.amount} {refund.currency} for booking "
               f"{refund.booking.reference} is being processed.")


@shared_task
def notify_refund_completed(refund_id: str) -> None:
    from apps.payments.models import Refund

    refund = Refund.objects.select_related("booking__guest").filter(
        pk=refund_id
    ).first()
    if refund:
        notify(refund.booking.guest, "REFUND_COMPLETED",
               "Refund completed",
               f"Your refund of {refund.amount} {refund.currency} has been "
               "completed.")


@shared_task
def notify_booking_expired(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related(
        "guest", "property__host"
    ).filter(pk=booking_id).first()
    if not booking:
        return
    ctx = {"reference": booking.reference}
    notify(booking.guest, "BOOKING_EXPIRED",
           f"Booking {booking.reference} expired",
           "Your unpaid booking expired and the dates were released.",
           context=ctx)
    notify(booking.property.host, "BOOKING_EXPIRED",
           f"Booking {booking.reference} expired",
           "An unpaid booking expired; the dates are available again.",
           context=ctx)


# ---------------------------------------------------------------------------
# Periodic maintenance
# ---------------------------------------------------------------------------

@shared_task
def cleanup_stale_notifications(days: int = 90) -> int:
    """Delete read IN_APP notifications older than N days. Idempotent."""
    from datetime import timedelta

    from apps.notifications.models import Notification

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = Notification.objects.filter(
        status=Notification.Status.READ,
        channel="IN_APP",
        created_at__lt=cutoff,
    ).delete()
    return deleted


@shared_task
def retry_failed_webhooks() -> int:
    """Retry failed webhook events — safe to run repeatedly."""
    from apps.payments.models import WebhookEvent
    from apps.payments import services as payment_services

    retried = 0
    events = WebhookEvent.objects.filter(
        status=WebhookEvent.Status.FAILED, retry_count__lt=5
    )[:50]
    for event in events:
        try:
            payment_services.process_webhook(
                event.provider,
                event.raw_body or b"",
                {"x-webhook-signature": event.raw_signature or ""},
            )
            retried += 1
        except Exception:
            logger.exception("Webhook retry failed", extra={
                "event_id": event.external_event_id,
            })
    return retried


@shared_task
def notify_booking_no_show(booking_id: str) -> None:
    from apps.bookings.models import Booking

    booking = Booking.objects.select_related("guest", "property").filter(
        pk=booking_id
    ).first()
    if not booking:
        return
    ctx = {"reference": booking.reference}
    notify(booking.guest, "BOOKING_NO_SHOW",
           f"Booking {booking.reference} marked as no-show",
           f"Your booking for {booking.property.title} was marked as a no-show. "
           "If this is incorrect, contact support.",
           context=ctx)
    notify(booking.property.host, "BOOKING_NO_SHOW",
           f"No-show recorded for {booking.reference}",
           f"The guest for {booking.property.title} did not check in. "
           "Your earnings were credited as usual.",
           context=ctx)
