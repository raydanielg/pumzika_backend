"""Shared utilities — money, reference codes, date helpers."""
from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value) -> Decimal:
    """Normalize a value to a 2dp Decimal. NEVER pass floats for money."""
    if isinstance(value, float):
        value = str(value)
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    return money(amount * Decimal(percent) / Decimal("100"))


def generate_reference(prefix: str = "PKA", length: int = 10) -> str:
    """Human-friendly unique reference e.g. BKG-9F3K2Q7XA1."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    suffix = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}-{suffix}"


def daterange(start: date, end: date):
    """Iterate [start, end) — nights of a stay."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def nights_between(check_in: date, check_out: date) -> int:
    return (check_out - check_in).days
