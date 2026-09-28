"""Smart Stay Match — endpoint + engine behaviour."""
from decimal import Decimal

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.properties.models import Amenity, AmenityCategory, PropertyUnit
from apps.bookings import services as booking_services

from .base import BaseTestCase

URL = "/api/v1/search/match/"
PREFS_URL = "/api/v1/search/match/preferences/"


class MatchEndpointTests(BaseTestCase):
    def _payload(self, **kw):
        base = {
            "destination": "Dar es Salaam",
            "check_in": str(self.check_in),
            "check_out": str(self.check_out),
            "guests": 2,
            "preferences": ["beach"],
        }
        base.update(kw)
        return base

    def test_anonymous_match_returns_enveloped_results(self):
        r = self.auth_client(self.guest).post(URL, self._payload(), format="json")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data["count"] == 1
        item = data["results"][0]
        assert item["id"] == str(self.property.id)
        assert item["match_label"] in (
            "great_match", "good_match", "fits_your_trip")
        assert "Available for your dates" in item["match_reasons"]
        assert item["total_price"] is not None  # real priced total

    def test_truly_anonymous_can_match(self):
        r = self.client.post(URL, self._payload(), format="json")
        assert r.status_code == 200

    def test_preferences_listed(self):
        r = self.client.get(PREFS_URL)
        assert r.status_code == 200
        prefs = r.json()["data"]["preferences"]
        assert "beach" in prefs and "budget" in prefs

    def test_invalid_dates_rejected(self):
        r = self.client.post(URL, self._payload(
            check_in=str(self.check_out), check_out=str(self.check_in)))
        assert r.status_code == 400
        assert r.json()["success"] is False

    def test_past_checkin_rejected(self):
        from datetime import date, timedelta
        r = self.client.post(URL, self._payload(
            check_in=str(date.today() - timedelta(days=1))))
        assert r.status_code == 400

    def test_unknown_preference_rejected(self):
        r = self.client.post(URL, self._payload(preferences=["teleport"]))
        assert r.status_code == 400

    def test_guests_required(self):
        p = self._payload()
        del p["guests"]
        r = self.client.post(URL, p, format="json")
        assert r.status_code == 400

    def test_budget_filters_expensive_property(self):
        r = self.client.post(URL, self._payload(
            budget_per_night="1000"), format="json")
        data = r.json()["data"]
        assert data["count"] == 0
        assert {s["type"] for s in data["suggestions"]} >= {
            "raise_budget", "remove_preference", "change_dates",
            "expand_destination"}

    def test_capacity_excludes_too_small_property(self):
        r = self.client.post(URL, self._payload(guests=9), format="json")
        assert r.json()["data"]["count"] == 0

    def test_booked_property_excluded(self):
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=2)
        r = self.client.post(URL, self._payload(), format="json")
        assert r.json()["data"]["count"] == 0

    def test_blocked_dates_excluded(self):
        AvailabilityDate.objects.create(
            property=self.property, date=self.check_in,
            status=AvailabilityStatus.BLOCKED)
        r = self.client.post(URL, self._payload(), format="json")
        assert r.json()["data"]["count"] == 0

    def test_preference_score_and_reasons(self):
        cat = AmenityCategory.objects.create(name="Essentials")
        wifi = Amenity.objects.create(category=cat, name="Wi-Fi")
        self.property.amenities.add(wifi)
        self.property.description = "Beachfront apartment with sea view"
        self.property.save(update_fields=["description"])

        r = self.client.post(
            URL, self._payload(preferences=["beach", "business"]),
            format="json")
        item = r.json()["data"]["results"][0]
        assert item["match_label"] in ("great_match", "good_match")
        assert "Suits a beach stay" in item["match_reasons"]
        assert "Suits a business stay" in item["match_reasons"]

    def test_sort_price_asc(self):
        cheap = PropertyUnit.objects.create(
            property=self.property, name="Budget room",
            price_per_night=Decimal("20000"), is_active=True)
        assert cheap
        r = self.client.post(URL, self._payload(sort="price_asc"),
                             format="json")
        assert r.status_code == 200

    def test_unit_with_lower_price_satisfies_budget(self):
        PropertyUnit.objects.create(
            property=self.property, name="Budget room", max_guests=2,
            price_per_night=Decimal("30000"), is_active=True)
        r = self.client.post(URL, self._payload(budget_per_night="35000"),
                             format="json")
        data = r.json()["data"]
        assert data["count"] == 1
        assert "Within your budget" in data["results"][0]["match_reasons"]

    def test_pagination_respected(self):
        r = self.client.post(URL, self._payload(page=1, page_size=1),
                             format="json")
        data = r.json()["data"]
        assert data["page"] == 1
        assert len(data["results"]) <= 1
