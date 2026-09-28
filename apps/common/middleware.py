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
