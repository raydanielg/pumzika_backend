"""Authentication and account endpoints."""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

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
    RegisterSerializer,
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
        try:
            user = services.authenticate_user(**serializer.validated_data)
        except Exception:
            audit(actor=None, action="user.login_failed",
                  request=request, metadata={"email": serializer.validated_data.get("email")})
            raise
        audit(actor=user, action="user.login", request=request)
        return Response({"user": UserSerializer(user).data, "tokens": _tokens_for(user)})


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
