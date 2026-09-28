"""Consistent API error envelope + domain exceptions.

Every error response looks like::

    {
      "success": false,
      "error": {"code": "PROPERTY_NOT_AVAILABLE", "message": "..."},
      "request_id": "..."
    }
"""
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("pumzika.errors")


class BusinessError(Exception):
    """Raised by services when a business rule is violated.

    ``code`` is a stable machine-readable string, ``http_status`` controls the
    HTTP response code and ``details`` can carry field-level context.
    """

    code = "BUSINESS_RULE_VIOLATION"
    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or "Business rule violation"
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(BusinessError):
    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(BusinessError):
    code = "PERMISSION_DENIED"
    http_status = status.HTTP_403_FORBIDDEN


class ConflictError(BusinessError):
    code = "CONFLICT"
    http_status = status.HTTP_409_CONFLICT


def _request_id(request) -> str:
    return getattr(request, "request_id", "") or ""


def _error_response(
    request, code: str, message: str, http_status: int, details: Any = None
) -> Response:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return Response(
        {
            "success": False,
            "message": message,
            "error": error,
            "request_id": _request_id(request),
        },
        status=http_status,
    )


def envelope_exception_handler(exc, context):
    """Map exceptions to the standard error envelope."""
    request = context.get("request")

    if isinstance(exc, BusinessError):
        return _error_response(request, exc.code, exc.message, exc.http_status, exc.details)

    if isinstance(exc, DjangoValidationError):
        return _error_response(
            request,
            "VALIDATION_ERROR",
            "Validation failed",
            status.HTTP_400_BAD_REQUEST,
            getattr(exc, "message_dict", {"detail": exc.messages}),
        )

    if isinstance(exc, Http404):
        return _error_response(request, "NOT_FOUND", "Resource not found", status.HTTP_404_NOT_FOUND)

    if isinstance(exc, DjangoPermissionDenied):
        return _error_response(request, "PERMISSION_DENIED", str(exc) or "Permission denied", status.HTTP_403_FORBIDDEN)

    response = exception_handler(exc, context)
    if response is not None:
        code = "ERROR"
        message = "Request failed"
        details = None
        data = response.data
        if isinstance(data, dict):
            if "detail" in data:
                message = str(data["detail"])
            else:
                message = "Validation failed"
                details = data
            code = getattr(exc, "default_code", "error")
            code = str(code).upper().replace(" ", "_")
        elif isinstance(data, list):
            message = "Request failed"
            details = data
        return _error_response(request, code, message, response.status_code, details)

    logger.exception("Unhandled exception", exc_info=exc)
    return _error_response(
        request, "INTERNAL_ERROR", "An unexpected error occurred", status.HTTP_500_INTERNAL_SERVER_ERROR
    )
