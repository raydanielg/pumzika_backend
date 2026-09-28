"""Social identity verification — provider-neutral.

Each provider verifies its credential into a `VerifiedIdentity`; the resolver
turns that into a Pumzika user. Providers never touch the User model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import jwt as pyjwt
from django.conf import settings


class SocialAuthError(Exception):
    """Provider credential could not be verified — safe message only."""

    code = "SOCIAL_AUTH_FAILED"

    def __init__(self, message: str = "Authentication could not be completed.",
                 code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


@dataclass
class VerifiedIdentity:
    """What the backend trusts after provider verification."""

    provider: str
    provider_user_id: str          # stable `sub` — never email
    email: str | None
    email_verified: bool
    first_name: str = ""
    last_name: str = ""
    raw_claims: dict | None = None


class SocialProviderInterface(Protocol):
    code: str  # "GOOGLE" | "APPLE"

    def verify(self, credential: str, extra: dict | None = None) -> VerifiedIdentity: ...


def verify_jwt_via_jwks(token: str, jwks_url: str, *, audiences: list[str],
                        issuers: list[str]) -> dict:
    """Verify a provider ID token: signature + iss + aud + exp.

    `decode()` without verification is never acceptable — this uses the
    provider's public JWKS and validates all standard claims.
    """
    try:
        jwks = pyjwt.PyJWKClient(jwks_url, cache_keys=True)
        signing_key = jwks.get_signing_key_from_jwt(token).key
        claims = pyjwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audiences,
            issuer=issuers,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise SocialAuthError("Credential has expired.",
                              code="TOKEN_EXPIRED") from exc
    except pyjwt.InvalidAudienceError as exc:
        raise SocialAuthError("Credential audience mismatch.",
                              code="TOKEN_AUDIENCE_INVALID") from exc
    except pyjwt.InvalidIssuerError as exc:
        raise SocialAuthError("Credential issuer mismatch.",
                              code="TOKEN_ISSUER_INVALID") from exc
    except pyjwt.PyJWTError as exc:
        raise SocialAuthError(code="TOKEN_INVALID") from exc
    except Exception as exc:
        raise SocialAuthError(code="PROVIDER_UNAVAILABLE") from exc
    return claims
