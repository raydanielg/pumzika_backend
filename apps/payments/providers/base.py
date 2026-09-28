"""Payment provider abstraction — providers are replaceable.

Each provider implements PaymentProviderInterface. Concrete providers live in
their own modules (``mock.py``, ``selcom/``) and register themselves via the
registry in ``__init__.py``. Booking/payment business logic never imports a
provider class directly — it goes through ``get_provider``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Generic provider failure — never carries secrets."""

    def __init__(self, message: str, code: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.code = code


class ProviderUnavailable(ProviderError):
    """Provider unreachable / 5xx — safe to re-check later, unsafe to retry."""

    def __init__(self, message: str = "Provider unavailable"):
        super().__init__(message, code="PROVIDER_UNAVAILABLE")


class ProviderTimeout(ProviderUnavailable):
    """Network timeout talking to the provider."""

    def __init__(self, message: str = "Provider request timed out"):
        super().__init__(message)
        self.code = "NETWORK_TIMEOUT"


class InvalidRequest(ProviderError):
    """Provider rejected the request — do not retry unchanged."""

    def __init__(self, message: str = "Invalid provider request"):
        super().__init__(message, code="INVALID_REQUEST")


class VerificationFailed(ProviderError):
    """Webhook/callback could not be verified."""

    def __init__(self, message: str = "Payment verification failed"):
        super().__init__(message, code="VERIFICATION_FAILED")


class PaymentFailedByProvider(ProviderError):
    """Customer-facing payment failure reported by the provider."""

    def __init__(self, message: str = "Customer payment failed"):
        super().__init__(message, code="CUSTOMER_PAYMENT_FAILED")


@dataclass
class InitiationResult:
    provider_reference: str
    status: str  # "PENDING" | "PROCESSING" | "SUCCESS" | "FAILED"
    checkout_url: str | None = None
    raw: dict | None = None


@dataclass
class WebhookData:
    external_event_id: str
    event_type: str  # "payment.success" | "payment.failed" | "refund.success" ...
    reference: str | None = None          # our internal payment reference
    external_reference: str | None = None  # provider transaction id
    payload: dict | None = None


class PaymentProviderInterface(Protocol):
    code: str

    def initiate(self, payment, method_details: dict) -> InitiationResult: ...
    def verify_webhook(self, body: bytes, headers: dict) -> WebhookData: ...
    def refund(self, refund) -> InitiationResult: ...
    def check_status(self, payment) -> str | None:
        """Provider-side status for reconciliation — None if unsupported."""
        return None
