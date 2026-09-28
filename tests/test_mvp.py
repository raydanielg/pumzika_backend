"""MVP-specific behavior: idempotency, moderation flow, privacy, retries."""
import json
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.common.exceptions import BusinessError
from apps.notifications.models import (
    Notification, NotificationChannel, NotificationDelivery,
    UserNotificationSettings,
)
from apps.notifications.services import notify
from apps.payments import services as payment_services
from apps.payments.models import Payment
from apps.payments.providers import mock_webhook_signature
from apps.payouts import services as payout_services
from apps.payouts.models import HostWallet, PayoutMethod, Payout
from apps.properties import services as property_services
from apps.properties.models import Property, PropertyImage, PropertyType

from .base import BaseTestCase


def _draft_property(tc, with_images=0) -> Property:
    prop = Property.objects.create(
        host=tc.host, title="New Listing", description="Desc",
        property_type=tc.prop_type, country=tc.country, city=tc.city,
        address="1 Test St", base_price=Decimal("20000"), currency="TZS",
        cancellation_policy=tc.policy, status=Property.Status.DRAFT,
    )
    for _ in range(with_images):
        PropertyImage.objects.create(property=prop, is_cover=True)
    from apps.properties.models import Amenity, AmenityCategory
    cat = AmenityCategory.objects.create(name="Ess")
    prop.amenities.add(Amenity.objects.create(category=cat, name="WiFi"))
    return prop


class IdempotencyTests(BaseTestCase):
    def test_booking_create_replays_with_same_key(self):
        b1 = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=2, idempotency_key="key-1",
        )
        b2 = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=2, idempotency_key="key-1",
        )
        assert b1.id == b2.id
        assert Booking.objects.filter(guest=self.guest).count() == 1

    def test_payout_replays_with_same_key(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking_services.confirm_booking(booking)
        booking.refresh_from_db()
        booking.check_in = timezone.now().date()
        booking.save(update_fields=["check_in", "updated_at"])
        booking_services.check_in(booking, self.host)
        booking_services.complete_booking(booking, self.host)

        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="B",
            account_name="H", account_number="1",
        )
        p1 = payout_services.request_payout(
            self.host, method.id, Decimal("5000"), idempotency_key="pay-1"
        )
        p2 = payout_services.request_payout(
            self.host, method.id, Decimal("5000"), idempotency_key="pay-1"
        )
        assert p1.id == p2.id
        assert Payout.objects.filter(user=self.host).count() == 1

    def test_wallet_pending_balance_and_reconcile(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking_services.confirm_booking(booking)
        booking.refresh_from_db()
        booking.check_in = timezone.now().date()
        booking.save(update_fields=["check_in", "updated_at"])
        booking_services.check_in(booking, self.host)
        booking_services.complete_booking(booking, self.host)

        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="B",
            account_name="H", account_number="1",
        )
        wallet = HostWallet.objects.get(user=self.host)
        payout_services.request_payout(self.host, method.id, Decimal("1000"))
        wallet.refresh_from_db()
        assert wallet.pending_balance == Decimal("1000")

        # Reconcile is idempotent and reports no drift.
        result = payout_services.reconcile_wallet(self.host)
        assert result["drift_corrected"] is False


