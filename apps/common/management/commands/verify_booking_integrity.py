"""Detect integrity problems between bookings and availability rows.

Checks:
  * CONFIRMED/CHECKED_IN bookings with missing BOOKED availability rows
  * BOOKED rows referencing cancelled/expired bookings (stale holds)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.bookings.models import Booking


class Command(BaseCommand):
    help = "Audit booking/availability consistency. Read-only."

    def handle(self, *args, **options):
        problems = 0

        # active bookings should own BOOKED rows
        active = Booking.objects.filter(
            status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN],
        )
        for b in active.iterator():
            missing = AvailabilityDate.objects.filter(
                booking=b, status=AvailabilityStatus.BOOKED
            ).count()
            if missing == 0:
                problems += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"booking {b.reference} has no BOOKED availability rows"
                    )
                )

        # BOOKED rows pointing at dead bookings are stale holds
        dead = AvailabilityDate.objects.filter(
            status=AvailabilityStatus.BOOKED,
            booking__status__in=[
                Booking.Status.CANCELLED,
                Booking.Status.EXPIRED,
                Booking.Status.REFUNDED,
            ],
        ).select_related("booking")
        for row in dead.iterator():
            problems += 1
            self.stdout.write(
                self.style.WARNING(
                    f"stale BOOKED row {row.property_id}:{row.unit_id}:{row.date} "
                    f"on {row.booking.status} booking {row.booking.reference}"
                )
            )

        if problems == 0:
            self.stdout.write(self.style.SUCCESS("booking inventory consistent"))
        else:
            self.stdout.write(self.style.WARNING(f"{problems} issue(s) found"))
            raise SystemExit(2)
