"""PropertyUnit (rooms) — API CRUD, permissions, unit-scoped availability."""
from decimal import Decimal

from django.db import transaction

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.availability.services import check_availability
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.common.exceptions import BusinessError
from apps.properties.models import PropertyUnit

from .base import BaseTestCase


class UnitApiTests(BaseTestCase):
    """Hosts manage units; guests see active units on published listings."""

    def _host(self):
        return self.auth_client(self.host)

    def _guest(self):
        return self.auth_client(self.guest)

    def test_host_can_create_list_update_delete_unit(self):
        c = self._host()
        r = c.post(f"/api/v1/properties/{self.property.id}/units/", {
            "name": "Standard room", "max_guests": 2, "beds": 1,
            "quantity": 3, "price_per_night": "35000",
        }, format="json")
        assert r.status_code == 201
        unit_id = r.json()["data"]["id"]

        r = c.get(f"/api/v1/properties/{self.property.id}/units/")
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1

        r = c.patch(f"/api/v1/properties/{self.property.id}/units/{unit_id}/",
                    {"price_per_night": "40000"}, format="json")
        assert r.status_code == 200
        assert r.json()["data"]["price_per_night"] == "40000.00"

        r = c.delete(f"/api/v1/properties/{self.property.id}/units/{unit_id}/")
        assert r.status_code == 204
        assert PropertyUnit.objects.count() == 0

    def test_other_host_cannot_manage_units(self):
        other_host = type(self.host).objects.create_user(
            email="host2@test.dev", password="Pass1234!", role=self.host.Role.HOST,
        )
        c = self.auth_client(other_host)
        r = c.post(f"/api/v1/properties/{self.property.id}/units/",
                   {"name": "Room"}, format="json")
        assert r.status_code in (403, 404)

    def test_public_sees_active_units_only(self):
        PropertyUnit.objects.create(
            property=self.property, name="Room A", is_active=True)
        PropertyUnit.objects.create(
            property=self.property, name="Room B", is_active=False)
        r = self._guest().get(f"/api/v1/properties/{self.property.id}/units/")
        names = [u["name"] for u in r.json()["data"]]
        assert "Room A" in names
        assert "Room B" not in names


class UnitBookingTests(BaseTestCase):
    def _unit(self, **kw):
        kw.setdefault("name", "Standard room")
        kw.setdefault("max_guests", 2)
        kw.setdefault("quantity", 2)
        return PropertyUnit.objects.create(property=self.property, **kw)

    def test_unit_price_overrides_property_price(self):
        unit = self._unit(price_per_night=Decimal("30000"))
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=2, unit_id=unit.id,
        )
        # 3 nights * 30000 = 90000 subtotal (unit price, not 50000)
        assert booking.price.nightly_subtotal == Decimal("90000.00")
        assert booking.unit_id == unit.id
        assert booking.unit_name == "Standard room"

    def test_unit_booking_does_not_block_other_units(self):
        unit_a = self._unit(name="A")
        unit_b = self._unit(name="B")
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=1, unit_id=unit_a.id,
        )
        # property-level rows unchanged; unit B still bookable same dates
        with transaction.atomic():
            check_availability(self.property, self.check_in, self.check_out,
                               unit=unit_b)
        booked = AvailabilityDate.objects.filter(
            unit=unit_a, status=AvailabilityStatus.BOOKED)
        assert booked.count() == 3
        assert not AvailabilityDate.objects.filter(unit=unit_b).exists()

    def test_unit_double_booking_rejected(self):
        # quantity=1 — second identical booking must fail
        unit = self._unit(quantity=1)
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=1, unit_id=unit.id,
        )
        try:
            booking_services.create_booking(
                self.other_guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1, unit_id=unit.id,
            )
            assert False, "should have raised"
        except BusinessError as e:
            assert e.code == "UNIT_NOT_AVAILABLE"

    def test_quantity_greater_than_one_sells_multiple(self):
        # quantity=2 — two bookings fit, the third is rejected
        unit = self._unit(quantity=2)
        third_guest = type(self.guest).objects.create_user(
            email="g3@test.dev", password="Pass1234!",
            role=self.guest.Role.GUEST, is_email_verified=True,
        )
        for guest in (self.guest, self.other_guest):
            booking_services.create_booking(
                guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1, unit_id=unit.id,
            )
        try:
            booking_services.create_booking(
                third_guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1, unit_id=unit.id,
            )
            assert False, "should have raised"
        except BusinessError as e:
            assert e.code == "UNIT_NOT_AVAILABLE"

    def test_cancel_releases_only_that_booking(self):
        unit = self._unit(quantity=2)
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=1, unit_id=unit.id,
        )
        second = booking_services.create_booking(
            self.other_guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=1, unit_id=unit.id,
        )
        booking_services.cancel_booking(second, self.other_guest, "changed plans")
        # first booking's nights are still held
        assert AvailabilityDate.objects.filter(
            unit=unit, status=AvailabilityStatus.BOOKED).count() == 3

    def test_unit_capacity_enforced(self):
        unit = self._unit(max_guests=1)
        try:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=2, unit_id=unit.id,
            )
            assert False, "should have raised"
        except BusinessError as e:
            assert e.code == "TOO_MANY_GUESTS"

    def test_inactive_unit_not_bookable(self):
        unit = self._unit(is_active=False)
        try:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1, unit_id=unit.id,
            )
            assert False, "should have raised"
        except BusinessError as e:
            assert e.code == "UNIT_NOT_FOUND"


class NoShowTests(BaseTestCase):
    def _confirmed_booking(self, check_in_offset=0):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out,
            guests_count=2,
        )
        booking.status = Booking.Status.CONFIRMED
        booking.save(update_fields=["status"])
        return booking

    def test_no_show_requires_past_checkin(self):
        booking = self._confirmed_booking()
        try:
            booking_services.mark_no_show(booking, self.host)
            assert False, "should have raised"
        except BusinessError as e:
            assert e.code == "TOO_EARLY"

    def test_no_show_credits_host(self):
        from datetime import timedelta
        from django.utils import timezone

        booking = self._confirmed_booking()
        Booking.objects.filter(pk=booking.pk).update(
            check_in=timezone.now().date() - timedelta(days=2))
        booking_services.mark_no_show(booking, self.host)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.NO_SHOW
        # host wallet credited like a completed stay
        from apps.payouts.models import HostWallet
        assert HostWallet.objects.filter(user=self.host).exists()

    def test_invalid_transition_rejected(self):
        booking = self._confirmed_booking()
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])
        try:
            booking_services.mark_no_show(booking, self.host)
            assert False, "should have raised"
        except BusinessError:
            pass
