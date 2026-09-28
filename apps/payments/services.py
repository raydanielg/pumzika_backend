"""Payment orchestration — initiation, webhooks, refunds.

Guarantees:
- Idempotent initiation via client-supplied ``idempotency_key``.
- Webhook dedupe via unique (provider, external_event_id).
- All state transitions recorded in append-only transaction tables.
- Booking confirmation only ever happens inside the payment layer.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.admin_panel.services import audit
from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError
from apps.common.utils import generate_reference
from apps.bookings import services as booking_services
from apps.bookings.models import Booking

from .models import (
    Payment,
    PaymentAttempt,
    PaymentProvider,
    PaymentTransaction,
    Refund,
    RefundTransaction,
    WebhookEvent,
)
from .providers import ProviderError, get_provider

logger = logging.getLogger("pumzika.payments")


def active_providers():
    return PaymentProvider.objects.filter(is_active=True)


def _record_transaction(payment: Payment, event_type: str, to_status: str,
                        provider_reference: str = "", raw: dict | None = None):
    PaymentTransaction.objects.create(
        payment=payment, event_type=event_type,
        from_status=payment.status, to_status=to_status,
        provider_reference=provider_reference or "", raw=raw or {},
    )


@transaction.atomic
def initiate_payment(user, *, booking_id, provider_code: str,
                     idempotency_key: str, method_details: dict | None = None) -> Payment:
    """Start (or resume) payment for a booking.

    Idempotent: the same idempotency_key always returns the same Payment.
    """
    if not idempotency_key:
        # No client key — derive a unique one so the column stays non-null.
        import uuid

        idempotency_key = f"auto-{uuid.uuid4().hex[:24]}"

    booking = (
        Booking.objects.select_for_update()
        .select_related("price", "property")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    if booking.guest_id != user.id:
        raise PermissionDeniedError("You can only pay for your own booking.")
    if booking.status not in (Booking.Status.PENDING, Booking.Status.AWAITING_PAYMENT):
        raise BusinessError(
            f"Booking is {booking.status} and cannot be paid.",
            code="BOOKING_NOT_PAYABLE",
        )
    if booking.expires_at and booking.expires_at < timezone.now():
        booking_services.expire_booking(booking)
        raise BusinessError("Booking has expired.", code="BOOKING_EXPIRED")

    provider_row = PaymentProvider.objects.filter(code=provider_code, is_active=True).first()
    if provider_row is None:
        raise BusinessError("Payment provider is not available.",
                            code="PROVIDER_UNAVAILABLE")
    if (provider_row.supported_currencies
            and booking.currency not in provider_row.supported_currencies):
        raise BusinessError("Provider does not support this currency.",
                            code="CURRENCY_NOT_SUPPORTED")

    # Idempotent replay — return the existing payment untouched.
    existing = Payment.objects.filter(
        idempotency_key=idempotency_key, booking__guest=user
    ).first()
    if existing is not None:
        return existing

    from apps.notifications.tasks import notify_payment_pending

    payment = Payment.objects.create(
        booking=booking,
        provider=provider_row,
        amount=booking.price.total,
        currency=booking.currency,
        idempotency_key=idempotency_key,
        reference=generate_reference("PAY"),
        expires_at=booking.expires_at,
    )
    _record_transaction(payment, "INITIATED", Payment.Status.PENDING)

    provider = get_provider(provider_code)
    try:
        result = provider.initiate(payment, method_details or {})
    except ProviderError as exc:
        PaymentAttempt.objects.create(
            payment=payment, status="FAILED", error=str(exc),
            request_payload={"method_details": method_details or {}},
        )
        _record_transaction(payment, "INITIATION_FAILED", Payment.Status.FAILED)
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise BusinessError("Payment initiation failed.", code="PAYMENT_INIT_FAILED")

    PaymentAttempt.objects.create(
        payment=payment, status="PENDING",
        request_payload={"method_details": method_details or {}},
        response_payload=result.raw or {},
    )
    payment.external_reference = result.provider_reference
    payment.metadata = {"checkout_url": result.checkout_url}
    payment.save(update_fields=["external_reference", "metadata", "updated_at"])

    booking_services.mark_awaiting_payment(booking)
    booking_services._event(payment.booking, "PAYMENT_STARTED",
                            actor=guest, data={"reference": payment.reference,
                                               "amount": str(payment.amount)})
    transaction.on_commit(
        lambda: notify_payment_pending.delay(str(payment.id))
    )
    return payment


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def _payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def process_webhook(provider_code: str, body: bytes, headers: dict) -> WebhookEvent:
    """Validate, dedupe and dispatch a provider webhook.

    Dedupe happens BEFORE processing: a repeated event id is acknowledged
    without re-running side effects.
    """
    provider = get_provider(provider_code)
    try:
        data = provider.verify_webhook(body, headers)
    except ProviderError as exc:
        WebhookEvent.objects.create(
            provider=provider_code, event_type="INVALID",
            external_event_id=f"invalid-{_payload_hash(body)[:24]}",
            payload_hash=_payload_hash(body), payload={},
            status=WebhookEvent.Status.FAILED, error=str(exc),
            processed_at=timezone.now(),
        )
        raise BusinessError("Invalid webhook.", code="INVALID_WEBHOOK",
                            http_status=400)

    event, created = WebhookEvent.objects.get_or_create(
        provider=provider_code,
        external_event_id=data.external_event_id,
        defaults={
            "event_type": data.event_type,
            "payload_hash": _payload_hash(body),
            "payload": data.payload or {},
            "raw_body": body,
            "raw_signature": headers.get("x-webhook-signature", ""),
        },
    )
    if not created:
        if event.status == WebhookEvent.Status.PROCESSED:
            return event  # idempotent — already handled
        event.retry_count += 1
        event.save(update_fields=["retry_count", "updated_at"])

    try:
        with transaction.atomic():
            _dispatch_webhook(event, data)
            event.status = WebhookEvent.Status.PROCESSED
    except Exception as exc:  # keep the event for retry/inspection
        event.status = WebhookEvent.Status.FAILED
        event.error = str(exc)
        logger.exception("Webhook processing failed",
                         extra={"provider": provider_code,
                                "event_id": data.external_event_id})
    finally:
        event.processed_at = timezone.now()
        event.save()
    return event


def _dispatch_webhook(event: WebhookEvent, data) -> None:
    payment = _find_payment(data)
    if payment is None:
        event.status = WebhookEvent.Status.IGNORED
        event.error = "No payment matched reference"
        return

    payment = Payment.objects.select_for_update().get(pk=payment.pk)

    if data.event_type == "payment.success":
        # Verify the provider-confirmed amount/currency against our record —
        # a mismatched webhook is a reconciliation incident, not a confirm.
        payload_amount = (data.payload.get("data") or {}).get("amount")
        payload_currency = (data.payload.get("data") or {}).get("currency")
        if payload_amount is not None and (
            Decimal(str(payload_amount)) != payment.amount
        ):
            raise BusinessError("Webhook amount mismatch.",
                                code="PAYMENT_AMOUNT_MISMATCH")
        if payload_currency and payload_currency.upper() != payment.currency:
            raise BusinessError("Webhook currency mismatch.",
                                code="PAYMENT_CURRENCY_MISMATCH")

        _record_transaction(payment, "WEBHOOK_SUCCESS", Payment.Status.SUCCESS,
                            data.external_reference, data.payload)
        payment.status = Payment.Status.SUCCESS
        payment.paid_at = timezone.now()
        if data.external_reference:
            payment.external_reference = data.external_reference
        payment.save(update_fields=["status", "paid_at", "external_reference",
                                    "updated_at"])
        booking_services.confirm_booking(payment.booking,
                                         note="Payment confirmed via webhook")
        booking_services._event(
            payment.booking, "PAYMENT_SUCCESS",
            data={"reference": payment.reference,
                  "external": payment.external_reference},
        )
        transaction.on_commit(
            lambda: _notify_payment_success(payment.id)
        )

    elif data.event_type in ("payment.failed", "payment.cancelled", "payment.expired"):
        status_map = {
            "payment.failed": Payment.Status.FAILED,
            "payment.cancelled": Payment.Status.CANCELLED,
            "payment.expired": Payment.Status.EXPIRED,
        }
        new_status = status_map[data.event_type]
        _record_transaction(payment, f"WEBHOOK_{data.event_type.upper()}",
                            new_status, data.external_reference, data.payload)
        payment.status = new_status
        payment.save(update_fields=["status", "updated_at"])
        # The booking stays payable — a failed payment does NOT kill it.
        # The booking's own expiry window (expire_unpaid_bookings) is the
        # single authority on when held dates are released.
        booking_services._event(
            payment.booking, "PAYMENT_FAILED",
            data={"reference": payment.reference, "provider_status": new_status},
        )
        transaction.on_commit(
            lambda: _notify_payment_failed(payment.id)
        )

    elif data.event_type == "refund.success":
        _handle_refund_success(data)

    else:
        event.status = WebhookEvent.Status.IGNORED


def _notify_refund_initiated(refund_id) -> None:
    from apps.notifications.tasks import notify_refund_initiated

    notify_refund_initiated.delay(str(refund_id))


def _notify_payment_success(payment_id) -> None:
    from apps.notifications.tasks import notify_payment_success

    notify_payment_success.delay(str(payment_id))


def _notify_payment_failed(payment_id) -> None:
    from apps.notifications.tasks import notify_payment_failed

    notify_payment_failed.delay(str(payment_id))


def _find_payment(data) -> Payment | None:
    qs = Payment.objects.all()
    if data.reference:
        found = qs.filter(reference=data.reference).first()
        if found:
            return found
    if data.external_reference:
        return qs.filter(external_reference=data.external_reference).first()
    return None


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------

@transaction.atomic
def initiate_refund(*, booking: Booking, amount: Decimal, reason: str,
                    requested_by=None, idempotency_key: str | None = None
                    ) -> Refund | None:
    """Create a refund against the booking's successful payment."""
    if idempotency_key:
        existing = Refund.objects.filter(
            idempotency_key=idempotency_key, booking=booking
        ).first()
        if existing is not None:
            return existing
    payment = (
        Payment.objects.select_for_update()
        .filter(booking=booking, status__in=[Payment.Status.SUCCESS,
                                             Payment.Status.PARTIALLY_REFUNDED])
        .order_by("-created_at")
        .first()
    )
    if payment is None or amount <= 0:
        return None
    if amount > payment.refundable_amount:
        raise BusinessError("Refund exceeds the refundable amount.",
                            code="REFUND_TOO_LARGE")

    refund = Refund.objects.create(
        payment=payment, booking=booking, amount=amount,
        currency=payment.currency, reason=reason, requested_by=requested_by,
        idempotency_key=idempotency_key or None,
    )
    transaction.on_commit(
        lambda: _notify_refund_initiated(refund.id)
    )
    provider = get_provider(payment.provider.code)
    try:
        result = provider.refund(refund)
    except ProviderError as exc:
        refund.status = Refund.Status.FAILED
        refund.save(update_fields=["status", "updated_at"])
        raise BusinessError(f"Refund failed: {exc}", code="REFUND_FAILED")

    refund.external_reference = result.provider_reference
    new_status = (Refund.Status.SUCCESS if result.status == "SUCCESS"
                  else Refund.Status.PROCESSING)
    _transition_refund(refund, new_status, result.provider_reference, result.raw)
    _sync_payment_refund_state(payment)
    return refund


