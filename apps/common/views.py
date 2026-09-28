"""Health probes — no sensitive internals exposed."""
from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"})


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
