"""SocialAuthService — provider credential → Pumzika session.

    POST /auth/social/<provider>/
            │
    SocialAuthService
            │
    GoogleProvider / AppleProvider   (verify credential, never trust client)
            │
    AccountResolver                  (find / link / create — transactional)
            │
    Pumzika User + JWT tokens
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import BusinessError

from ..models import SocialAccount, User
from .apple import AppleProvider
from .base import SocialAuthError, VerifiedIdentity
from .google import GoogleProvider

_PROVIDERS = {
    GoogleProvider.code: GoogleProvider,
    AppleProvider.code: AppleProvider,
}


def _provider(code: str):
    try:
        return _PROVIDERS[code.upper()]()
    except KeyError as exc:
        raise SocialAuthError(
            f"Provider '{code}' is not supported.", code="PROVIDER_UNKNOWN"
        ) from exc


def _placeholder_email(provider: str, sub: str) -> str:
    """Fallback email when the provider shares none (e.g. hidden Apple email)."""
    return f"{provider.lower()}-{sub[:20]}@social.pumzika.invalid"


@transaction.atomic
def resolve_identity(identity: VerifiedIdentity) -> tuple[User, bool]:
    """Find or create the Pumzika user for a verified identity.

    Returns (user, is_new_user). Linking to an existing account only happens
    when the provider asserts a *verified* email that matches — an unverified
    email never merges accounts (account-takeover guard).
    """
    # Step 1 — known social identity → existing user.
    social = (
        SocialAccount.objects.select_for_update()
        .select_related("user")
        .filter(provider=identity.provider,
                provider_user_id=identity.provider_user_id)
        .first()
    )
    if social is not None:
        social.last_login_at = timezone.now()
        social.email = identity.email or social.email
        social.email_verified = identity.email_verified or social.email_verified
        social.save(update_fields=["last_login_at", "email",
                                   "email_verified", "updated_at"])
        return social.user, False

    # Step 2 — verified-email match → link onto that account.
    user = None
    if identity.email and identity.email_verified:
        user = User.objects.select_for_update().filter(
            email__iexact=identity.email,
        ).first()

    # Step 3 — create a new user. If the provider email is unverified AND
    # already taken, don't merge OR collide — mint a placeholder instead.
    is_new = user is None
    if is_new:
        email = identity.email
        if email and User.objects.filter(email__iexact=email).exists():
            email = _placeholder_email(identity.provider,
                                       identity.provider_user_id)
        user = User.objects.create_user(
            email=email or _placeholder_email(
                identity.provider, identity.provider_user_id
            ),
            first_name=identity.first_name or "Pumzika",
            last_name=identity.last_name or "User",
            is_email_verified=bool(identity.email and identity.email_verified),
            password=None,
        )
        user.set_unusable_password()
        user.save(update_fields=["password", "updated_at"])

    SocialAccount.objects.create(
        user=user,
        provider=identity.provider,
        provider_user_id=identity.provider_user_id,
        email=identity.email or "",
        email_verified=identity.email_verified,
        last_login_at=timezone.now(),
    )
    return user, is_new


def login(credential: str, provider: str, extra: dict | None = None,
          request=None) -> tuple[User, bool]:
    """Verify → resolve → enforce account status. Returns (user, is_new)."""
    identity = _provider(provider).verify(credential, extra)
    user, is_new = resolve_identity(identity)
    _assert_active(user)
    _record_login(user, provider, request)
    return user, is_new


def link(user: User, credential: str, provider: str,
         extra: dict | None = None, request=None) -> SocialAccount:
    """Attach a verified social identity to an *authenticated* account —
    ownership is proven by the session, not by a matching email."""
    identity = _provider(provider).verify(credential, extra)
    with transaction.atomic():
        if SocialAccount.objects.filter(
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
        ).exclude(user=user).exists():
            raise BusinessError(
                "This identity is already linked to another account.",
                code="IDENTITY_TAKEN",
            )
        social, created = SocialAccount.objects.get_or_create(
            user=user, provider=identity.provider,
            defaults={
                "provider_user_id": identity.provider_user_id,
                "email": identity.email or "",
                "email_verified": identity.email_verified,
            },
        )
        if not created and social.provider_user_id != identity.provider_user_id:
            raise BusinessError(
                "A different identity is already linked for this provider.",
                code="IDENTITY_CONFLICT",
            )
    return social


def unlink(user: User, provider: str, request=None) -> None:
    """Remove a linked identity — never the user's last auth method."""
    social = SocialAccount.objects.filter(user=user, provider=provider).first()
    if social is None:
        raise BusinessError("This identity is not linked.",
                            code="IDENTITY_NOT_LINKED")
    has_password = user.has_usable_password()
    other_social = SocialAccount.objects.filter(user=user).exclude(
        pk=social.pk).exists()
    if not has_password and not other_social:
        raise BusinessError(
            "Set a password or link another provider before removing this "
            "sign-in method.",
            code="LAST_AUTH_METHOD",
        )
    social.delete()


def _assert_active(user: User) -> None:
    from apps.security.services import auto_lift_suspension

    auto_lift_suspension(user)
    if user.is_access_blocked:
        raise BusinessError("This account is not active.",
                            code="ACCOUNT_INACTIVE", http_status=403)


def _record_login(user: User, provider: str, request) -> None:
    try:
        from apps.security.services import record_event
        from apps.security.models import SecurityEvent

        record_event(SecurityEvent.Type.LOGIN_SUCCESS, user=user,
                     request=request, metadata={"provider": provider})
    except Exception:
        pass
