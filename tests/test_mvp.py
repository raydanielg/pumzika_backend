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
