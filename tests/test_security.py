"""Security layer tests — lockout, suspension, events, incidents."""
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from apps.accounts.models import User
from apps.common.exceptions import BusinessError
from apps.payments.models import Payment
from apps.bookings import services as booking_services
from apps.payments import services as payment_services
from apps.payments.providers import mock_webhook_signature
from apps.security.models import SecurityEvent, SecurityIncident
from apps.security import services as sec

from .base import BaseTestCase


class LoginSecurityTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_failed_login_records_event(self):
        count = sec.record_login_failure("guest@x.com")
        assert count == 1
        assert SecurityEvent.objects.filter(
            event_type=SecurityEvent.Type.LOGIN_FAILED).count() == 1

    def test_lockout_after_threshold(self):
        with override_settings():
            for _ in range(5):
                sec.record_login_failure("guest@x.com")
            assert sec.is_login_locked("guest@x.com")
            assert SecurityEvent.objects.filter(
                event_type=SecurityEvent.Type.ACCOUNT_LOCKED).exists()

    def test_new_ip_is_suspicious(self):
        self.guest.known_ips = ["1.1.1.1"]
        self.guest.save()

        class Req:
            META = {"REMOTE_ADDR": "9.9.9.9", "HTTP_USER_AGENT": "t"}
            request_id = "r1"

        with patch("apps.notifications.tasks.notify_security_alert") as m:
            m.delay = lambda *a, **k: None
            sec.record_login_success(self.guest, Req())
        assert SecurityEvent.objects.filter(
            event_type=SecurityEvent.Type.SUSPICIOUS_LOGIN).exists()
        self.guest.refresh_from_db()
        assert "9.9.9.9" in self.guest.known_ips


class SuspensionTests(BaseTestCase):
    def test_suspended_user_blocked(self):
        sec.suspend_account(self.guest, self.admin, "fraud")
        self.guest.refresh_from_db()
        assert self.guest.is_access_blocked
        with self.assertRaises(BusinessError):
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1,
            )

    def test_timed_suspension_auto_lifts(self):
        from datetime import timedelta

        sec.suspend_account(self.guest, self.admin, "temp", minutes=-1)
        self.guest.refresh_from_db()
        sec.auto_lift_suspension(self.guest)
        assert self.guest.account_status == User.AccountStatus.ACTIVE

    def test_restore_clears_fields(self):
        sec.suspend_account(self.guest, self.admin, "x")
        sec.restore_account(self.guest, self.admin)
        self.guest.refresh_from_db()
        assert self.guest.account_status == User.AccountStatus.ACTIVE


class IncidentTests(BaseTestCase):
    def test_critical_event_opens_incident(self):
        sec.record_event(
            SecurityEvent.Type.PAYMENT_ANOMALY,
            metadata={"detail": "amount mismatch", "service": "payments"},
        )
        assert SecurityIncident.objects.filter(
            incident_type="PAYMENT_ANOMALY",
            status=SecurityIncident.Status.DETECTED).exists()

    def test_incident_workflow_enforced(self):
        inc = sec.open_incident(
            title="t", severity="HIGH", incident_type="TEST")
        with self.assertRaises(BusinessError):
            sec.transition_incident(inc, "RESOLVED")  # skips INVESTIGATING
        inc = sec.transition_incident(inc, "INVESTIGATING", actor=self.admin)
        inc = sec.transition_incident(inc, "CONTAINED")
        inc = sec.transition_incident(inc, "RESOLVED", resolution="fixed")
        assert inc.resolved_at is not None


class WebhookSecurityTests(BaseTestCase):
    def test_forged_signature_logged(self):
        try:
            payment_services.process_webhook(
                "MOCK", b"{}", {"x-webhook-signature": "forged"}
            )
        except BusinessError:
            pass
        assert SecurityEvent.objects.filter(
            event_type=SecurityEvent.Type.WEBHOOK_SIGNATURE_FAILED).exists()

    def test_amount_mismatch_is_critical_event(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-mis",
        )
        body = json.dumps({
            "event_id": "evt-mis", "event_type": "payment.success",
            "data": {"reference": payment.reference, "amount": "1.00"},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        assert SecurityEvent.objects.filter(
            event_type=SecurityEvent.Type.PAYMENT_ANOMALY).exists()
        assert SecurityIncident.objects.filter(
            incident_type="PAYMENT_ANOMALY").exists()


class AuditImmutabilityTests(BaseTestCase):
    def test_audit_admin_readonly(self):
        from apps.admin_panel.admin import AuditLogAdmin
        from django.test import RequestFactory

        admin_inst = AuditLogAdmin(
            __import__("apps.admin_panel.models", fromlist=["x"]).AuditLog,
            __import__("django.contrib.admin", fromlist=["x"]).site,
        )
        req = RequestFactory().get("/admin/")
        assert not admin_inst.has_add_permission(req)
        assert not admin_inst.has_change_permission(req)
        assert not admin_inst.has_delete_permission(req)
