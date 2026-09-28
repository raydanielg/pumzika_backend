"""Security events and incidents — the operational security ledger."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class SecurityEvent(TimeStampedModel):
    """Immutable record of a security-relevant occurrence."""

    class Type(models.TextChoices):
        LOGIN_FAILED = "LOGIN_FAILED", "Login Failed"
        LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login Success"
        SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN", "Suspicious Login"
        PASSWORD_CHANGED = "PASSWORD_CHANGED", "Password Changed"
        PASSWORD_RESET = "PASSWORD_RESET", "Password Reset"
        ACCOUNT_LOCKED = "ACCOUNT_LOCKED", "Account Locked"
        ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED", "Account Suspended"
        ACCOUNT_RESTORED = "ACCOUNT_RESTORED", "Account Restored"
        ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED", "Account Restricted"
        TOKEN_REVOKED = "TOKEN_REVOKED", "Token Revoked"
        EMAIL_VERIFIED = "EMAIL_VERIFIED", "Email Verified"
        PHONE_VERIFIED = "PHONE_VERIFIED", "Phone Verified"
        PERMISSION_CHANGE = "PERMISSION_CHANGE", "Permission Change"
        PERMISSION_DENIED = "PERMISSION_DENIED", "Permission Denied"
        RATE_LIMIT_TRIGGERED = "RATE_LIMIT_TRIGGERED", "Rate Limit Triggered"
        WEBHOOK_SIGNATURE_FAILED = "WEBHOOK_SIGNATURE_FAILED", "Webhook Signature Failed"
        PAYMENT_ANOMALY = "PAYMENT_ANOMALY", "Payment Anomaly"
        ADMIN_ACTION = "ADMIN_ACTION", "Admin Action"
        FILE_UPLOAD_REJECTED = "FILE_UPLOAD_REJECTED", "File Upload Rejected"
        OTP_FAILED = "OTP_FAILED", "OTP Failed"

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=40, choices=Type.choices,
                                  db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices,
                                db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="security_events",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    resource_type = models.CharField(max_length=60, blank=True)
    resource_id = models.CharField(max_length=64, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="security_events_resolved",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "-created_at"]),
            models.Index(fields=["severity", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]


class SecurityIncident(TimeStampedModel):
    """A tracked incident — CRITICAL events open one automatically."""

    class Status(models.TextChoices):
        DETECTED = "DETECTED", "Detected"
        INVESTIGATING = "INVESTIGATING", "Investigating"
        CONTAINED = "CONTAINED", "Contained"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    TRANSITIONS = {
        Status.DETECTED: {Status.INVESTIGATING},
        Status.INVESTIGATING: {Status.CONTAINED},
        Status.CONTAINED: {Status.RESOLVED},
        Status.RESOLVED: {Status.CLOSED},
        Status.CLOSED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident_ref = models.CharField(max_length=20, unique=True, db_index=True)
    severity = models.CharField(
        max_length=10, choices=SecurityEvent.Severity.choices, db_index=True
    )
    incident_type = models.CharField(max_length=60, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    affected_service = models.CharField(max_length=60, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DETECTED,
        db_index=True,
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incidents_assigned",
    )
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    events = models.ManyToManyField(SecurityEvent, related_name="incidents",
                                    blank=True)

    class Meta:
        ordering = ["-detected_at"]

    def can_transition_to(self, to_status: str) -> bool:
        return to_status in self.TRANSITIONS.get(self.status, set())
