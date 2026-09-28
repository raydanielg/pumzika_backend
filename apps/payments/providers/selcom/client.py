"""Selcom HTTP client — auth headers, timeouts, error mapping.

No booking/business logic lives here. Credentials come from settings (env);
they are never logged, never returned in errors.
"""
from __future__ import annotations

import logging
from typing import Mapping

import requests
from django.conf import settings

from ..base import (
    InvalidRequest,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .authentication import auth_headers

logger = logging.getLogger("pumzika.payments.selcom")

DEFAULT_TIMEOUT = (5, 20)  # (connect, read) seconds — never hang forever


def _config() -> dict:
    return {
        "base_url": getattr(settings, "SELCOM_BASE_URL",
                            "https://apigw.selcommobile.com").rstrip("/"),
        "api_key": getattr(settings, "SELCOM_API_KEY", ""),
        "api_secret": getattr(settings, "SELCOM_API_SECRET", ""),
        "vendor_id": getattr(settings, "SELCOM_VENDOR_ID", ""),
        "webhook_url": getattr(settings, "SELCOM_WEBHOOK_URL", ""),
        "timeout": getattr(settings, "SELCOM_TIMEOUT", DEFAULT_TIMEOUT),
    }


def _redact(params: Mapping) -> dict:
    """Strip anything that must never appear in logs."""
    hidden = {"pin", "cvv", "card_number", "api_secret"}
    return {k: ("***" if k.lower() in hidden else v) for k, v in params.items()}


class SelcomClient:
    """Thin, signed HTTP wrapper around Selcom's API gateway."""

    def __init__(self, session: requests.Session | None = None):
        cfg = _config()
        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]
        self.api_secret = cfg["api_secret"]
        self.vendor_id = cfg["vendor_id"]
        self.webhook_url = cfg["webhook_url"]
        self.timeout = cfg["timeout"]
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.vendor_id)

    def request(self, method: str, path: str, parameters: Mapping,
                signed_fields: list[str]) -> dict:
        """Signed request → parsed JSON. Raises typed ProviderErrors."""
        if not self.configured:
            raise ProviderUnavailable("Selcom is not configured.")
        url = f"{self.base_url}{path}"
        headers = auth_headers(self.api_key, self.api_secret, parameters,
                               signed_fields)
        try:
            resp = self.session.request(
                method.upper(), url, json=dict(parameters), headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.warning("selcom timeout %s %s", method, path)
            raise ProviderTimeout() from exc
        except requests.RequestException as exc:
            logger.warning("selcom unreachable %s %s: %s", method, path,
                           type(exc).__name__)
            raise ProviderUnavailable() from exc

        # Log the response safely — no secrets, no raw payload at INFO.
        logger.info(
            "selcom %s %s -> %s", method, path, resp.status_code,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderUnavailable(
                f"Selcom returned a non-JSON response (HTTP {resp.status_code})"
            ) from exc

        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Selcom error (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            # map 4xx to a safe internal error — never echo raw provider body
            raise InvalidRequest(
                str(payload.get("message", "Selcom rejected the request"))
            )
        return payload
