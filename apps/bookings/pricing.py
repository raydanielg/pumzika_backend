"""Pricing engine — the ONLY place booking totals are computed.

Never trust totals from the frontend: clients submit property + dates +
promo code, this engine returns the authoritative Decimal breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.admin_panel import services as settings_service
from apps.availability.services import nightly_prices
from apps.common.utils import money, nights_between, percent_of


@dataclass
class PriceBreakdown:
    currency: str
    nights: int
    nightly_subtotal: Decimal
    cleaning_fee: Decimal
    service_fee: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    commission_rate: Decimal
    commission_amount: Decimal
    host_payout_amount: Decimal
    nightly_detail: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "nights": self.nights,
            "nightly_subtotal": str(self.nightly_subtotal),
            "cleaning_fee": str(self.cleaning_fee),
            "service_fee": str(self.service_fee),
            "tax": str(self.tax),
            "discount": str(self.discount),
            "total": str(self.total),
            "commission_rate": str(self.commission_rate),
            "commission_amount": str(self.commission_amount),
            "host_payout_amount": str(self.host_payout_amount),
            "nightly_detail": self.nightly_detail,
        }


def compute_quote(prop, check_in: date, check_out: date,
                  discount: Decimal = Decimal("0.00"), unit=None) -> PriceBreakdown:
    """Authoritative quote for a stay. All inputs Decimal; no floats."""
    prices = nightly_prices(prop, check_in, check_out, unit=unit)
    nights = nights_between(check_in, check_out)

    nightly_subtotal = money(sum(prices.values(), Decimal("0")))
    cleaning_fee = money(prop.cleaning_fee or 0)

    taxable_base = nightly_subtotal + cleaning_fee
    service_fee = percent_of(taxable_base, settings_service.service_fee_percent())
    tax = percent_of(
        taxable_base + service_fee, settings_service.resolve_tax_percent(prop)
    )
    discount = money(min(discount, taxable_base + service_fee + tax))

    total = money(taxable_base + service_fee + tax - discount)

    commission_rate = settings_service.resolve_commission_percent(prop)
    commission_amount = percent_of(nightly_subtotal + cleaning_fee, commission_rate)
    host_payout_amount = money(nightly_subtotal + cleaning_fee - commission_amount)

    detail = [{"date": str(d), "price": str(money(p))} for d, p in prices.items()]

    return PriceBreakdown(
        currency=prop.currency,
        nights=nights,
        nightly_subtotal=nightly_subtotal,
        cleaning_fee=cleaning_fee,
        service_fee=service_fee,
        tax=tax,
        discount=discount,
        total=total,
        commission_rate=commission_rate,
        commission_amount=commission_amount,
        host_payout_amount=host_payout_amount,
        nightly_detail=detail,
    )
