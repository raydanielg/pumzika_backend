"""Check connectivity to Django's critical dependencies.

Usage: python manage.py health_check
"""
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Verify database, cache/Redis and Celery broker connectivity."

    def handle(self, *args, **options):
        ok = True

        try:
            with connection.cursor() as c:
                c.execute("SELECT 1")
            self.stdout.write(self.style.SUCCESS("database: ok"))
        except Exception as exc:  # noqa: BLE001 — report any failure
            ok = False
            self.stdout.write(self.style.ERROR(f"database: FAIL ({exc})"))

        try:
            cache.set("pz_healthcheck", "ok", timeout=10)
            assert cache.get("pz_healthcheck") == "ok"
            self.stdout.write(self.style.SUCCESS("cache/redis: ok"))
        except Exception as exc:
            ok = False
            self.stdout.write(self.style.ERROR(f"cache/redis: FAIL ({exc})"))

        try:
            from celery import current_app

            current_app.connection().ensure_connection(max_retries=1, timeout=3)
            self.stdout.write(self.style.SUCCESS("celery broker: ok"))
        except Exception as exc:
            ok = False
            self.stdout.write(self.style.ERROR(f"celery broker: FAIL ({exc})"))

        if not ok:
            raise SystemExit(1)
