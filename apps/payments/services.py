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
    """Append an immutable ledger row — this does NOT change payment.status."""
    PaymentTransaction.objects.create(
        payment=payment, event_type=event_type,
        from_status=payment.status, to_status=to_status,
        provider_reference=provider_reference or "", raw=raw or {},
    )


def _transition_payment(payment: Payment, to_status: str, event_type: str,
                        provider_reference: str = "", raw: dict | None = None,
                        failure_reason: str = "") -> None:
    """State-machine-guarded payment status change + ledger entry.

    Raises INVALID_PAYMENT_TRANSITION on impossible moves (e.g. SUCCESS→PENDING)
    instead of silently corrupting financial state.
    """
    if payment.status != to_status and not payment.can_transition_to(to_status):
        raise BusinessError(
            f"Cannot move payment from {payment.status} to {to_status}.",
            code="INVALID_PAYMENT_TRANSITION",
        )
    _record_transaction(payment, event_type, to_status,
                        provider_reference, raw)
    payment.status = to_status
    now = timezone.now()
    if to_status == Payment.Status.SUCCESS and payment.paid_at is None:
        payment.paid_at = now
    if to_status == Payment.Status.FAILED:
        payment.failed_at = now
        if failure_reason:
            payment.failure_reason = failure_reason
    if to_status == Payment.Status.EXPIRED:
        payment.expired_at = now
    payment.save()


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

    # booking_id accepts either the UUID pk or the public PZA- reference.
    booking_qs = Booking.objects.select_for_update().select_related(
        "price", "property", "guest"
    )
    booking = booking_qs.filter(pk=booking_id).first()
    if booking is None:
        booking = booking_qs.filter(reference=str(booking_id)).first()
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

    # Idempotent replay — the same key may only ever name the same request.
    existing = Payment.objects.filter(
        idempotency_key=idempotency_key, booking__guest=user
    ).first()
    if existing is not None:
        if existing.booking_id != booking.id:
            raise BusinessError(
                "Idempotency key was used for a different payment.",
                code="IDEMPOTENCY_CONFLICT",
            )
        return existing

    from apps.notifications.tasks import notify_payment_pending

    payment = Payment.objects.create(
        booking=booking,
        user=user,
        provider=provider_row,
        amount=booking.price.total,
        currency=booking.currency,
        payment_method=(method_details or {}).get("method", ""),
        idempotency_key=idempotency_key,
        reference=generate_reference("PZP"),
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
        _transition_payment(payment, Payment.Status.FAILED,
                            "INITIATION_FAILED", failure_reason=str(exc))
        raise BusinessError("Payment initiation failed.", code="PAYMENT_INIT_FAILED")

    PaymentAttempt.objects.create(
        payment=payment, status="PENDING",
        request_payload={"method_details": method_details or {}},
        response_payload=result.raw or {},
    )
    _transition_payment(payment, Payment.Status.PENDING, "AWAITING_CONFIRMATION",
                        result.provider_reference, result.raw)
    payment.external_reference = result.provider_reference
    payment.metadata = {"checkout_url": result.checkout_url}
    payment.save(update_fields=["external_reference", "metadata", "updated_at"])

    booking_services.mark_awaiting_payment(booking)
    booking_services._event(payment.booking, "PAYMENT_STARTED",
                            actor=booking.guest,
                            data={"reference": payment.reference,
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

    if data.event_type == "payment.success" and payment.status == Payment.Status.SUCCESS:
        # Provider resent a success under a new event id — no side effects.
        return
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

        _transition_payment(payment, Payment.Status.SUCCESS, "WEBHOOK_SUCCESS",
                            data.external_reference, data.payload)
        update = []
        if data.external_reference:
            payment.external_reference = data.external_reference
            update.append("external_reference")
        remote_status = (data.payload.get("data") or [{}])[0].get(
            "payment_status"
        ) or (data.payload.get("data") or {}).get("payment_status")
        if remote_status:
            payment.provider_status = str(remote_status).upper()
            update.append("provider_status")
        if update:
            update.append("updated_at")
            payment.save(update_fields=update)
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

    elif data.event_type == "payment.pending":
        _transition_payment(payment, Payment.Status.PROCESSING,
                            "WEBHOOK_PENDING", data.external_reference,
                            data.payload)
        payment.provider_status = "PENDING"
        payment.save(update_fields=["provider_status", "updated_at"])

    elif data.event_type in ("payment.failed", "payment.cancelled", "payment.expired"):
        status_map = {
            "payment.failed": Payment.Status.FAILED,
            "payment.cancelled": Payment.Status.CANCELLED,
            "payment.expired": Payment.Status.EXPIRED,
        }
        new_status = status_map[data.event_type]
        _transition_payment(
            payment, new_status, f"WEBHOOK_{data.event_type.upper()}",
            data.external_reference, data.payload,
            failure_reason=(data.payload.get("data") or {}).get("reason", ""),
        )
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
        reference=generate_reference("RFD"),
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
    booking_services._event(
        booking, "REFUND_REQUESTED", actor=requested_by,
        data={"amount": str(amount), "reason": reason},
    )
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
    booking_services._event(
        refund.booking, "REFUND_COMPLETED",
        data={"amount": str(refund.amount)},
    )


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
        _transition_payment(payment, new_status, "REFUND_SYNC")

    booking = payment.booking
    if new_status == Payment.Status.REFUNDED and booking.can_transition_to(
        Booking.Status.REFUNDED
    ):
        from apps.bookings.services import _transition as booking_transition

        booking_transition(booking, Booking.Status.REFUNDED)
        booking.save(update_fields=["status", "updated_at"])
