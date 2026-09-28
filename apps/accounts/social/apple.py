"""Sign in with Apple — identity_token verification via Apple's JWKS."""
from __future__ import annotations

from django.conf import settings

from .base import SocialAuthError, VerifiedIdentity, verify_jwt_via_jwks

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = ["https://appleid.apple.com"]


class AppleProvider:
    code = "APPLE"

    def verify(self, credential: str, extra: dict | None = None) -> VerifiedIdentity:
        client_id = getattr(settings, "APPLE_CLIENT_ID", "")
        if not client_id:
            raise SocialAuthError(
                "Apple sign-in is not configured.",
                code="PROVIDER_NOT_CONFIGURED",
            )
        claims = verify_jwt_via_jwks(
            credential, APPLE_JWKS_URL,
            audiences=[client_id], issuers=APPLE_ISSUER,
        )
        sub = claims.get("sub")
        if not sub:
            raise SocialAuthError(code="TOKEN_INVALID")

        # Apple only sends name/email on the *first* authorization — the
        # client may forward it once; we persist whatever arrives now and
        # never depend on it appearing again.
        extra = extra or {}
        first = extra.get("first_name", "") or ""
        last = extra.get("last_name", "") or ""
        name = extra.get("name") or {}
        if isinstance(name, dict):
            first = first or name.get("firstName", "") or ""
            last = last or name.get("lastName", "") or ""

        return VerifiedIdentity(
            provider=self.code,
            provider_user_id=sub,
            # Apple private-relay emails are valid — do not reject them.
            email=(claims.get("email") or "").lower() or None,
            email_verified=claims.get("email_verified") in (True, "true"),
            first_name=first,
            last_name=last,
            raw_claims=claims,
        )
