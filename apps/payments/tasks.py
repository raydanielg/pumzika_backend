"""Periodic payment maintenance — all safe to run repeatedly."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import Payment, PaymentTransaction

logger = logging.getLogger("pumzika.payments")


@shared_task
def reconcile_pending_payments() -> int:
    """Expire stale pending/processing payments whose window has elapsed.

    Idempotent — each payment is moved to EXPIRED exactly once and the
    transition is written to the append-only transaction log.
    """
    from apps.bookings import services as booking_services

    stale = Payment.objects.filter(
        status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
        expires_at__lt=timezone.now(),
    )
    count = 0
    for payment in stale.select_for_update().select_related("booking"):
        PaymentTransaction.objects.create(
            payment=payment, event_type="RECONCILE_EXPIRED",
            from_status=payment.status, to_status=Payment.Status.EXPIRED,
        )
        payment.status = Payment.Status.EXPIRED
        payment.expired_at = timezone.now()
        payment.save(update_fields=["status", "expired_at", "updated_at"])
        # Expiring the payment also expires the underlying unpaid booking —
        # expire_booking is itself idempotent.
        try:
            booking_services.expire_booking(payment.booking)
        except Exception:
            logger.exception("Failed to expire booking %s", payment.booking_id)
        count += 1
    return count


@shared_task
def reconcile_provider_status() -> int:
    """Compare open payments against provider-side state (where supported).

    Flags payments stuck in PENDING/PROCESSING long past creation so finance
    can review — providers without check_status are skipped.
    """
    from .providers import get_provider, ProviderError

    checked = 0
    open_payments = Payment.objects.filter(
        status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
    ).select_related("provider")
    for payment in open_payments.iterator():
        try:
            provider = get_provider(payment.provider.code)
            status = provider.check_status(payment)
        except (ProviderError, AttributeError, NotImplementedError):
            continue
        if status and status != payment.status:
            PaymentTransaction.objects.create(
                payment=payment, event_type="RECONCILE_DRIFT",
                from_status=payment.status, to_status=payment.status,
                raw={"provider_status": status},
            )
        checked += 1
    return checked
