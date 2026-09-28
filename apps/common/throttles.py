"""Rate limiting for sensitive endpoints."""
from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """Login/register/reset endpoints — keyed by IP."""

    scope = "auth"


class StrictAuthRateThrottle(AnonRateThrottle):
    """Verification-code and password-reset endpoints."""

    scope = "auth_strict"


class PaymentRateThrottle(AnonRateThrottle):
    scope = "payment"


class WebhookRateThrottle(AnonRateThrottle):
    scope = "webhook"
