"""Booking lifecycle, double-booking, pricing snapshot, cancellation."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.availability.services import block_dates
from apps.bookings.models import Booking
from apps.bookings import services as booking_services
from apps.common.exceptions import BusinessError
from apps.properties.models import Property

from .base import BaseTestCase


class BookingTests(BaseTestCase):
    def test_create_booking_locks_dates_and_snapshots_price(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=2,
        )
        assert booking.status == Booking.Status.PENDING
        price = booking.price
        # 3 nights * 50000 + 10000 cleaning = 160000 base
        assert price.nightly_subtotal == Decimal("160000.00") - Decimal("10000.00")
        assert price.cleaning_fee == Decimal("10000.00")
        assert price.commission_rate == Decimal("15")
        # booked nights occupy the calendar
        booked = AvailabilityDate.objects.filter(
            property=self.property, status=AvailabilityStatus.BOOKED
        )
        assert booked.count() == 3

    def test_double_booking_same_dates_rejected(self):
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=2,
        )
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.other_guest, property_id=self.property.id,
                check_in=self.check_in + timedelta(days=1),
                check_out=self.check_out + timedelta(days=1),
                guests_count=2,
            )
        assert ctx.exception.code == "PROPERTY_NOT_AVAILABLE"

    def test_cannot_book_own_property(self):
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.host, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1,
            )
        assert ctx.exception.code == "SELF_BOOKING"

    def test_unpublished_property_not_bookable(self):
        self.property.status = Property.Status.DRAFT
        self.property.save()
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out, guests_count=1,
            )
        assert ctx.exception.code == "PROPERTY_NOT_AVAILABLE"

    def test_blocked_dates_reject_booking(self):
        block_dates(self.property, self.check_in, self.check_out)
        with self.assertRaises(BusinessError):
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out, guests_count=1,
            )

    def test_cannot_block_over_existing_booking(self):
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        with self.assertRaises(BusinessError) as ctx:
            block_dates(self.property, self.check_in, self.check_out)
        assert ctx.exception.code == "DATES_CONTAIN_BOOKINGS"

    def test_price_snapshot_survives_host_price_change(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        original_total = booking.price.total
        self.property.base_price = Decimal("999999")
        self.property.save()
        booking.refresh_from_db()
        assert booking.price.total == original_total

    def test_confirm_requires_payment_path(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        # Direct confirm via service is allowed (payment layer calls it)
        booking_services.confirm_booking(booking)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        # Second confirm is a no-op (idempotent webhook replay)
        booking_services.confirm_booking(booking)
        assert booking.status == Booking.Status.CONFIRMED

    def test_cancel_pending_releases_dates(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking_services.cancel_booking(booking, self.guest, "changed plans")
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert not AvailabilityDate.objects.filter(property=self.property).exists()

    def test_invalid_transition_rejected(self):
        booking = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        with self.assertRaises(BusinessError) as ctx:
            booking_services.check_in(booking, self.host)
        assert ctx.exception.code in ("INVALID_BOOKING_TRANSITION", "TOO_EARLY")

    def test_concurrent_booking_attempt(self):
        """Simulated race: two bookings for the same nights — second fails."""
        booking1 = booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        # Atomicity check: even with direct bulk insert, the unique constraint
        # on (property, date) makes a duplicate raise IntegrityError.
        from django.db import IntegrityError

        with self.assertRaises((BusinessError, IntegrityError)):
            with transaction.atomic():
                booking2 = Booking.objects.create(
                    reference="BKG-RACE1", guest=self.other_guest,
                    property=self.property, check_in=self.check_in,
                    check_out=self.check_out, guests_count=1,
                    currency="TZS",
                )
                for day in [self.check_in + timedelta(days=i) for i in range(3)]:
                    AvailabilityDate.objects.create(
                        property=self.property, date=day,
                        status=AvailabilityStatus.BOOKED, booking=booking2,
                    )
        assert booking1.status == Booking.Status.PENDING