class PaymentRetryTests(BaseTestCase):
    def test_failed_payment_leaves_booking_payable(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-pay",
        )
        body = json.dumps({
            "event_id": "evt-fail", "event_type": "payment.failed",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        payment.refresh_from_db()
        booking.refresh_from_db()
        assert payment.status == Payment.Status.FAILED
        # Booking is still payable — guest retries.
        assert booking.status == Booking.Status.AWAITING_PAYMENT
        retry = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-pay-2",
        )
        assert retry.id != payment.id

    def test_receipt_requires_successful_payment(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-rcpt",
        )
        client = self.auth_client(self.guest)
        resp = client.get(f"/api/v1/payments/{payment.id}/receipt/")
        assert resp.status_code == 400  # not paid yet

        body = json.dumps({
            "event_id": "evt-rcpt", "event_type": "payment.success",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        resp = client.get(f"/api/v1/payments/{payment.id}/receipt/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["payment_reference"] == payment.reference
        assert data["booking_reference"] == booking.reference


class BookingLifecycleTests(BaseTestCase):
    def test_unverified_guest_cannot_book(self):
        self.guest.is_email_verified = False
        self.guest.save()
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1,
            )
        assert ctx.exception.code == "EMAIL_NOT_VERIFIED"

    def test_guest_breakdown_validates_capacity(self):
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1, adults=4, children=2,  # 6 > max_guests=4
            )
        assert ctx.exception.code == "TOO_MANY_GUESTS"

        # Infants do not count toward occupancy.
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=1, adults=3, children=1, infants=2,
        )
        assert booking.guests_count == 4
        assert booking.infants == 2

    def test_snapshot_survives_later_changes(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        old_title = booking.property_title
        old_total = booking.price.total
        # Host edits + reprices the listing after the booking.
        self.property.title = "Completely Different Name"
        self.property.base_price = Decimal("999999")
        self.property.save()

        booking.refresh_from_db()
        assert booking.property_title == old_title
        assert booking.price.total == old_total
        assert booking.host_id == self.host.id

    def test_event_log_sequence(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-evt",
        )
        body = json.dumps({
            "event_id": "evt-seq", "event_type": "payment.success",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        events = list(booking.events.values_list("event_type", flat=True))
        assert events.index("BOOKING_CREATED") < events.index("PAYMENT_STARTED") \
            < events.index("PAYMENT_SUCCESS")
        assert "BOOKING_CONFIRMED" in events

    def test_host_cancel_requires_reason_and_refunds_fully(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking_services.confirm_booking(booking)

        with self.assertRaises(BusinessError) as ctx:
            booking_services.cancel_booking(booking, self.host)
        assert ctx.exception.code == "REASON_REQUIRED"

        booking_services.cancel_booking(booking, self.host, "Host emergency")
        assert booking.cancellation.refund_amount == booking.price.total

    def test_auto_complete_checkouts(self):
        from apps.bookings.tasks import auto_complete_checkouts

        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking_services.confirm_booking(booking)
        booking.refresh_from_db()
        booking.check_in = timezone.now().date()
        booking.save(update_fields=["check_in", "updated_at"])
        booking_services.check_in(booking, self.host)
        booking.refresh_from_db()
        booking.check_out = timezone.now().date() - timedelta(days=1)
        booking.save(update_fields=["check_out", "updated_at"])

        ran = auto_complete_checkouts()
        booking.refresh_from_db()
        assert ran == 1
        assert booking.status == Booking.Status.COMPLETED
        # Idempotent — second run is a no-op.
        assert auto_complete_checkouts() == 0


class ModerationTests(BaseTestCase):
    def test_submit_requires_complete_listing(self):
        prop = _draft_property(self, with_images=0)
        with self.assertRaises(BusinessError) as ctx:
            property_services.submit_for_review(prop)
        assert ctx.exception.code == "PROPERTY_INCOMPLETE"
        assert "images" in ctx.exception.details
        assert "cover_image" in ctx.exception.details

    def test_full_moderation_flow(self):
        prop = _draft_property(self, with_images=3)
        property_services.submit_for_review(prop)
        assert prop.status == Property.Status.SUBMITTED

        # Host cannot approve or publish directly.
        with self.assertRaises(BusinessError):
            property_services.publish_property(prop)

        property_services.approve_property(prop, admin=self.admin)
        assert prop.status == Property.Status.APPROVED
        assert prop.approved_by == self.admin

        property_services.publish_property(prop)
        assert prop.status == Property.Status.PUBLISHED

    def test_reject_requires_reason(self):
        prop = _draft_property(self, with_images=3)
        property_services.submit_for_review(prop)
        with self.assertRaises(BusinessError) as ctx:
            property_services.reject_property(prop, "")
        assert ctx.exception.code == "REASON_REQUIRED"


class PaymentSafetyTests(BaseTestCase):
    def _paid_payment(self, key="k-ps"):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key=key,
        )
        body = json.dumps({
            "event_id": f"evt-{key}", "event_type": "payment.success",
            "data": {"reference": payment.reference},
        }).encode()
        payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )
        payment.refresh_from_db()
        return booking, payment

    def _webhook(self, payment, event_id, event_type, **data):
        body = json.dumps({
            "event_id": event_id, "event_type": event_type,
            "data": {"reference": payment.reference, **data},
        }).encode()
        return payment_services.process_webhook(
            "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
        )

    def test_amount_mismatch_rejects_confirmation(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-amt",
        )
        event = self._webhook(payment, "evt-bad-amt", "payment.success",
                              amount="1.00")
        payment.refresh_from_db()
        booking.refresh_from_db()
        assert event.status == "FAILED"
        assert payment.status != Payment.Status.SUCCESS
        assert booking.status != Booking.Status.CONFIRMED

    def test_currency_mismatch_rejects_confirmation(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-cur",
        )
        event = self._webhook(payment, "evt-bad-cur", "payment.success",
                              currency="USD")
        payment.refresh_from_db()
        assert event.status == "FAILED"
        assert payment.status != Payment.Status.SUCCESS

    def test_webhook_replay_five_times_confirms_once(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        payment = payment_services.initiate_payment(
            self.guest, booking_id=booking.id, provider_code="MOCK",
            idempotency_key="k-r5",
        )
        for _ in range(5):  # same event id delivered repeatedly
            event = self._webhook(payment, "evt-dup", "payment.success")
            assert event.status == "PROCESSED"
        booking.refresh_from_db()
        payment.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        # one confirmation, one ledger row
        assert payment.transactions.filter(
            event_type="WEBHOOK_SUCCESS").count() == 1

        # distinct event ids for the same paid payment are also no-ops
        self._webhook(payment, "evt-other", "payment.success")
        assert payment.transactions.filter(
            event_type="WEBHOOK_SUCCESS").count() == 1

    def test_success_cannot_go_backwards(self):
        _, payment = self._paid_payment("k-back")
        assert not payment.can_transition_to(Payment.Status.PENDING)
        with self.assertRaises(BusinessError):
            payment_services._transition_payment(
                payment, Payment.Status.PENDING, "ILLEGAL"
            )

    def test_over_refund_rejected(self):
        booking, payment = self._paid_payment("k-ovr")
        payment_services.initiate_refund(
            booking=booking, amount=payment.amount - 1, reason="r1",
            requested_by=self.admin, idempotency_key="rfd-1",
        )
        with self.assertRaises(BusinessError) as ctx:
            payment_services.initiate_refund(
                booking=booking, amount=Decimal("5"), reason="r2",
                requested_by=self.admin, idempotency_key="rfd-2",
            )
        assert ctx.exception.code == "REFUND_TOO_LARGE"

    def test_partial_refund_status(self):
        booking, payment = self._paid_payment("k-part")
        payment_services.initiate_refund(
            booking=booking, amount=Decimal("1000"), reason="partial",
            requested_by=self.admin, idempotency_key="rfd-p",
        )
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PARTIALLY_REFUNDED

    def test_insufficient_payout_balance(self):
        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="B",
            account_name="H", account_number="1",
        )
        with self.assertRaises(BusinessError) as ctx:
            payout_services.request_payout(
                self.host, method.id, Decimal("999999999"),
            )
        assert ctx.exception.code in ("INSUFFICIENT_FUNDS", "BELOW_MINIMUM_PAYOUT")

    def test_payment_statuses_have_machine(self):
        payment = Payment(status=Payment.Status.SUCCESS)
        assert not payment.can_transition_to(Payment.Status.PENDING)
        assert payment.can_transition_to(Payment.Status.REFUNDED)


class LocationPrivacyTests(BaseTestCase):
    def test_public_listing_hides_exact_location(self):
        resp = self.client.get(f"/api/v1/properties/{self.property.id}/")
        data = resp.json()["data"]
        assert "address" not in data
        assert "latitude" not in data
        assert data["exact_location_available"] is False
        # approx coords are rounded to 2 decimals
        assert len(data["approximate_latitude"].split(".")[-1]) <= 2 or \
            data["approximate_latitude"] is None

    def test_confirmed_booking_reveals_location(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        from apps.bookings.serializers import BookingSerializer

        data = BookingSerializer(booking).data
        assert data["property_location"] is None  # pending stays private

        booking_services.confirm_booking(booking)
        booking.refresh_from_db()
        data = BookingSerializer(booking).data
        assert data["property_location"]["address"] == "1 Ocean Rd"


class NotificationPrefTests(BaseTestCase):
    def test_critical_events_bypass_preferences(self):
        settings_row, _ = UserNotificationSettings.objects.get_or_create(
            user=self.guest
        )
        settings_row.email_notifications = False
        settings_row.sms_notifications = False
        settings_row.save()

        notify(self.guest, "SECURITY_ALERT", "alert", "body")
        channels = set(
            Notification.objects.filter(
                user=self.guest, event_type="SECURITY_ALERT"
            ).values_list("channel", flat=True)
        )
        assert NotificationChannel.EMAIL in channels

    def test_marketing_opt_out(self):
        settings_row, _ = UserNotificationSettings.objects.get_or_create(
            user=self.guest
        )
        settings_row.marketing_notifications = False
        settings_row.save()
        notify(self.guest, "WELCOME", "hi", "there")
        assert not Notification.objects.filter(
            user=self.guest, event_type="WELCOME",
            channel=NotificationChannel.EMAIL,
        ).exists()

    def test_delivery_records_created(self):
        notify(self.guest, "NEW_MESSAGE", "hi", "body")
        notif = Notification.objects.get(
            user=self.guest, event_type="NEW_MESSAGE",
            channel=NotificationChannel.IN_APP,
        )
        delivery = notif.deliveries.get()
        assert delivery.status == NotificationDelivery.Status.SENT
