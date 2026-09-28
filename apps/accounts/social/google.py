"""Google Sign-In — ID token verification via Google's JWKS."""
from __future__ import annotations

from django.conf import settings

from .base import SocialAuthError, VerifiedIdentity, verify_jwt_via_jwks

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


def google_audiences() -> list[str]:
    """All client IDs this deployment accepts — web + Android + iOS."""
    ids = [
        getattr(settings, "GOOGLE_WEB_CLIENT_ID", ""),
        getattr(settings, "GOOGLE_ANDROID_CLIENT_ID", ""),
        getattr(settings, "GOOGLE_IOS_CLIENT_ID", ""),
        getattr(settings, "GOOGLE_CLIENT_ID", ""),  # legacy single value
    ]
    return [i for i in ids if i]


class GoogleProvider:
    code = "GOOGLE"

    def verify(self, credential: str, extra: dict | None = None) -> VerifiedIdentity:
        audiences = google_audiences()
        if not audiences:
            raise SocialAuthError(
                "Google sign-in is not configured.",
                code="PROVIDER_NOT_CONFIGURED",
            )
        claims = verify_jwt_via_jwks(
            credential, GOOGLE_JWKS_URL,
            audiences=audiences, issuers=GOOGLE_ISSUERS,
        )
        sub = claims.get("sub")
        if not sub:
            raise SocialAuthError(code="TOKEN_INVALID")
        return VerifiedIdentity(
            provider=self.code,
            provider_user_id=sub,
            email=(claims.get("email") or "").lower() or None,
            email_verified=bool(claims.get("email_verified")),
            first_name=claims.get("given_name", "") or "",
            last_name=claims.get("family_name", "") or "",
            raw_claims=claims,
        )
