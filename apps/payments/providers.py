"""Payment provider abstraction — providers are replaceable.

Each provider implements PaymentProviderInterface. The MOCK provider is a
clearly-labelled sandbox implementation for development/testing — it never
pretends to be a real integration. Real providers (Selcom, AzamPay, Stripe)
slot in by implementing the same interface and registering below.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings


class ProviderError(Exception):
    pass


@dataclass
class InitiationResult:
    provider_reference: str
    status: str  # "PENDING" | "SUCCESS" | "FAILED"
    checkout_url: str | None = None
    raw: dict | None = None


@dataclass
class WebhookData:
    external_event_id: str
    event_type: str  # "payment.success" | "payment.failed" | "refund.success" ...
    reference: str | None = None
    external_reference: str | None = None
    payload: dict | None = None


class PaymentProviderInterface(Protocol):
    code: str

    def initiate(self, payment, method_details: dict) -> InitiationResult: ...
    def verify_webhook(self, body: bytes, headers: dict) -> WebhookData: ...
    def refund(self, refund) -> InitiationResult: ...


def _mock_secret() -> str:
    return getattr(settings, "MOCK_PAYMENT_SECRET", "mock-webhook-secret")


class MockProvider:
    """Sandbox provider for development. No real money moves.

    Webhooks are HMAC-signed exactly like real providers so the webhook
    pipeline is exercised end-to-end.
    """

    code = "MOCK"

    def initiate(self, payment, method_details: dict) -> InitiationResult:
        ref = f"MOCK-{uuid.uuid4().hex[:12].upper()}"
        return InitiationResult(
            provider_reference=ref,
            status="PENDING",
            checkout_url=(
                f"{settings.FRONTEND_BASE_URL}/mock-checkout/{payment.id}?ref={ref}"
            ),
            raw={"sandbox": True, "provider_reference": ref},
        )

    def verify_webhook(self, body: bytes, headers: dict) -> WebhookData:
        signature = headers.get("x-webhook-signature", "")
        expected = hmac.new(_mock_secret().encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ProviderError("Invalid webhook signature")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON payload") from exc
        return WebhookData(
            external_event_id=data["event_id"],
            event_type=data["event_type"],
            reference=data.get("data", {}).get("reference"),
            external_reference=data.get("data", {}).get("external_reference"),
            payload=data,
        )

    def refund(self, refund) -> InitiationResult:
        return InitiationResult(
            provider_reference=f"MOCKRF-{uuid.uuid4().hex[:12].upper()}",
            status="SUCCESS",
            raw={"sandbox": True},
        )


def mock_webhook_signature(body: bytes) -> str:
    """Test/dev helper to sign mock webhook payloads."""
    return hmac.new(_mock_secret().encode(), body, hashlib.sha256).hexdigest()


_PROVIDER_REGISTRY: dict[str, type] = {
    MockProvider.code: MockProvider,
}


def register_provider(cls: type) -> None:
    _PROVIDER_REGISTRY[cls.code] = cls


def get_provider(code: str) -> PaymentProviderInterface:
    try:
        return _PROVIDER_REGISTRY[code]()
    except KeyError as exc:
        raise ProviderError(f"Provider '{code}' is not implemented.") from exc