def _transition_refund(refund: Refund, to_status: str, provider_reference="",
                       raw: dict | None = None) -> None:
    RefundTransaction.objects.create(
        refund=refund, from_status=refund.status, to_status=to_status,
        provider_reference=provider_reference, raw=raw or {},
    )
    refund.status = to_status
    if to_status == Refund.Status.SUCCESS:
        refund.processed_at = timezone.now()
    refund.save()


def _handle_refund_success(data) -> None:
    refund = Refund.objects.select_for_update().filter(
        external_reference=data.external_reference
    ).first()
    if refund is None:
        return
    if refund.status == Refund.Status.SUCCESS:
        return  # idempotent
    _transition_refund(refund, Refund.Status.SUCCESS, data.external_reference,
                       data.payload)
    _sync_payment_refund_state(refund.payment)


@transaction.atomic
def _sync_payment_refund_state(payment: Payment) -> None:
    from django.db.models import Sum

    total_refunded = payment.refunds.filter(
        status=Refund.Status.SUCCESS
    ).aggregate(Sum("amount"))["amount__sum"] or Decimal("0")

    if total_refunded >= payment.amount:
        new_status = Payment.Status.REFUNDED
    elif total_refunded > 0:
        new_status = Payment.Status.PARTIALLY_REFUNDED
    else:
        return
    if payment.status != new_status:
        _record_transaction(payment, "REFUND_SYNC", new_status)
        payment.status = new_status
        payment.save(update_fields=["status", "updated_at"])

    booking = payment.booking
    if new_status == Payment.Status.REFUNDED and booking.can_transition_to(
        Booking.Status.REFUNDED
    ):
        from apps.bookings.services import _transition as booking_transition

        booking_transition(booking, Booking.Status.REFUNDED)
        booking.save(update_fields=["status", "updated_at"])
