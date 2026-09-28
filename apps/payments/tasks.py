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
    stale = Payment.objects.filter(
        status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
        expires_at__lt=timezone.now(),
    )
    count = 0
    for payment in stale.select_for_update():
        PaymentTransaction.objects.create(
            payment=payment, event_type="RECONCILE_EXPIRED",
            from_status=payment.status, to_status=Payment.Status.EXPIRED,
        )
        payment.status = Payment.Status.EXPIRED
        payment.save(update_fields=["status", "updated_at"])
        count += 1
    return count
