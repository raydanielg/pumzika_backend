"""Cancellation engine — computes refund entitlement from policy rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from apps.common.utils import money, percent_of

from .models import Booking, CancellationPolicy


@dataclass
class CancellationResult:
    allowed: bool
    reason: str
    refund_amount: Decimal
    host_amount: Decimal
    refund_service_fee: bool


def _hours_until_check_in(booking: Booking) -> float:
    check_in_dt = datetime.combine(booking.check_in, booking.property.check_in_time)
    check_in_dt = timezone.make_aware(check_in_dt)
    return (check_in_dt - timezone.now()).total_seconds() / 3600


def _matching_rule(policy: CancellationPolicy, hours_before: float):
    """Rules are ordered most-generous first; first satisfied rule wins."""
    rules = list(policy.rules.order_by("-hours_before_check_in"))
    for rule in rules:
        if hours_before >= rule.hours_before_check_in:
            return rule
    return rules[-1] if rules else None  # least refund tier


def compute_cancellation(booking: Booking) -> CancellationResult:
    """What would happen if the booking were cancelled right now."""
    if booking.status in (Booking.Status.CANCELLED, Booking.Status.REFUNDED,
                          Booking.Status.EXPIRED):
        return CancellationResult(False, "Booking already ended.",
                                  Decimal("0"), Decimal("0"), False)
    if booking.status in (Booking.Status.PENDING, Booking.Status.AWAITING_PAYMENT):
        # No money taken yet — full release.
        total = booking.price.total if hasattr(booking, "price") else Decimal("0")
        return CancellationResult(True, "Unpaid booking released.", money(total),
                                  Decimal("0"), True)

    policy = booking.cancellation_policy
    price = booking.price
    if policy is None:
        return CancellationResult(True, "No policy — full refund.", money(price.total),
                                  Decimal("0"), True)

    hours = _hours_until_check_in(booking)
    rule = _matching_rule(policy, hours)
    if rule is None:
        return CancellationResult(True, "No matching rule — full refund.",
                                  money(price.total), Decimal("0"), True)

    refundable_base = price.nightly_subtotal + price.cleaning_fee
    if rule.refund_service_fee:
        refundable_base += price.service_fee
    refund_amount = money(percent_of(refundable_base, rule.guest_refund_percent))
    host_amount = money(refundable_base - refund_amount) if refund_amount < refundable_base else Decimal("0")

    reason = (
        f"{policy.name}: cancel ≥{rule.hours_before_check_in}h before check-in "
        f"-> {rule.guest_refund_percent}% refund"
    )
    return CancellationResult(True, reason, refund_amount, host_amount,
                              rule.refund_service_fee)


def policy_snapshot(policy: CancellationPolicy | None) -> dict:
    if policy is None:
        return {}
    return {
        "name": policy.name,
        "code": policy.code,
        "rules": [
            {
                "hours_before_check_in": r.hours_before_check_in,
                "guest_refund_percent": str(r.guest_refund_percent),
                "refund_service_fee": r.refund_service_fee,
            }
            for r in policy.rules.order_by("-hours_before_check_in")
        ],
    }
