"""Reviews eligibility, favorites dedupe, search visibility, admin perms."""
import json
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.common.exceptions import BusinessError, PermissionDeniedError
from apps.favorites.models import Favorite
from apps.messaging import services as msg_services
from apps.payments import services as payment_services
from apps.payments.models import Payment
from apps.payments.providers import mock_webhook_signature
from apps.properties.models import Property
from apps.reviews import services as review_services
from apps.reviews.models import PropertyReview

from .base import BaseTestCase


def _completed_booking(tc) -> Booking:
    booking = booking_services.create_booking(
        tc.guest, property_id=tc.property.id,
        check_in=tc.check_in, check_out=tc.check_out, guests_count=2,
    )
    payment = payment_services.initiate_payment(
        tc.guest, booking_id=booking.id, provider_code="MOCK",
        idempotency_key=f"idem-{booking.reference}",
    )
    body = json.dumps({
        "event_id": f"evt-{booking.reference}",
        "event_type": "payment.success",
        "data": {"reference": payment.reference},
    }).encode()
    payment_services.process_webhook(
        "MOCK", body, {"x-webhook-signature": mock_webhook_signature(body)}
    )
    booking.refresh_from_db()
    booking.refresh_from_db()
    booking.check_in = timezone.now().date()
    booking.save(update_fields=["check_in", "updated_at"])
    booking_services.check_in(booking, tc.host)
    booking_services.complete_booking(booking, tc.host)
    booking.refresh_from_db()
    return booking


class ReviewTests(BaseTestCase):
    def test_guest_can_review_completed_booking(self):
        booking = _completed_booking(self)
        review = review_services.create_property_review(
            self.guest, booking.id, rating=5, comment="Great stay",
            cleanliness=5, communication=4, location=5, value=4, accuracy=5,
        )
        self.property.refresh_from_db()
        assert self.property.review_count == 1
        assert self.property.rating == Decimal("5.00") or self.property.rating == Decimal("5")

    def test_review_requires_booking(self):
        from apps.common.exceptions import NotFoundError

        with self.assertRaises(NotFoundError):
            review_services.create_property_review(
                self.guest, "00000000-0000-0000-0000-000000000000", rating=5
            )

    def test_review_requires_completed_booking(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        with self.assertRaises(BusinessError) as ctx:
            review_services.create_property_review(
                self.guest, booking.id, rating=5
            )
        assert ctx.exception.code == "BOOKING_NOT_COMPLETED"

    def test_duplicate_review_blocked(self):
        booking = _completed_booking(self)
        review_services.create_property_review(self.guest, booking.id, rating=5)
        with self.assertRaises(BusinessError) as ctx:
            review_services.create_property_review(self.guest, booking.id, rating=4)
        assert ctx.exception.code == "REVIEW_EXISTS"

    def test_other_guest_cannot_review(self):
        booking = _completed_booking(self)
        with self.assertRaises(PermissionDeniedError):
            review_services.create_property_review(
                self.other_guest, booking.id, rating=5
            )


class FavoriteTests(BaseTestCase):
    def test_favorite_dedupe(self):
        f1, _ = Favorite.objects.get_or_create(
            user=self.guest, property=self.property
        )
        f2, created = Favorite.objects.get_or_create(
            user=self.guest, property=self.property
        )
        assert not created and f1.id == f2.id

    def test_favorite_endpoints(self):
        client = self.auth_client(self.guest)
        resp = client.post("/api/v1/favorites/add/",
                           {"property_id": str(self.property.id)})
        assert resp.status_code == 201
        resp = client.get(f"/api/v1/favorites/{self.property.id}/check/")
        assert resp.json()["data"]["is_favorite"] is True
        resp = client.delete(f"/api/v1/favorites/{self.property.id}/")
        assert resp.status_code == 204


class SearchTests(BaseTestCase):
    def test_search_returns_published_only(self):
        draft = Property.objects.create(
            host=self.host, title="Hidden", description="x",
            property_type=self.prop_type, country=self.country,
            city=self.city, address="?", base_price=Decimal("1000"),
            currency="TZS", status=Property.Status.DRAFT,
        )
        resp = self.client.get("/api/v1/search/properties/")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["data"]["results"]]
        assert str(self.property.id) in ids
        assert str(draft.id) not in ids

    def test_search_filters_dates(self):
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        resp = self.client.get("/api/v1/search/properties/", {
            "check_in": str(self.check_in), "check_out": str(self.check_out),
        })
        ids = [p["id"] for p in resp.json()["data"]["results"]]
        assert str(self.property.id) not in ids  # dates already booked

        resp2 = self.client.get("/api/v1/search/properties/", {
            "check_in": str(self.check_out + timedelta(days=10)),
            "check_out": str(self.check_out + timedelta(days=13)),
        })
        ids2 = [p["id"] for p in resp2.json()["data"]["results"]]
        assert str(self.property.id) in ids2

    def test_search_price_sort(self):
        cheap = Property.objects.create(
            host=self.host, title="Cheap", description="x",
            property_type=self.prop_type, country=self.country,
            city=self.city, address="?", base_price=Decimal("1"),
            currency="TZS", status=Property.Status.PUBLISHED,
        )
        resp = self.client.get("/api/v1/search/properties/", {"sort": "price_asc"})
        results = resp.json()["data"]["results"]
        assert results[0]["id"] == str(cheap.id)


class MessagingTests(BaseTestCase):
    def test_participant_only_access(self):
        convo = msg_services.start_conversation(
            self.guest, self.property.id, "Hello host"
        )
        msg_services.send_message(self.guest, convo.id, "Is it available?")

        # Host can read
        host_convo = msg_services.get_conversation_for_user(self.host, convo.id)
        assert host_convo.id == convo.id

        # Stranger cannot
        with self.assertRaises(PermissionDeniedError):
            msg_services.get_conversation_for_user(self.other_guest, convo.id)


class AdminPermissionTests(BaseTestCase):
    def test_guest_cannot_view_admin_dashboard(self):
        client = self.auth_client(self.guest)
        resp = client.get("/api/v1/admin/dashboard/")
        assert resp.status_code == 403

    def test_admin_dashboard_metrics(self):
        client = self.auth_client(self.admin)
        resp = client.get("/api/v1/admin/dashboard/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_users" in data and "published_properties" in data

    def test_guest_cannot_approve_property(self):
        client = self.auth_client(self.guest)
        resp = client.post(f"/api/v1/admin/properties/{self.property.id}/approve/")
        assert resp.status_code == 403
