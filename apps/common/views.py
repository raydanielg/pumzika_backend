"""Health probes — no sensitive internals exposed."""
from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


@extend_schema(exclude=True)
class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"})


@extend_schema(exclude=True)
class HealthDBView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({"database": "ok"})
        except Exception:
            return Response({"database": "error"}, status=503)


@extend_schema(exclude=True)
class HealthRedisView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            cache.set("health_probe", "ok", timeout=5)
            if cache.get("health_probe") == "ok":
                return Response({"redis": "ok"})
            return Response({"redis": "error"}, status=503)
        except Exception:
            return Response({"redis": "error"}, status=503)


@extend_schema(exclude=True)
class HealthLiveView(APIView):
    """Liveness — process is running; no dependency checks."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "alive"})


@extend_schema(exclude=True)
class HealthReadyView(APIView):
    """Readiness — DB + cache must both respond; 503 when either is down."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
        try:
            cache.set("health_probe", "ok", timeout=5)
            checks["redis"] = "ok" if cache.get("health_probe") == "ok" else "error"
        except Exception:
            checks["redis"] = "error"
        healthy = all(v == "ok" for v in checks.values())
        return Response({"ready": healthy, **checks},
                        status=200 if healthy else 503)
