"""Account serializers — never expose sensitive flags publicly."""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import HostProfile, User


class SocialLoginSerializer(serializers.Serializer):
    """Google: `credential` (id_token). Apple: `identity_token` + optional
    first-login profile data forwarded once by the client."""

    credential = serializers.CharField(required=False)
    identity_token = serializers.CharField(required=False)
    authorization_code = serializers.CharField(required=False, allow_blank=True)
    name = serializers.DictField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("credential") and not attrs.get("identity_token"):
            raise serializers.ValidationError(
                "credential or identity_token is required."
            )
        return attrs

    @property
    def token(self) -> str:
        return self.validated_data.get("credential") or self.validated_data.get(
            "identity_token"
        )


class SocialLinkSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["GOOGLE", "APPLE"])
    credential = serializers.CharField(required=False)
    identity_token = serializers.CharField(required=False)

    def validate(self, attrs):
        if not attrs.get("credential") and not attrs.get("identity_token"):
            raise serializers.ValidationError(
                "credential or identity_token is required."
            )
        return attrs

    @property
    def token(self) -> str:
        return self.validated_data.get("credential") or self.validated_data.get(
            "identity_token"
        )


class SocialAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    provider = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    email_verified = serializers.BooleanField()
    last_login_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=[User.Role.GUEST, User.Role.HOST], default=User.Role.GUEST
    )

    def validate_password(self, value):
        validate_password(value)
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "phone", "first_name", "last_name", "full_name",
            "avatar", "date_of_birth", "role", "country",
            "preferred_language", "preferred_currency",
            "is_email_verified", "is_phone_verified",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "email", "role", "is_email_verified",
            "is_phone_verified", "created_at", "updated_at",
        ]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "avatar", "date_of_birth",
            "preferred_language", "preferred_currency", "country", "phone",
        ]
        extra_kwargs = {f: {"required": False} for f in fields}


class PublicHostProfileSerializer(serializers.ModelSerializer):
    """Public-facing host card — no email, phone, KYC or financial data."""

    member_since = serializers.DateTimeField(source="user.date_joined",
                                             read_only=True)
    display_first_name = serializers.CharField(source="user.first_name",
                                               read_only=True)

    class Meta:
        model = HostProfile
        fields = [
            "id", "display_name", "display_first_name", "bio",
            "profile_photo", "rating", "response_rate",
            "response_time_minutes", "total_properties", "member_since",
        ]
        read_only_fields = fields


class HostProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = HostProfile
        fields = [
            "id", "user_email", "display_name", "bio", "profile_photo",
            "hosting_status", "verification_status", "rating",
            "response_rate", "response_time_minutes",
            "total_properties", "total_bookings",
        ]
        read_only_fields = [
            "id", "hosting_status", "verification_status", "rating",
            "response_rate", "response_time_minutes",
            "total_properties", "total_bookings",
        ]


class VerifyCodeSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=10)


class PhoneVerifyRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=10)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class AccountDeleteSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
