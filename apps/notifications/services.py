"""Notification dispatch — templated, preference-aware, async-friendly."""
from __future__ import annotations

import logging

from django.core.mail import send_mail
from django.utils import timezone

from .models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationTemplate,
)

logger = logging.getLogger("pumzika.notifications")

# Events and the channels they default to when no template/preference exists.
EVENT_DEFAULTS: dict[str, list[str]] = {
    "EMAIL_VERIFY": [NotificationChannel.EMAIL],
    "PHONE_VERIFY": [NotificationChannel.SMS],
    "PASSWORD_RESET": [NotificationChannel.EMAIL],
    "BOOKING_CREATED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_CONFIRMED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL,
                          NotificationChannel.SMS],
    "BOOKING_CANCELLED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "BOOKING_COMPLETED": [NotificationChannel.IN_APP],
    "CHECKIN_REMINDER": [NotificationChannel.IN_APP, NotificationChannel.SMS],
    "CHECKOUT_REMINDER": [NotificationChannel.IN_APP],
    "REVIEW_REMINDER": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PAYOUT_COMPLETED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "NEW_MESSAGE": [NotificationChannel.IN_APP],
    "PROPERTY_APPROVED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "PROPERTY_REJECTED": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "KYC_DECISION": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
}


def _channel_enabled(user, event_type: str, channel: str) -> bool:
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
        if channel == NotificationChannel.IN_APP:
            notification.status = Notification.Status.SENT
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at"])
        else:
            deliver_notification.delay(str(notification.id))


def send_sms(phone: str, message: str) -> bool:
    """SMS gateway abstraction — console backend in development."""
    from django.conf import settings

    provider = settings.SMS_PROVIDER
    if provider == "console":
        logger.info("SMS -> %s: %s", phone, message)
        return True
    # Real providers (Africa's Talking, Twilio) plug in here.
    logger.warning("SMS provider '%s' not implemented; message dropped", provider)
    return False


from celery import shared_task  # noqa: E402  (defined after helpers)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_notification(self, notification_id: str) -> None:
    """Deliver a single non-in-app notification with retries."""
    try:
        notification = Notification.objects.select_related("user").get(
            pk=notification_id
        )
    except Notification.DoesNotExist:
        return

    try:
        if notification.channel == NotificationChannel.EMAIL:
            send_mail(
                notification.title, notification.body,
                None, [notification.user.email], fail_silently=False,
            )
        elif notification.channel == NotificationChannel.SMS:
            if notification.user.phone:
                send_sms(notification.user.phone, notification.body)
        # PUSH / WHATSAPP integrate later — record stays pending until then.
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.error = ""
        notification.save(update_fields=["status", "sent_at", "error", "updated_at"])
    except Exception as exc:
        notification.status = Notification.Status.FAILED
        notification.error = str(exc)[:2000]
        notification.save(update_fields=["status", "error", "updated_at"])
        raise self.retry(exc=exc)
