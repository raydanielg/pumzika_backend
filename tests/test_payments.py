"""Payment initiation, webhook idempotency, refunds, wallet, payouts."""
import json
from decimal import Decimal

from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.payments import services as payment_services
from apps.payments.models import Payment, Refund, WebhookEvent
from apps.payments.providers import mock_webhook_signature
from apps.payouts import services as payout_services
from apps.payouts.models import HostWallet, Payout, PayoutMethod, WalletTransaction
from apps.common.exceptions import BusinessError
from apps.promotions.models import Promotion
from apps.promotions import services as promo_services
from django.utils import timezone
from datetime import timedelta

from .base import BaseTestCase


def _make_booking(tc, guest=None) -> Booking:
    return booking_services.create_booking(
        guest or tc.guest, property_id=tc.property.id,
        check_in=tc.check_in, check_out=tc.check_out, guests_count=2,
    )


class PaymentTests(BaseTestCase):
    def test_initiate_payment_is_idempotent(self):
        booking = _make_booking(self)
        p1 = payment_services.initiate_payment(
            self.guest, booking_id=booking.id,
            provider_code="MOCK", idempotency_key="idem-1",
        )
        p2 = payment_services.initiate_payment(
            self.guest, booking_id=booking.id,
            provider_code="MOCK", idempotency_key="idem-1",
        )
        assert p1.id == p2.id
        booking.refresh_from_db()
        assert booking.status == Booking.Status.AWAITING_PAYMENT

    def test_webhook_confirms_booking_and_is_idempotent(self):
        booking = _make_booking(self)
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id,
            provider_code="MOCK", idempotency_key="idem-2",
        )
        body = json.dumps({
            "event_id": "evt-1",
            "event_type": "payment.success",
            "data": {"reference": payment.reference,
                     "external_reference": "MOCK-XYZ"},
        }).encode()
        headers = {"x-webhook-signature": mock_webhook_signature(body)}

        event1 = payment_services.process_webhook("MOCK", body, headers)
        payment.refresh_from_db()
        booking.refresh_from_db()
        assert payment.status == Payment.Status.SUCCESS
        assert booking.status == Booking.Status.CONFIRMED
        assert event1.status == WebhookEvent.Status.PROCESSED

        # Replay — must be a no-op.
        event2 = payment_services.process_webhook("MOCK", body, headers)
        assert event2.id == event1.id
        assert Payment.objects.filter(booking=booking).count() == 1

    def test_webhook_rejects_bad_signature(self):
        body = json.dumps({
            "event_id": "evt-bad", "event_type": "payment.success",
            "data": {},
        }).encode()
        with self.assertRaises(BusinessError):
            payment_services.process_webhook(
                "MOCK", body, {"x-webhook-signature": "bad"}
            )

    def test_refund_updates_payment_state(self):
        booking = _make_booking(self)
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id,
            provider_code="MOCK", idempotency_key="idem-3",
        )
        body = json.dumps({
            "event_id": "evt-2", "event_type": "payment.success",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        refund = payment_services.initiate_refund(
            booking=booking, amount=Decimal("1000"), reason="test",
            requested_by=self.admin,
        )
        assert refund.status == Refund.Status.SUCCESS
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PARTIALLY_REFUNDED

        refund2 = payment_services.initiate_refund(
            booking=booking, amount=payment.refundable_amount, reason="rest",
            requested_by=self.admin,
        )
        payment.refresh_from_db()
        assert payment.status == Payment.Status.REFUNDED
        booking.refresh_from_db()
        assert booking.status == Booking.Status.REFUNDED

    def test_client_cannot_confirm_payment(self):
        """Payment state never comes from the client — only webhooks."""
        booking = _make_booking(self)
        resp = self.auth_client(self.guest).post("/api/v1/payments/initiate/", {
            "booking_id": str(booking.id), "provider": "MOCK",
            "idempotency_key": "idem-x", "status": "SUCCESS",
        })
        payment = Payment.objects.get(booking=booking)
        assert payment.status == Payment.Status.PENDING


class PayoutTests(BaseTestCase):
    def _confirmed_completed_booking(self) -> Booking:
        booking = _make_booking(self)
        payment_services.initiate_payment(
            self.guest, booking_id=booking.id,
            provider_code="MOCK", idempotency_key="idem-p",
        )
        payment = Payment.objects.get(booking=booking)
        body = json.dumps({
            "event_id": "evt-pay", "event_type": "payment.success",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        booking.refresh_from_db()
        booking.check_in = timezone.now().date()  # allow check-in
        booking.save()
        booking_services.check_in(booking, self.host)
        booking_services.complete_booking(booking, self.host)
        return booking

    def test_completed_booking_credits_host_wallet(self):
        booking = self._confirmed_completed_booking()
        wallet = HostWallet.objects.get(user=self.host)
        assert wallet.balance == booking.price.host_payout_amount
        assert WalletTransaction.objects.filter(
            booking=booking, transaction_type="EARNING"
        ).exists()

    def test_payout_request_and_approval(self):
        booking = self._confirmed_completed_booking()
        method = PayoutMethod.objects.create(
            user=self.host, method_type="MOBILE_MONEY", label="M-Pesa",
            account_name="H Host", account_number="2557000000",
        )
        payout = payout_services.request_payout(
            self.host, method.id, Decimal("5000")
        )
        assert payout.status == Payout.Status.PENDING
        wallet = HostWallet.objects.get(user=self.host)
        assert wallet.balance == booking.price.host_payout_amount - Decimal("5000")

        payout_services.process_payout(self.admin, payout.id, approve=True)
        payout.refresh_from_db()
        assert payout.status == Payout.Status.COMPLETED

    def test_rejected_payout_reverses_funds(self):
        self._confirmed_completed_booking()
        wallet = HostWallet.objects.get(user=self.host)
        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="Bank",
            account_name="H", account_number="123",
        )
        payout = payout_services.request_payout(
            self.host, method.id, Decimal("3000")
        )
        payout_services.process_payout(self.admin, payout.id, approve=False,
                                       reason="bad method")
        wallet.refresh_from_db()
        booking = Booking.objects.latest("created_at")
        assert wallet.balance == booking.price.host_payout_amount
        reversal = WalletTransaction.objects.filter(
            payout=payout, transaction_type="REVERSAL"
        ).exists()
        assert reversal

    def test_payout_exceeding_balance_rejected(self):
        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="B",
            account_name="H", account_number="9",
        )
        with self.assertRaises(BusinessError) as ctx:
            payout_services.request_payout(self.host, method.id, Decimal("999"))
        assert ctx.exception.code == "BELOW_PAYOUT_MINIMUM"


class PromoTests(BaseTestCase):
    def test_promo_validation_and_usage(self):
        promo = Promotion.objects.create(
            code="WELCOME10", name="Welcome", discount_type="PERCENT",
            value=Decimal("10"),
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
            per_user_limit=1,
        )
        promo2, discount = promo_services.validate_for_booking(
            "WELCOME10", self.property, self.guest,
            self.check_in, self.check_out,
        )
        assert discount > 0
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=2, promo_code="WELCOME10",
        )
        assert booking.price.discount == discount

        # Second use by same user -> per-user limit.
        with self.assertRaises(BusinessError) as ctx:
            promo_services.validate_for_booking(
                "WELCOME10", self.property, self.guest,
                self.check_in + timedelta(days=20), self.check_out + timedelta(days=20),
            )
        assert ctx.exception.code == "PROMO_USER_LIMIT"
