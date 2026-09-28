"""Selcom payment provider — checkout orders + USSD wallet push.

Internal method names (MOBILE_MONEY, CARD, ...) map to Selcom identifiers
here and only here — nothing else in the codebase references them.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings

from ..base import (
    InitiationResult,
    PaymentFailedByProvider,
    VerificationFailed,
    WebhookData,
)
from .client import SelcomClient

# Internal method -> Selcom payment-methods / utilitycode identifiers.
METHOD_MAP = {
    "MOBILE_MONEY": {"payment_methods": "AM", "utilitycode": "walletpush"},
    "CARD": {"payment_methods": "CC", "utilitycode": None},
    "BANK": {"payment_methods": "BT", "utilitycode": None},
    "OTHER": {"payment_methods": "ALL", "utilitycode": None},
}

# Selcom order-status payment_status -> internal Payment.Status
STATUS_MAP = {
    "PENDING": "PENDING",
    "COMPLETED": "SUCCESS",
    "SUCCESS": "SUCCESS",
    "USERCANCELLED": "CANCELLED",
    "CANCELLED": "CANCELLED",
    "FAILED": "FAILED",
    "REJECTED": "FAILED",
}

SIGNED_ORDER_FIELDS = [
    "vendor", "order_id", "buyer_email", "buyer_name", "buyer_phone",
    "amount", "currency", "payment_methods", "redirect_url", "cancel_url",
    "webhook", "billing.firstname", "billing.lastname", "billing.country",
    "billing.phone", "order_items",
]

SIGNED_PUSH_FIELDS = ["order_id", "transid", "msisdn", "utilitycode"]


class SelcomProvider:
    """Selcom Checkout API integration via the shared provider interface."""

    code = "SELCOM"

    def __init__(self, client: SelcomClient | None = None):
        self.client = client or SelcomClient()

    # -- initiation -------------------------------------------------------

    def initiate(self, payment, method_details: dict) -> InitiationResult:
        method = (method_details.get("method") or "MOBILE_MONEY").upper()
        mapped = METHOD_MAP.get(method, METHOD_MAP["OTHER"])
        guest = payment.booking.guest

        order = {
            "vendor": self.client.vendor_id,
            "order_id": payment.reference,          # our PZP- ref is order_id
            "buyer_email": guest.email,
            "buyer_name": guest.full_name,
            "buyer_phone": guest.phone or "",
            "amount": str(int(payment.amount)),
            "currency": payment.currency,
            "payment_methods": mapped["payment_methods"],
            "redirect_url": f"{settings.FRONTEND_BASE_URL}/payments/success",
            "cancel_url": f"{settings.FRONTEND_BASE_URL}/payments/cancel",
            "webhook": self.client.webhook_url,
            "billing.firstname": guest.first_name,
            "billing.lastname": guest.last_name,
            "billing.country": "TZ",
            "billing.phone": guest.phone or "",
            "order_items": "1",
        }
        resp = self.client.request(
            "POST", "/v1/checkout/create-order", order, SIGNED_ORDER_FIELDS
        )
        result = resp.get("data", [{}])[0]
        checkout_url = result.get("payment_gateway_url") or result.get("payment_url")

        # Mobile money: immediately trigger a USSD push so the customer pays
        # from their wallet without visiting the checkout page.
        if method == "MOBILE_MONEY" and method_details.get("msisdn"):
            self.client.request(
                "POST", "/v1/checkout/wallet-payment",
                {
                    "order_id": payment.reference,
                    "transid": payment.reference,
                    "msisdn": method_details["msisdn"],
                    "utilitycode": mapped["utilitycode"],
                },
                SIGNED_PUSH_FIELDS,
            )

        return InitiationResult(
            provider_reference=str(result.get("reference", payment.reference)),
            status="PENDING",
            checkout_url=checkout_url,
            raw={"order": resp.get("result"), "transid": result.get("transid")},
        )

    # -- webhooks / callbacks ----------------------------------------------

    def verify_webhook(self, body: bytes, headers: dict) -> WebhookData:
        """Selcom callbacks carry order state — we re-verify against the
        order-status endpoint rather than trusting the payload alone."""
        import json

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise VerificationFailed("Invalid webhook payload") from exc

        order = (data.get("data") or [{}])[0]
        order_id = order.get("order_id") or data.get("order_id")
        if not order_id:
            raise VerificationFailed("Webhook missing order reference")

        remote = self._remote_status(order_id)
        event_type = {
            "SUCCESS": "payment.success",
            "FAILED": "payment.failed",
            "CANCELLED": "payment.cancelled",
            "PENDING": "payment.pending",
        }.get(remote)
        if event_type is None:
            raise VerificationFailed(f"Unverifiable provider status: {remote}")

        return WebhookData(
            external_event_id=f"{order_id}:{remote}",
            event_type=event_type,
            reference=order_id,
            external_reference=order.get("transid") or data.get("transid"),
            payload=data,
        )

    # -- status / reconciliation -------------------------------------------

    def _remote_status(self, order_id: str) -> str | None:
        resp = self.client.request(
            "GET", f"/v1/checkout/order-status/{order_id}",
            {"order_id": order_id}, ["order_id"],
        )
        record = (resp.get("data") or [{}])[0]
        return STATUS_MAP.get(record.get("payment_status", "").upper())

    def check_status(self, payment) -> str | None:
        return self._remote_status(payment.reference)

    # -- refunds ------------------------------------------------------------

    def refund(self, refund) -> InitiationResult:
        """Selcom has no public checkout refund endpoint — refunds are
        processed through Selcom merchant support / settlement and tracked
        as PROCESSING until staff confirm completion."""
        return InitiationResult(
            provider_reference=f"SELCOM-MANUAL-{uuid.uuid4().hex[:8].upper()}",
            status="PROCESSING",
            raw={"note": "manual refund via Selcom merchant channel"},
        )
