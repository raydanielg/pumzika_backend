"""Audit logging + configuration services used across the platform."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from .models import CommissionRule, PlatformSetting, TaxRule, AuditLog

logger = logging.getLogger("pumzika.audit")

_SENSITIVE_KEYS = {"password", "token", "secret", "code", "authorization"}


def _safe_metadata(metadata: dict | None) -> dict:
    """Strip anything that looks like a credential before it hits the log."""
    if not metadata:
        return {}
    return {
        k: ("***" if any(s in k.lower() for s in _SENSITIVE_KEYS) else v)
        for k, v in metadata.items()
    }


def audit(actor, action: str, target=None, request=None,
          before: Any = None, after: Any = None, metadata: dict | None = None) -> None:
    """Record an auditable action. Never raises — logging must not break flows."""
    try:
        AuditLog.objects.create(
            actor=actor if getattr(actor, "is_authenticated", True) else None,
            action=action,
            target_type=target.__class__.__name__ if target is not None else "",
            target_id=str(target.pk) if target is not None else "",
            ip_address=_client_ip(request) if request else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
            before=before,
            after=after,
            metadata=_safe_metadata(metadata),
        )
    except Exception:
        logger.exception("Failed to write audit log", extra={"action": action})


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# Pricing configuration
# ---------------------------------------------------------------------------

def service_fee_percent() -> Decimal:
    return PlatformSetting.get_decimal("SERVICE_FEE_PERCENT", "12")


def default_commission_percent() -> Decimal:
    return PlatformSetting.get_decimal("DEFAULT_COMMISSION_PERCENT", "15")


def min_booking_amount() -> Decimal:
    return PlatformSetting.get_decimal("MIN_BOOKING_AMOUNT", "0")


def max_booking_amount() -> Decimal:
    return PlatformSetting.get_decimal("MAX_BOOKING_AMOUNT", "100000000")


def resolve_commission_percent(prop) -> Decimal:
    """Host-specific > property type > country > global default."""
    host_rule = CommissionRule.objects.filter(
        scope=CommissionRule.Scope.HOST, host=prop.host, is_active=True
    ).first()
    if host_rule:
        return host_rule.percent

    type_rule = CommissionRule.objects.filter(
        scope=CommissionRule.Scope.PROPERTY_TYPE,
        property_type=prop.property_type, is_active=True,
    ).first()
    if type_rule:
        return type_rule.percent

    country_rule = CommissionRule.objects.filter(
        scope=CommissionRule.Scope.COUNTRY, country=prop.country, is_active=True
    ).first()
    if country_rule:
        return country_rule.percent

    global_rule = CommissionRule.objects.filter(
        scope=CommissionRule.Scope.GLOBAL, is_active=True
    ).first()
    if global_rule:
        return global_rule.percent
    return default_commission_percent()


def resolve_tax_percent(prop) -> Decimal:
    country_rule = TaxRule.objects.filter(
        country=prop.country, is_active=True
    ).first()
    if country_rule:
        return country_rule.percent
    global_rule = TaxRule.objects.filter(country__isnull=True, is_active=True).first()
    return global_rule.percent if global_rule else Decimal("0")
