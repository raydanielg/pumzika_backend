"""Notification dispatch — templated, preference-aware, async-friendly."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import (
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
    UserNotificationSettings,
)
from .providers import EmailService, PushNotificationService, send_sms

logger = logging.getLogger("pumzika.notifications")

# Events and the channels they default to when no template/preference exists.
EVENT_DEFAULTS: dict[str, list[str]] = {
    "WELCOME": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "EMAIL_VERIFY": [NotificationChannel.EMAIL],
    "PHONE_VERIFY": [NotificationChannel.SMS],
    "PASSWORD_RESET": [NotificationChannel.EMAIL],
    "SECURITY_ALERT": [NotificationChannel.IN_APP, NotificationChannel.EMAIL,
                       NotificationChannel.SMS],
    "KYC_SUBMITTED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "KYC_DECISION": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PROPERTY_SUBMITTED": [NotificationChannel.IN_APP],
    "PROPERTY_APPROVED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PROPERTY_REJECTED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PROPERTY_SUSPENDED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_CREATED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PAYMENT_PENDING": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PAYMENT_SUCCESS": [NotificationChannel.IN_APP, NotificationChannel.EMAIL,
                        NotificationChannel.SMS],
    "PAYMENT_FAILED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_CONFIRMED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL,
                          NotificationChannel.SMS],
    "BOOKING_CANCELLED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_COMPLETED": [NotificationChannel.IN_APP],
    "BOOKING_EXPIRED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_NO_SHOW": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "CHECKIN_REMINDER": [NotificationChannel.IN_APP, NotificationChannel.SMS],
    "CHECKOUT_REMINDER": [NotificationChannel.IN_APP],
    "REVIEW_REMINDER": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "NEW_MESSAGE": [NotificationChannel.IN_APP, NotificationChannel.PUSH],
    "PAYOUT_REQUESTED": [NotificationChannel.IN_APP],
    "PAYOUT_COMPLETED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PAYOUT_FAILED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL,
                      NotificationChannel.SMS],
    "REFUND_INITIATED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "REFUND_COMPLETED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
}

# Security & transaction events must always be delivered — users cannot
# opt out of these regardless of their preferences.
CRITICAL_EVENTS = {
    "SECURITY_ALERT", "PASSWORD_RESET", "EMAIL_VERIFY", "PHONE_VERIFY",
    "PAYMENT_SUCCESS", "PAYMENT_FAILED", "PAYMENT_PENDING",
    "BOOKING_CONFIRMED", "BOOKING_CANCELLED", "BOOKING_EXPIRED",
    "BOOKING_NO_SHOW",
    "PAYOUT_FAILED", "PAYOUT_COMPLETED", "KYC_DECISION",
    "REFUND_INITIATED", "REFUND_COMPLETED",
}

# Non-critical events map onto a category switch on UserNotificationSettings.
EVENT_CATEGORY = {
    "BOOKING_CREATED": "booking_notifications",
    "CHECKIN_REMINDER": "booking_notifications",
    "CHECKOUT_REMINDER": "booking_notifications",
    "REVIEW_REMINDER": "booking_notifications",
    "BOOKING_COMPLETED": "booking_notifications",
    "NEW_MESSAGE": "message_notifications",
    "PROPERTY_SUBMITTED": "booking_notifications",
    "PROPERTY_APPROVED": "booking_notifications",
    "PROPERTY_REJECTED": "booking_notifications",
    "PROPERTY_SUSPENDED": "booking_notifications",
    "PAYOUT_REQUESTED": "booking_notifications",
    "KYC_SUBMITTED": "booking_notifications",
    "WELCOME": "marketing_notifications",
}


def _channel_enabled(user, event_type: str, channel: str) -> bool:
    if event_type in CRITICAL_EVENTS:
        return True  # security/transactional notifications cannot be muted

    settings_row, _ = UserNotificationSettings.objects.get_or_create(user=user)
    if not settings_row.channel_allowed(channel):
        return False
    category = EVENT_CATEGORY.get(event_type)
    if category and not getattr(settings_row, category):
        return False
    pref = NotificationPreference.objects.filter(
        user=user, event_type=event_type, channel=channel
    ).first()
    return pref.enabled if pref else True


def _render(event_type: str, channel: str, context: dict,
            fallback_subject: str, fallback_body: str) -> tuple[str, str]:
    template = NotificationTemplate.objects.filter(
        key=event_type, channel=channel, is_active=True
    ).first()
    if template:
        return template.render(context)
    return fallback_subject, fallback_body


def notify(user, event_type: str, subject: str, body: str,
           context: dict | None = None, channels: list[str] | None = None) -> None:
    """Create Notification records for each enabled channel.

    Records are created immediately (IN_APP is instant); external channels are
    delivered by Celery tasks so the API request never blocks.
    """
    context = context or {}
    for channel in channels or EVENT_DEFAULTS.get(event_type, [NotificationChannel.IN_APP]):
        if not _channel_enabled(user, event_type, channel):
            continue
        title, rendered_body = _render(event_type, channel, context,
                                       subject, body)
        notification = Notification.objects.create(
            user=user, channel=channel, event_type=event_type,
            title=title or subject, body=rendered_body, data=context,
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification, channel=channel
        )
        if channel == NotificationChannel.IN_APP:
            _mark(notification, delivery, Notification.Status.SENT)
        else:
            deliver_notification.delay(str(notification.id))


def _mark(notification: Notification, delivery: NotificationDelivery,
          status: str, error: str = "", provider_ref: str = "") -> None:
    now = timezone.now()
    notification.status = status
    if status == Notification.Status.SENT:
        notification.sent_at = now
        notification.error = ""
    else:
        notification.error = error[:2000]
    notification.save(
        update_fields=["status", "sent_at", "error", "updated_at"]
    )
    delivery.status = status
    delivery.attempts += 1
    delivery.error = error[:2000]
    delivery.provider_reference = provider_ref
    delivery.sent_at = now if status == NotificationDelivery.Status.SENT else None
    delivery.save()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_notification(self, notification_id: str) -> None:
    """Deliver a single non-in-app notification with retries.

    Failures update the delivery record but never roll back the business
    transaction that triggered the notification.
    """
    try:
        notification = Notification.objects.select_related("user").get(
            pk=notification_id
        )
    except Notification.DoesNotExist:
        return
    delivery = notification.deliveries.order_by("-created_at").first()
    if delivery is None:
        delivery = NotificationDelivery.objects.create(
            notification=notification, channel=notification.channel
        )
    if notification.status == Notification.Status.SENT:
        return  # idempotent — already delivered

    notification.status = Notification.Status.PROCESSING
    notification.save(update_fields=["status", "updated_at"])

    try:
        if notification.channel == NotificationChannel.EMAIL:
            EmailService.send(
                to=notification.user.email,
                subject=notification.title,
                context=notification.data,
                body_fallback=notification.body,
            )
            _mark(notification, delivery, Notification.Status.SENT)
        elif notification.channel == NotificationChannel.SMS:
            if notification.user.phone:
                ref = send_sms(notification.user.phone, notification.body)
                _mark(notification, delivery, Notification.Status.SENT,
                      provider_ref=ref)
            else:
                _mark(notification, delivery, Notification.Status.FAILED,
                      error="No phone number on file")
        elif notification.channel == NotificationChannel.PUSH:
            result = PushNotificationService.send_to_user(
                notification.user, notification.title, notification.body,
                notification.data,
            )
            if result.delivered:
                _mark(notification, delivery, Notification.Status.SENT)
            else:
                _mark(notification, delivery, Notification.Status.FAILED,
                      error="No active devices")
        else:
            # WHATSAPP — integration point for a later phase.
            _mark(notification, delivery, Notification.Status.FAILED,
                  error="Channel not implemented")
    except Exception as exc:
        _mark(notification, delivery, Notification.Status.FAILED,
              error=str(exc))
        raise self.retry(exc=exc)
