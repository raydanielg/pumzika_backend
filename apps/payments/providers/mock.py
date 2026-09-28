"""Sandbox provider for development/tests — no real money moves.

Webhooks are HMAC-signed exactly like real providers so the webhook pipeline
is exercised end-to-end.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from django.conf import settings

from .base import (
    InitiationResult,
    ProviderError,
    WebhookData,
)


def _mock_secret() -> str:
    return getattr(settings, "MOCK_PAYMENT_SECRET", "mock-webhook-secret")


class MockProvider:
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

    def check_status(self, payment) -> str | None:
        # The sandbox has no remote state — always agree with the local copy.
        return payment.status


def mock_webhook_signature(body: bytes) -> str:
    """Test/dev helper to sign mock webhook payloads."""
    return hmac.new(_mock_secret().encode(), body, hashlib.sha256).hexdigest()
