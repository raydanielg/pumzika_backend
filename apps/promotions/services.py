"""Promotion validation + application — server-side only."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.availability.services import nightly_prices
from apps.common.exceptions import BusinessError
from apps.common.utils import money, percent_of

from .models import Promotion, PromotionUsage


def validate_for_booking(code: str, prop, user, check_in: date,
                         check_out: date) -> tuple[Promotion, Decimal]:
    """Return (promotion, discount) or raise. Called inside booking creation."""
    promo = Promotion.objects.filter(code__iexact=code, is_active=True).first()
    if promo is None:
        raise BusinessError("Invalid promo code.", code="INVALID_PROMO")

    now = timezone.now()
    if now < promo.valid_from or now > promo.valid_until:
        raise BusinessError("Promo code is not valid at this time.",
                            code="PROMO_EXPIRED")
    if promo.max_uses is not None and promo.times_used >= promo.max_uses:
        raise BusinessError("Promo code usage limit reached.",
                            code="PROMO_EXHAUSTED")
    if promo.country_id and promo.country_id != prop.country_id:
        raise BusinessError("Promo code is not valid in this country.",
                            code="PROMO_COUNTRY_RESTRICTED")
    if promo.properties.exists() and not promo.properties.filter(pk=prop.pk).exists():
        raise BusinessError("Promo code does not apply to this property.",
                            code="PROMO_PROPERTY_RESTRICTED")
    if user is not None and user.is_authenticated:
        used = PromotionUsage.objects.filter(promotion=promo, user=user).count()
        if used >= promo.per_user_limit:
            raise BusinessError("You have already used this promo code.",
                                code="PROMO_USER_LIMIT")

    # Discount applies to the accommodation base (nightly + cleaning).
    subtotal = sum(nightly_prices(prop, check_in, check_out).values(), Decimal("0"))
    subtotal = money(subtotal + (prop.cleaning_fee or 0))
    if subtotal < promo.min_booking_amount:
        raise BusinessError("Booking does not meet the promo minimum amount.",
                            code="PROMO_MIN_NOT_MET")

    if promo.discount_type == Promotion.DiscountType.PERCENT:
        discount = percent_of(subtotal, promo.value)
        if promo.max_discount is not None:
            discount = min(discount, money(promo.max_discount))
    else:
        if promo.currency and promo.currency != prop.currency:
            raise BusinessError("Promo currency does not match the booking currency.",
                                code="PROMO_CURRENCY_MISMATCH")
        discount = money(promo.value)
    return promo, min(discount, subtotal)


@transaction.atomic
def record_usage(promo: Promotion, user, booking, discount: Decimal | None = None) -> None:
    """Record usage atomically — unique(promotion, booking) blocks double use."""
    amount = discount if discount is not None else booking.price.discount
    PromotionUsage.objects.create(
        promotion=promo, user=user, booking=booking, discount_amount=amount
    )
    Promotion.objects.filter(pk=promo.pk).update(times_used=F("times_used") + 1)
