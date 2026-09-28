"""Authentication and account endpoints."""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.common.exceptions import BusinessError
from apps.common.throttles import AuthRateThrottle, StrictAuthRateThrottle
from apps.admin_panel.services import audit

from . import services
from .models import HostProfile
from .serializers import (
    AccountDeleteSerializer,
    HostProfileSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PhoneVerifyRequestSerializer,
    ProfileUpdateSerializer,
    PublicHostProfileSerializer,
    RegisterSerializer,
    SocialAccountSerializer,
    SocialLinkSerializer,
    SocialLoginSerializer,
    UserSerializer,
    VerifyCodeSerializer,
)


def _tokens_for(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        audit(actor=user, action="user.registered", target=user, request=request)
        return Response(
            {"user": UserSerializer(user).data, "tokens": _tokens_for(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        from apps.security import services as security_services

        if security_services.is_login_locked(email):
            raise BusinessError(
                "Too many failed attempts. Try again later.",
                code="ACCOUNT_LOCKED", http_status=429,
            )
        try:
            user = services.authenticate_user(**serializer.validated_data)
        except Exception:
            security_services.record_login_failure(email, request)
            audit(actor=None, action="user.login_failed",
                  request=request, metadata={"email": email})
            raise
        security_services.record_login_success(user, request)
        audit(actor=user, action="user.login", request=request)
        return Response({"user": UserSerializer(user).data, "tokens": _tokens_for(user)})


class SocialLoginView(APIView):
    """POST /api/v1/auth/social/<provider>/ — Google/Apple sign-in."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = SocialLoginSerializer

    def post(self, request, provider: str):
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.accounts.social import login as social_login
        from apps.security import services as security_services

        extra = {k: serializer.validated_data[k]
                 for k in ("name", "first_name", "last_name")
                 if k in serializer.validated_data}
        try:
            user, is_new = social_login(
                serializer.token, provider, extra=extra, request=request
            )
        except Exception:
            from apps.security.models import SecurityEvent

            security_services.record_event(
                SecurityEvent.Type.LOGIN_FAILED, request=request,
                metadata={"provider": provider.upper()})
            raise
        audit(actor=user, action=f"user.social_login:{provider.lower()}",
              request=request)
        return Response({
            "user": UserSerializer(user).data,
            "tokens": _tokens_for(user),
            "is_new_user": is_new,
        })


class SocialLinkView(APIView):
    """POST /api/v1/auth/social/link/ — attach a provider to the session user."""

    permission_classes = [IsAuthenticated]
    serializer_class = SocialLinkSerializer

    def post(self, request):
        serializer = SocialLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.accounts.social import link

        extra = {k: serializer.validated_data[k]
                 for k in ("first_name", "last_name")
                 if k in serializer.validated_data}
        social = link(
            request.user, serializer.token,
            serializer.validated_data["provider"], extra=extra,
            request=request,
        )
        audit(actor=request.user,
              action=f"user.social_linked:{social.provider.lower()}",
              target=social, request=request)
        return Response(SocialAccountSerializer(social).data,
                        status=status.HTTP_201_CREATED)


class SocialAccountsView(generics.ListAPIView):
    """GET /api/v1/auth/social/accounts/ — linked identities."""

    permission_classes = [IsAuthenticated]
    serializer_class = SocialAccountSerializer

    def get_queryset(self):
        from .models import SocialAccount

        return SocialAccount.objects.filter(user=self.request.user)


class SocialUnlinkView(APIView):
    """DELETE /api/v1/auth/social/link/<provider>/"""

    permission_classes = [IsAuthenticated]
    serializer_class = SocialLinkSerializer  # docs only

    def delete(self, request, provider: str):
        from apps.accounts.social import unlink

        unlink(request.user, provider.upper(), request=request)
        audit(actor=request.user,
              action=f"user.social_unlinked:{provider.lower()}",
              request=request)
        return Response({"detail": "Identity unlinked."})


class PublicHostProfileView(generics.RetrieveAPIView):
    """GET /api/v1/users/hosts/<id>/ — safe public host card.

    Never exposes email, phone, KYC, financials or security data.
    """

    permission_classes = [AllowAny]
    serializer_class = PublicHostProfileSerializer

    def get_queryset(self):
        return HostProfile.objects.select_related("user").filter(
            hosting_status=HostProfile.HostingStatus.ACTIVE
        )


class RefreshView(TokenRefreshView):
    """POST /api/v1/auth/refresh/"""


class LogoutView(APIView):
    """Blacklist the refresh token — server-side invalidation."""

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = RefreshToken(serializer.validated_data["refresh"])
        token.blacklist()
        try:
            from apps.security.services import record_event
            from apps.security.models import SecurityEvent

            record_event(SecurityEvent.Type.TOKEN_REVOKED, user=request.user,
                         request=request)
        except Exception:
            pass
        audit(actor=request.user, action="user.logout", request=request)
        return Response({"detail": "Logged out."})


class EmailVerifySendView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = VerifyCodeSerializer  # docs only; request body is empty

    def post(self, request):
        services.send_email_verification(request.user)
        return Response({"detail": "Verification code sent."})


class EmailVerifyConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = VerifyCodeSerializer

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_email_verification(request.user, serializer.validated_data["code"])
        audit(actor=request.user, action="user.email_verified", request=request)
        return Response({"detail": "Email verified."})


class PhoneVerifySendView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = PhoneVerifyRequestSerializer

    def post(self, request):
        serializer = PhoneVerifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.send_phone_verification(request.user, serializer.validated_data["phone"])
        return Response({"detail": "Verification code sent."})


class PhoneVerifyConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = VerifyCodeSerializer

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_phone_verification(request.user, serializer.validated_data["code"])
        audit(actor=request.user, action="user.phone_verified", request=request)
        return Response({"detail": "Phone verified."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = PasswordResetRequestSerializer

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"])
        # Deliberately identical response whether the account exists or not.
        return Response({"detail": "If the account exists, a reset code was sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [StrictAuthRateThrottle]
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.confirm_password_reset(data["email"], data["code"], data["new_password"])
        return Response({"detail": "Password updated."})


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.change_password(request.user, data["old_password"], data["new_password"])
        audit(actor=request.user, action="user.password_changed", request=request)
        return Response({"detail": "Password changed."})


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return ProfileUpdateSerializer
        return UserSerializer

    def perform_update(self, serializer):
        services.update_profile(self.request.user, **serializer.validated_data)


class MeDeactivateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDeleteSerializer

    def post(self, request):
        services.deactivate_account(request.user)
        audit(actor=request.user, action="user.deactivated", request=request)
        return Response({"detail": "Account deactivated."})


class MeDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDeleteSerializer

    def post(self, request):
        serializer = AccountDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.delete_account(request.user, serializer.validated_data["password"])
        audit(actor=request.user, action="user.deleted", request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionListView(APIView):
    """Active login sessions — one row per outstanding refresh token."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer  # docs hint only

    def get(self, request):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        current_jti = getattr(
            getattr(request, "auth", None), "get", lambda *_: None
        )("jti")
        sessions = OutstandingToken.objects.filter(
            user=request.user
        ).exclude(
            blacklistedtoken__isnull=False
        ).order_by("-created_at")
        data = [{
            "jti": t.jti,
            "created_at": t.created_at,
            "expires_at": t.expires_at,
            "is_current": t.jti == current_jti,
        } for t in sessions]
        return Response(data)


class SessionRevokeView(APIView):
    """Revoke a session by its refresh-token jti (or all but current)."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def post(self, request, jti=None):
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken,
        )

        qs = OutstandingToken.objects.filter(user=request.user)
        if jti:
            qs = qs.filter(jti=jti)
        else:  # revoke-all keeps the current session alive
            current_jti = getattr(
                getattr(request, "auth", None), "get", lambda *_: None
            )("jti")
            if current_jti:
                qs = qs.exclude(jti=current_jti)
        for token in qs:
            BlacklistedToken.objects.get_or_create(token=token)
        audit(actor=request.user,
              action="session.revoked" if jti else "session.revoked_all",
              request=request, metadata={"jti": jti} if jti else None)
        return Response({"detail": "Session(s) revoked."})


class MyHostProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HostProfileSerializer

    def get_object(self):
        profile, _ = HostProfile.objects.get_or_create(
            user=self.request.user,
            defaults={"display_name": self.request.user.full_name},
        )
        return profile
