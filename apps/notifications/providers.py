"""Outbound channel providers — swap implementations via settings, not code.

- ``EmailService`` — Django templates under ``templates/email/<slug>.{txt,html}``
  with a plain-text fallback when a slug has no file.
- ``SMSProviderInterface`` — ``ConsoleSMSProvider`` in dev; a production
  provider (Africa's Talking / Twilio) implements ``send`` and is selected
  by the ``SMS_PROVIDER`` setting.
- ``PushProviderInterface`` — ``MockPushProvider`` now; Firebase/FCM can be
  dropped in without touching callers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.mail import send_mail
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

logger = logging.getLogger("pumzika.notifications")


class ProviderError(Exception):
    """Raised when a channel provider fails — callers may retry."""


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

class EmailService:
    """Templated email sender. Views never call this — Celery tasks do."""

    DEFAULT_SUBJECT = "Pumzika Africa"

    @classmethod
    def send(cls, *, to: str, template: str = "", subject: str = "",
             context: dict | None = None, body_fallback: str = "") -> bool:
        context = context or {}
        if template:
            try:
                body = render_to_string(f"email/{template}.txt", context)
            except TemplateDoesNotExist:
                body = body_fallback
            try:
                html = render_to_string(f"email/{template}.html", context)
            except TemplateDoesNotExist:
                html = None
        else:
            body, html = body_fallback, None
        send_mail(
            subject or cls.DEFAULT_SUBJECT,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [to],
            html_message=html,
            fail_silently=False,
        )
        return True


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------

class SMSProviderInterface(Protocol):
    def send(self, phone: str, message: str) -> str:
        """Send an SMS, returning a provider reference or raising ProviderError."""


class ConsoleSMSProvider:
    """Development provider — logs instead of sending."""

    def send(self, phone: str, message: str) -> str:
        logger.info("SMS -> %s: %s", phone, message)
        return "console-ok"


class ProductionSMSProvider:
    """Placeholder for Africa's Talking / Twilio — fails loudly until wired."""

    def send(self, phone: str, message: str) -> str:
        raise ProviderError(
            "Production SMS provider is not configured. "
            "Set SMS_PROVIDER credentials or use 'console'."
        )


_SMS_PROVIDERS = {
    "console": ConsoleSMSProvider,
    "production": ProductionSMSProvider,
}


def get_sms_provider() -> SMSProviderInterface:
    cls = _SMS_PROVIDERS.get(
        getattr(settings, "SMS_PROVIDER", "console"), ConsoleSMSProvider
    )
    return cls()


def send_sms(phone: str, message: str) -> str:
    return get_sms_provider().send(phone, message)


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

@dataclass
class PushResult:
    delivered: int = 0
    provider: str = ""


class PushProviderInterface(Protocol):
    def send(self, tokens: list[str], title: str, body: str,
             data: dict | None = None) -> PushResult:
        """Deliver a push to device tokens or raise ProviderError."""


class MockPushProvider:
    """Sandbox provider — logs, never pretends FCM was contacted."""

    def send(self, tokens: list[str], title: str, body: str,
             data: dict | None = None) -> PushResult:
        logger.info("PUSH(mock) -> %d device(s): %s", len(tokens), title)
        return PushResult(delivered=len(tokens), provider="mock")


class PushNotificationService:
    """Fan-out to all of a user's active devices."""

    provider: PushProviderInterface = MockPushProvider()

    @classmethod
    def send_to_user(cls, user, title: str, body: str,
                     data: dict | None = None) -> PushResult:
        from .models import UserDevice

        tokens = list(
            UserDevice.objects.filter(user=user, is_active=True)
            .exclude(push_token="")
            .values_list("push_token", flat=True)
        )
        if not tokens:
            return PushResult(delivered=0, provider="none")
        return cls.provider.send(tokens, title, body, data)
