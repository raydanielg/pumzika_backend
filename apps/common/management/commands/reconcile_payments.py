"""Report payments stuck in non-terminal states — for ops reconciliation.

Usage:
    python manage.py reconcile_payments             # report
    python manage.py reconcile_payments --hours 6   # custom staleness window
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import Payment


class Command(BaseCommand):
    help = "List payments stuck in PENDING/PROCESSING longer than expected."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=6,
                            help="Consider payments older than this stale.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        stale = Payment.objects.filter(
            status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
            updated_at__lt=cutoff,
        ).order_by("updated_at")
        self.stdout.write(f"stale payments (>{options['hours']}h): {stale.count()}")
        for p in stale.iterator():
            self.stdout.write(
                f"  {p.id} {p.provider}:{p.provider_reference or '-'} "
                f"{p.amount} {p.currency} {p.status} since {p.updated_at}"
            )
        if not stale.exists():
            self.stdout.write(self.style.SUCCESS("nothing to reconcile"))
