"""Selcom provider tests — signature vectors, initiation, webhook verify."""
import base64
import hashlib
import hmac
import json
from decimal import Decimal

from django.test import override_settings

from apps.payments.models import Payment, PaymentProvider
from apps.payments.providers import get_provider
from apps.payments.providers.selcom import SelcomProvider
from apps.payments.providers.selcom.authentication import (
    auth_headers, build_signing_string, compute_digest,
)
from apps.bookings import services as booking_services
from apps.payments import services as payment_services

from .base import BaseTestCase

SECRET = "test-secret"


def _headers(body_params, fields, ts="2026-09-28T10:00:00+03:00"):
    return auth_headers("api-key", SECRET, body_params, fields, timestamp=ts)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class FakeSession:
    """Captures requests; serves canned responses keyed by path fragment."""

    def __init__(self, responses=None, fail_with=None):
        self.responses = responses or {}
        self.fail_with = fail_with
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json,
                           "headers": headers, "timeout": timeout})
        if self.fail_with:
            raise self.fail_with
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        return FakeResponse({"result": "OK", "data": [{"reference": "SEL-1"}]})


class SelcomSignatureTests(BaseTestCase):
    def test_signing_string_format(self):
        s = build_signing_string(
            "2026-09-28T10:00:00+03:00",
            {"vendor": "PUMZIKA", "order_id": "PZP-1", "amount": "1000"},
            ["vendor", "order_id", "amount"],
        )
        assert s == (
            "timestamp=2026-09-28T10:00:00+03:00"
            "&vendor=PUMZIKA&order_id=PZP-1&amount=1000"
        )

    def test_digest_matches_manual_hmac(self):
        signing = "timestamp=2019-02-26T09:30:46+03:00&vendor=BANKX&amount=1234"
        expected = base64.b64encode(
            hmac.new(SECRET.encode(), signing.encode(), hashlib.sha256).digest()
        ).decode()
        assert compute_digest(signing, SECRET) == expected

    def test_headers_complete(self):
        h = _headers({"vendor": "X"}, ["vendor"])
        assert h["Authorization"].startswith("SELCOM ")
        assert h["Digest-Method"] == "HS256"
        assert h["Signed-Fields"] == "vendor"
        assert base64.b64decode(h["Authorization"].split()[1]) == b"api-key"


class SelcomProviderTests(BaseTestCase):
    def _payment(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        return booking, Payment.objects.create(
            booking=booking, user=self.guest, provider_id=1,
            amount=booking.price.total, currency="TZS",
            idempotency_key="sel-1",
            reference="PZP-TEST1", expires_at=booking.expires_at,
        )

    def test_initiate_creates_signed_order(self):
        booking, payment = self._payment()
        session = FakeSession({
            "create-order": FakeResponse({
                "result": "SUCCESS",
                "data": [{"reference": "SEL-ORD-9",
                          "payment_gateway_url": "https://pay.selcom/x"}],
            }),
            "wallet-payment": FakeResponse({"result": "SUCCESS", "data": []}),
        })
        from apps.payments.providers.selcom.client import SelcomClient

        provider = SelcomProvider(
            client=SelcomClient(session=session)
        )
        with override_settings(
            SELCOM_API_KEY="k", SELCOM_API_SECRET="s",
            SELCOM_VENDOR_ID="PUMZIKA",
            SELCOM_BASE_URL="https://api.test",
        ):
            # force client reconfig
            provider.client = SelcomClient(session=session)
            result = provider.initiate(
                payment, {"method": "MOBILE_MONEY", "msisdn": "255700000000"}
            )
        assert result.status == "PENDING"
        assert result.checkout_url == "https://pay.selcom/x"
        assert len(session.calls) == 2  # create-order + wallet push
        order = session.calls[0]["json"]
        assert order["order_id"] == "PZP-TEST1"
        assert order["amount"] == str(int(payment.amount))
        assert order["currency"] == "TZS"
        # signed headers present on every call
        assert "Digest" in session.calls[0]["headers"]
        assert session.calls[1]["json"]["utilitycode"] == "walletpush"

    def test_webhook_verifies_against_remote_status(self):
        _, payment = self._payment()
        session = FakeSession({
            "order-status": FakeResponse({
                "result": "SUCCESS",
                "data": [{"payment_status": "COMPLETED", "transid": "SEL-T1"}],
            }),
        })
        from apps.payments.providers.selcom.client import SelcomClient

        provider = SelcomProvider()
        provider.client = SelcomClient(session=session)
        body = json.dumps({
            "data": [{"order_id": "PZP-TEST1", "transid": "SEL-T1"}]
        }).encode()
        with override_settings(
            SELCOM_API_KEY="k", SELCOM_API_SECRET="s",
            SELCOM_VENDOR_ID="PUMZIKA", SELCOM_BASE_URL="https://api.test",
        ):
            provider.client = SelcomClient(session=session)
            data = provider.verify_webhook(body, {})
        assert data.event_type == "payment.success"
        assert data.reference == "PZP-TEST1"
        assert data.external_reference == "SEL-T1"

    def test_webhook_rejects_unknown_status(self):
        from apps.payments.providers.selcom.client import SelcomClient
        from apps.payments.providers.base import VerificationFailed

        provider = SelcomProvider()
        session = FakeSession({
            "order-status": FakeResponse({"data": [{"payment_status": "??"}]}),
        })
        with override_settings(
            SELCOM_API_KEY="k", SELCOM_API_SECRET="s",
            SELCOM_VENDOR_ID="PUMZIKA", SELCOM_BASE_URL="https://api.test",
        ):
            provider.client = SelcomClient(session=session)
            with self.assertRaises(VerificationFailed):
                provider.verify_webhook(
                    json.dumps({"data": [{"order_id": "PZP-1"}]}).encode(), {}
                )

    def test_idempotency_key_cannot_be_rebound(self):
        booking1 = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment_services.initiate_payment(
            self.guest, booking_id=booking1.id, provider_code="MOCK",
            idempotency_key="shared-key",
        )
        booking2 = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in + __import__("datetime").timedelta(days=10),
            check_out=self.check_out + __import__("datetime").timedelta(days=10),
            guests_count=1,
        )
        from apps.common.exceptions import BusinessError

        with self.assertRaises(BusinessError) as ctx:
            payment_services.initiate_payment(
                self.guest, booking_id=booking2.id, provider_code="MOCK",
                idempotency_key="shared-key",
            )
        assert ctx.exception.code == "IDEMPOTENCY_CONFLICT"

    def test_booking_reference_accepted(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.reference, provider_code="MOCK",
            idempotency_key="k-ref",
        )
        assert payment.booking_id == booking.id
