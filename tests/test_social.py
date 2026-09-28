"""Social auth tests — verify-then-resolve; no client-supplied claims trusted."""
import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings

from apps.accounts.models import SocialAccount, User
from apps.accounts.social import link, login, unlink
from apps.accounts.social.base import SocialAuthError
from apps.common.exceptions import BusinessError

from .base import BaseTestCase

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(sub="google-sub-1", aud="web-client", iss="https://accounts.google.com",
           email="social@example.com", email_verified=True, exp_in=3600,
           **claims):
    payload = {
        "sub": sub, "iss": iss, "aud": aud,
        "exp": int(time.time()) + exp_in, "iat": int(time.time()),
        "email": email, "email_verified": email_verified,
        "given_name": "Social", "family_name": "User", **claims,
    }
    return pyjwt.encode(payload, _KEY, algorithm="RS256")


def _mock_jwks(token):
    """Patch PyJWKClient so verification resolves our test signing key."""
    key = MagicMock()
    key.key = _KEY.public_key()
    return patch(
        "jwt.PyJWKClient",
        return_value=MagicMock(get_signing_key_from_jwt=lambda t: key),
    )


@override_settings(GOOGLE_WEB_CLIENT_ID="web-client",
                   GOOGLE_ANDROID_CLIENT_ID="android-client",
                   APPLE_CLIENT_ID="app.pumzika.ios")
class GoogleLoginTests(BaseTestCase):
    def test_new_user_created(self):
        with _mock_jwks(None):
            user, is_new = login(_token(), "GOOGLE")
        assert is_new
        assert user.email == "social@example.com"
        assert user.is_email_verified
        assert SocialAccount.objects.get(
            provider="GOOGLE", provider_user_id="google-sub-1"
        ).user == user

    def test_existing_identity_logs_in(self):
        with _mock_jwks(None):
            user1, _ = login(_token(), "GOOGLE")
            user2, is_new = login(_token(), "GOOGLE")
        assert user2.id == user1.id
        assert not is_new
        assert SocialAccount.objects.count() == 1

    def test_verified_email_links_existing_user(self):
        existing = User.objects.create_user(
            email="social@example.com", first_name="A", last_name="B",
            password="Pass123!x", is_email_verified=True,
        )
        with _mock_jwks(None):
            user, is_new = login(_token(), "GOOGLE")
        assert user.id == existing.id
        assert not is_new
        assert SocialAccount.objects.get(user=existing).provider == "GOOGLE"

    def test_unverified_email_does_not_link(self):
        User.objects.create_user(
            email="social@example.com", first_name="A", last_name="B",
            password="Pass123!x", is_email_verified=True,
        )
        with _mock_jwks(None):
            user, is_new = login(_token(email_verified=False), "GOOGLE")
        # Unverified email must never merge onto the existing account —
        # the new user gets a placeholder email instead of colliding.
        assert is_new
        assert user.email.endswith("@social.pumzika.invalid")

    def test_wrong_audience_rejected(self):
        with _mock_jwks(None), self.assertRaises(SocialAuthError) as ctx:
            login(_token(aud="evil-client"), "GOOGLE")
        assert ctx.exception.code == "TOKEN_AUDIENCE_INVALID"

    def test_wrong_issuer_rejected(self):
        with _mock_jwks(None), self.assertRaises(SocialAuthError) as ctx:
            login(_token(iss="https://evil.example.com"), "GOOGLE")
        assert ctx.exception.code == "TOKEN_ISSUER_INVALID"

    def test_expired_token_rejected(self):
        with _mock_jwks(None), self.assertRaises(SocialAuthError) as ctx:
            login(_token(exp_in=-10), "GOOGLE")
        assert ctx.exception.code == "TOKEN_EXPIRED"

    def test_android_audience_accepted(self):
        with _mock_jwks(None):
            user, _ = login(_token(sub="android-sub", aud="android-client",
                                   email="android@x.com"), "GOOGLE")
        assert SocialAccount.objects.filter(
            provider_user_id="android-sub").exists()


@override_settings(GOOGLE_WEB_CLIENT_ID="web-client",
                   APPLE_CLIENT_ID="app.pumzika.ios")
class AppleLoginTests(BaseTestCase):
    def _apple_token(self, **kw):
        return _token(iss="https://appleid.apple.com", aud="app.pumzika.ios",
                      **kw)

    def test_private_relay_email_accepted(self):
        with _mock_jwks(None):
            user, is_new = login(
                self._apple_token(
                    sub="apple-sub-1",
                    email="xyz@privaterelay.appleid.com",
                    email_verified="true",
                ),
                "APPLE",
            )
        assert is_new
        assert user.email == "xyz@privaterelay.appleid.com"

    def test_no_email_uses_placeholder(self):
        with _mock_jwks(None):
            user, _ = login(self._apple_token(sub="apple-noemail", email=None),
                            "APPLE")
        assert user.email.endswith("@social.pumzika.invalid")

    def test_first_login_name_persisted(self):
        with _mock_jwks(None):
            user, _ = login(
                self._apple_token(sub="apple-name"),
                "APPLE", extra={"name": {"firstName": "Kwame",
                                         "lastName": "Otieno"}},
            )
        assert user.first_name == "Kwame"


@override_settings(GOOGLE_WEB_CLIENT_ID="web-client")
class AccountLinkingTests(BaseTestCase):
    def test_link_and_unlink(self):
        with _mock_jwks(None):
            social = link(self.guest, _token(sub="g-link"), "GOOGLE")
        assert social.user == self.guest
        # guest has a usable password → unlink is allowed
        with _mock_jwks(None):
            unlink(self.guest, "GOOGLE")
        assert not SocialAccount.objects.filter(user=self.guest).exists()

    def test_unlink_last_method_blocked(self):
        user = User.objects.create_user(
            email="socialonly@x.com", first_name="A", last_name="B",
            password=None,
        )
        user.set_unusable_password()
        user.save()
        SocialAccount.objects.create(user=user, provider="GOOGLE",
                                     provider_user_id="only-sub")
        with self.assertRaises(BusinessError) as ctx:
            unlink(user, "GOOGLE")
        assert ctx.exception.code == "LAST_AUTH_METHOD"

    def test_cannot_link_identity_owned_by_other(self):
        other = User.objects.create_user(
            email="other@x.com", first_name="O", last_name="U",
            password="Pass123!x",
        )
        SocialAccount.objects.create(user=other, provider="GOOGLE",
                                     provider_user_id="taken-sub")
        with _mock_jwks(None), self.assertRaises(BusinessError) as ctx:
            link(self.guest, _token(sub="taken-sub"), "GOOGLE")
        assert ctx.exception.code == "IDENTITY_TAKEN"

    def test_suspended_social_user_blocked(self):
        with _mock_jwks(None):
            user, _ = login(_token(sub="susp-sub", email="susp@x.com"),
                            "GOOGLE")
        user.account_status = User.AccountStatus.SUSPENDED
        user.save()
        with _mock_jwks(None), self.assertRaises(BusinessError) as ctx:
            login(_token(sub="susp-sub"), "GOOGLE")
        assert ctx.exception.code == "ACCOUNT_INACTIVE"
