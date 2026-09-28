"""Request-ID propagation and request logging middleware."""
from __future__ import annotations

import logging
import time
import uuid

request_logger = logging.getLogger("pumzika.request")


class RequestIDMiddleware:
    """Attach a request ID (from the client or generated) to each request."""

    HEADER = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get(self.HEADER) or uuid.uuid4().hex
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response


class RequestLoggingMiddleware:
    """Log every request with method/path/status/duration — never bodies."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        user_id = getattr(getattr(request, "user", None), "id", None)
        request_logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "user_id": str(user_id) if user_id else None,
            },
        )
        return response


class AccountStatusMiddleware:
    """Block suspended/deactivated accounts on every authenticated request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "is_access_blocked", False)
        ):
            from django.http import JsonResponse

            return JsonResponse(
                {
                    "success": False,
                    "error": {
                        "code": "ACCOUNT_SUSPENDED",
                        "message": "This account is suspended.",
                    },
                    "request_id": getattr(request, "request_id", ""),
                },
                status=403,
            )
        # last_seen activity heartbeat — at most one write per 5 minutes.
        if user is not None and user.is_authenticated:
            from django.contrib.auth import get_user_model
            from django.utils import timezone as _tz

            now = _tz.now()
            if (
                user.last_seen_at is None
                or (now - user.last_seen_at).total_seconds() > 300
            ):
                get_user_model().objects.filter(pk=user.pk).update(
                    last_seen_at=now
                )
        return self.get_response(request)
