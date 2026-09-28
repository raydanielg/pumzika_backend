"""Provider registry — business logic resolves providers by code only."""
from __future__ import annotations

from .base import (
    InitiationResult,
    InvalidRequest,
    PaymentFailedByProvider,
    PaymentProviderInterface,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    VerificationFailed,
    WebhookData,
)
from .mock import MockProvider, mock_webhook_signature
from .selcom import SelcomProvider

_PROVIDER_REGISTRY: dict[str, type] = {
    MockProvider.code: MockProvider,
    SelcomProvider.code: SelcomProvider,
}


def register_provider(cls: type) -> None:
    _PROVIDER_REGISTRY[cls.code] = cls


def get_provider(code: str) -> PaymentProviderInterface:
    try:
        return _PROVIDER_REGISTRY[code]()
    except KeyError as exc:
        raise ProviderError(f"Provider '{code}' is not implemented.") from exc


__all__ = [
    "InitiationResult",
    "InvalidRequest",
    "MockProvider",
    "PaymentFailedByProvider",
    "PaymentProviderInterface",
    "ProviderError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "SelcomProvider",
    "VerificationFailed",
    "WebhookData",
    "get_provider",
    "mock_webhook_signature",
    "register_provider",
]
