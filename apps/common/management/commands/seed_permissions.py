"""Seed role -> permission-code grants from accounts.constants.ROLE_DEFAULTS."""
from django.core.management.base import BaseCommand

from apps.accounts.constants import ROLE_DEFAULTS
from apps.accounts.models import RolePermission


class Command(BaseCommand):
    help = "Seed role permission grants (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for role, codes in ROLE_DEFAULTS.items():
            for code in codes:
                _, was_created = RolePermission.objects.get_or_create(
                    role=role, code=code
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded role permissions ({created} new grants)."
        ))
