"""Synchronous expiry sweep — releases dates for unpaid bookings.

Usage:
    python manage.py cleanup_expired_bookings           # expire them
    python manage.py cleanup_expired_bookings --dry-run # report only
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings import services


class Command(BaseCommand):
    help = "Expire PENDING/AWAITING_PAYMENT bookings past their payment window."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would expire without changing anything.")

    def handle(self, *args, **options):
        expired = list(Booking.objects.filter(
            status__in=[Booking.Status.PENDING, Booking.Status.AWAITING_PAYMENT],
            expires_at__lt=timezone.now(),
        ))
        self.stdout.write(f"found {len(expired)} expired booking(s)")
        if options["dry_run"]:
            for b in expired:
                self.stdout.write(f"  would expire {b.reference} (expired {b.expires_at})")
            return
        for b in expired:
            try:
                services.expire_booking(b)
                self.stdout.write(f"  expired {b.reference}")
            except Exception as exc:  # noqa: BLE001 — keep sweeping
                self.stderr.write(f"  {b.reference}: failed ({exc})")
        self.stdout.write(self.style.SUCCESS(f"expired {len(expired)} booking(s)"))
