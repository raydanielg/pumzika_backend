"""Security event recording, login risk control, suspension, incidents.

Weak signals never trigger hard actions alone — they accumulate in cache
counters until a configurable threshold, then produce events/incidents.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.common.utils import generate_reference

from .models import SecurityEvent, SecurityIncident

logger = logging.getLogger("pumzika.security")

# Severity is derived from event type — never left to ad-hoc judgment.
SEVERITY_RULES = {
    SecurityEvent.Type.LOGIN_SUCCESS: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.PASSWORD_CHANGED: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.PASSWORD_RESET: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.EMAIL_VERIFIED: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.PHONE_VERIFIED: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.ACCOUNT_RESTORED: SecurityEvent.Severity.INFO,
    SecurityEvent.Type.ACCOUNT_RESTRICTED: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.PERMISSION_CHANGE: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.LOGIN_FAILED: SecurityEvent.Severity.LOW,
    SecurityEvent.Type.OTP_FAILED: SecurityEvent.Severity.LOW,
    SecurityEvent.Type.TOKEN_REVOKED: SecurityEvent.Severity.LOW,
    SecurityEvent.Type.FILE_UPLOAD_REJECTED: SecurityEvent.Severity.LOW,
    SecurityEvent.Type.SUSPICIOUS_LOGIN: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.PERMISSION_DENIED: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.RATE_LIMIT_TRIGGERED: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.ACCOUNT_SUSPENDED: SecurityEvent.Severity.MEDIUM,
    SecurityEvent.Type.ACCOUNT_LOCKED: SecurityEvent.Severity.HIGH,
    SecurityEvent.Type.WEBHOOK_SIGNATURE_FAILED: SecurityEvent.Severity.HIGH,
    SecurityEvent.Type.PAYMENT_ANOMALY: SecurityEvent.Severity.CRITICAL,
    SecurityEvent.Type.ADMIN_ACTION: SecurityEvent.Severity.MEDIUM,
}

# Configurable thresholds (PlatformSetting name, default).
LOGIN_FAIL_THRESHOLD = ("SEC_LOGIN_FAIL_THRESHOLD", 5)
LOGIN_LOCK_MINUTES = ("SEC_LOGIN_LOCK_MINUTES", 15)
MAX_KNOWN_IPS = 10


def _setting(name: str, default):
    from apps.admin_panel.models import PlatformSetting

    try:
        return type(default)(PlatformSetting.get(name, default))
    except (TypeError, ValueError):
        return default


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record_event(event_type: str, *, user=None, request=None, resource=None,
                 metadata: dict | None = None,
                 severity: str | None = None) -> SecurityEvent:
    """Append a security event. CRITICAL events auto-open an incident."""
    event = SecurityEvent.objects.create(
        event_type=event_type,
        severity=severity or SEVERITY_RULES.get(
            event_type, SecurityEvent.Severity.LOW
        ),
        user=user if getattr(user, "is_authenticated", False) else None,
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300]
                    if request else ""),
        request_id=getattr(request, "request_id", "") or "",
        resource_type=type(resource).__name__ if resource is not None else "",
        resource_id=str(getattr(resource, "pk", "") or "") if resource else "",
        metadata=metadata or {},
    )
    if event.severity == SecurityEvent.Severity.CRITICAL:
        open_incident(
            title=f"{event_type} detected",
            severity=event.severity,
            incident_type=event_type,
            description=(metadata or {}).get("detail", ""),
            affected_service=(metadata or {}).get("service", ""),
            linked_event=event,
        )
    return event


def login_lockout_key(email: str) -> str:
    return f"sec:lockout:{email.lower()}"


def login_failures_key(email: str) -> str:
    return f"sec:loginfail:{email.lower()}"


def is_login_locked(email: str) -> bool:
    return bool(cache.get(login_lockout_key(email)))


def record_login_failure(email: str, request=None) -> int:
    """Count a failed login; lock temporarily once threshold is crossed."""
    threshold = _setting(*LOGIN_FAIL_THRESHOLD)
    lock_minutes = _setting(*LOGIN_LOCK_MINUTES)
    key = login_failures_key(email)
    count = cache.add(key, 0, 60 * 60) or 0
    count = cache.incr(key)
    from apps.accounts.models import User

    user = User.objects.filter(email__iexact=email).first()
    record_event(SecurityEvent.Type.LOGIN_FAILED, user=user, request=request,
                 metadata={"email": email[:3] + "***", "attempt": count})
    if count >= threshold:
        cache.set(login_lockout_key(email), True, 60 * lock_minutes)
        record_event(SecurityEvent.Type.ACCOUNT_LOCKED, user=user,
                     request=request,
                     metadata={"email": email[:3] + "***",
                               "lock_minutes": lock_minutes})
    return count


def record_login_success(user, request=None) -> None:
    """Successful login — log it, and flag a brand-new IP as suspicious."""
    record_event(SecurityEvent.Type.LOGIN_SUCCESS, user=user, request=request)
    ip = _client_ip(request)
    if not ip:
        return
    known = set(user.known_ips or [])
    if known and ip not in known:
        record_event(SecurityEvent.Type.SUSPICIOUS_LOGIN, user=user,
                     request=request, metadata={"new_ip": ip})
        from apps.notifications.tasks import notify_security_alert

        notify_security_alert.delay(str(user.id), "Login from a new device/IP")
    known.add(ip)
    user.known_ips = sorted(known)[-MAX_KNOWN_IPS:]
    user.last_login_ip = ip
    user.save(update_fields=["known_ips", "last_login_ip", "updated_at"])


def restrict_account(user, actor, capability: str, reason: str,
                     minutes: int | None = None, request=None):
    """Capability-level restriction — narrower than suspension."""
    from apps.accounts.models import UserRestriction

    expires = (timezone.now() + timedelta(minutes=minutes)
               if minutes else None)
    restriction = UserRestriction.objects.create(
        user=user, capability=capability, reason=reason,
        created_by=actor, expires_at=expires,
    )
    if user.account_status == user.AccountStatus.ACTIVE:
        user.account_status = user.AccountStatus.RESTRICTED
        user.save(update_fields=["account_status", "updated_at"])
    record_event(SecurityEvent.Type.ACCOUNT_RESTRICTED, user=user,
                 request=request, resource=user,
                 metadata={"capability": capability, "reason": reason,
                           "actor": actor.email})
    return restriction


def suspend_account(user, actor, reason: str, minutes: int | None = None,
                    request=None) -> None:
    user.account_status = user.AccountStatus.SUSPENDED
    user.suspension_reason = reason
    user.suspended_at = timezone.now()
    user.suspended_by = actor
    user.suspension_until = (
        timezone.now() + timedelta(minutes=minutes) if minutes else None
    )
    user.save(update_fields=["account_status", "suspension_reason",
                             "suspended_at", "suspended_by",
                             "suspension_until", "updated_at"])
    record_event(SecurityEvent.Type.ACCOUNT_SUSPENDED, user=user,
                 request=request, resource=user,
                 metadata={"reason": reason, "actor": actor.email})


def restore_account(user, actor, request=None) -> None:
    user.account_status = user.AccountStatus.ACTIVE
    user.suspension_reason = ""
    user.suspension_until = None
    user.save(update_fields=["account_status", "suspension_reason",
                             "suspension_until", "updated_at"])
    # Restore lifts all open restrictions too.
    user.restrictions.filter(revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_by=actor,
    )
    record_event(SecurityEvent.Type.ACCOUNT_RESTORED, user=user,
                 request=request, resource=user,
                 metadata={"actor": actor.email})


def auto_lift_suspension(user) -> None:
    """A timed suspension that has elapsed restores itself lazily."""
    if (
        user.account_status == user.AccountStatus.SUSPENDED
        and user.suspension_until
        and user.suspension_until <= timezone.now()
    ):
        user.account_status = user.AccountStatus.ACTIVE
        user.save(update_fields=["account_status", "updated_at"])


def open_incident(*, title: str, severity: str, incident_type: str,
                  description: str = "", affected_service: str = "",
                  linked_event: SecurityEvent | None = None) -> SecurityIncident:
    incident = SecurityIncident.objects.create(
        incident_ref=generate_reference("INC"),
        severity=severity,
        incident_type=incident_type,
        title=title,
        description=description,
        affected_service=affected_service,
    )
    if linked_event is not None:
        incident.events.add(linked_event)
    logger.warning("security incident opened: %s %s", incident.incident_ref,
                   title)
    return incident


def transition_incident(incident: SecurityIncident, to_status: str,
                        actor=None, resolution: str = "") -> SecurityIncident:
    from apps.common.exceptions import BusinessError

    if not incident.can_transition_to(to_status):
        raise BusinessError(
            f"Cannot move incident from {incident.status} to {to_status}.",
            code="INVALID_INCIDENT_TRANSITION",
        )
    incident.status = to_status
    if to_status == SecurityIncident.Status.RESOLVED:
        incident.resolved_at = timezone.now()
        incident.resolution = resolution
    incident.save()
    if actor is not None:
        record_event(SecurityEvent.Type.ADMIN_ACTION, user=actor,
                     resource=incident,
                     metadata={"action": f"incident:{to_status}",
                               "incident": incident.incident_ref})
    return incident
