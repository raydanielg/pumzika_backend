"""Rate limiting for sensitive endpoints.

Default rates live in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]. Each scope
may be overridden at runtime via PlatformSetting key ``RATELIMIT_<SCOPE>``
(e.g. RATELIMIT_AUTH="10/min") — no code deploy needed to tighten limits.
"""
from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle


class ConfigurableRateThrottle(AnonRateThrottle):
    """Reads its rate from PlatformSetting with the settings default."""

    def get_rate(self):
        from apps.admin_panel.models import PlatformSetting

        override = PlatformSetting.get(
            f"RATELIMIT_{self.scope.upper()}", ""
        )
        return override or super().get_rate()


class AuthRateThrottle(ConfigurableRateThrottle):
    """Login/register/reset endpoints — keyed by IP."""

    scope = "auth"


class StrictAuthRateThrottle(ConfigurableRateThrottle):
    """Verification-code and password-reset endpoints."""

    scope = "auth_strict"


class PaymentRateThrottle(ConfigurableRateThrottle):
    scope = "payment"


class WebhookRateThrottle(ConfigurableRateThrottle):
    scope = "webhook"
