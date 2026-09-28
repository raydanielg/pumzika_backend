"""Custom user model, host profiles, role permissions, verification codes."""
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.common.validators import secure_upload_to


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("role", User.Role.SUPER_ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_email_verified", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    class Role(models.TextChoices):
        GUEST = "GUEST", "Guest"
        HOST = "HOST", "Host"
        STAFF = "STAFF", "Staff"
        ADMIN = "ADMIN", "Admin"
        SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    avatar = models.ImageField(upload_to=secure_upload_to("avatars"), null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.GUEST, db_index=True)
    country = models.ForeignKey(
        "locations.Country", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="users",
    )
    preferred_language = models.CharField(max_length=10, default="en")
    preferred_currency = models.CharField(max_length=3, default="TZS")
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(default=False)  # Django admin-site access
    deleted_at = models.DateTimeField(null=True, blank=True)

    class AccountStatus(models.TextChoices):
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending Verification"
        ACTIVE = "ACTIVE", "Active"
        RESTRICTED = "RESTRICTED", "Restricted"
        SUSPENDED = "SUSPENDED", "Suspended"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    account_status = models.CharField(
        max_length=20, choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE, db_index=True,
    )
    suspension_reason = models.TextField(blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="suspensions_issued",
    )
    suspension_until = models.DateTimeField(
        null=True, blank=True, help_text="NULL = indefinite"
    )
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    known_ips = models.JSONField(
        default=list, blank=True,
        help_text="Capped list of previously seen IPs — new IP = risk signal",
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_staff_role(self) -> bool:
        return self.role in {self.Role.STAFF, self.Role.ADMIN, self.Role.SUPER_ADMIN}

    def has_perm_code(self, code: str) -> bool:
        """Granular permission check resolved through the user's role."""
        if self.is_superuser or self.role == self.Role.SUPER_ADMIN:
            return True
        if not hasattr(self, "_perm_codes"):
            self._perm_codes = set(
                RolePermission.objects.filter(role=self.role).values_list("code", flat=True)
            )
        return code in self._perm_codes

    def deactivate(self) -> None:
        self.is_active = False
        self.account_status = self.AccountStatus.DEACTIVATED
        self.save(update_fields=["is_active", "account_status", "updated_at"])

    @property
    def is_access_blocked(self) -> bool:
        # PENDING_VERIFICATION users may still log in — capability gates
        # (booking, payout) enforce verification separately.
        return self.account_status in (
            self.AccountStatus.SUSPENDED, self.AccountStatus.DEACTIVATED,
        ) or not self.is_active or self.deleted_at is not None

    def has_restriction(self, capability: str) -> bool:
        """True when an unexpired, unrevoked restriction covers `capability`."""
        return self.restrictions.filter(
            capability=capability,
            revoked_at__isnull=True,
        ).filter(
            models.Q(expires_at__isnull=True)
            | models.Q(expires_at__gt=timezone.now())
        ).exists()

    def soft_delete(self) -> None:
        """Deactivate + anonymise PII while preserving financial/booking history."""
        self.is_active = False
        self.account_status = self.AccountStatus.DEACTIVATED
        self.deleted_at = timezone.now()
        anonym = self.id.hex[:8]
        self.email = f"deleted-{anonym}@pumzika.invalid"
        self.phone = None
        self.first_name = "Deleted"
        self.last_name = "User"
        self.avatar = None
        self.is_email_verified = False
        self.is_phone_verified = False
        self.save()


class RolePermission(TimeStampedModel):
    """Maps a role to a permission code — database-driven authorization."""

    role = models.CharField(max_length=20, choices=User.Role.choices, db_index=True)
    code = models.CharField(max_length=64, db_index=True)

    class Meta:
        unique_together = ("role", "code")

    def __str__(self) -> str:
        return f"{self.role}:{self.code}"


class HostProfile(TimeStampedModel):
    """Extra data + metrics for users who host properties."""

    class HostingStatus(models.TextChoices):
        INACTIVE = "INACTIVE", "Inactive"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Unverified"
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="host_profile")
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    profile_photo = models.ImageField(upload_to=secure_upload_to("hosts"), null=True, blank=True)
    hosting_status = models.CharField(
        max_length=20, choices=HostingStatus.choices, default=HostingStatus.ACTIVE
    )
    verification_status = models.CharField(
        max_length=20, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    response_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    response_time_minutes = models.PositiveIntegerField(default=0)
    total_properties = models.PositiveIntegerField(default=0)
    total_bookings = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["verification_status", "hosting_status"])]

    def __str__(self) -> str:
        return f"Host({self.user.email})"

    @property
    def can_publish(self) -> bool:
        return (
            self.hosting_status == self.HostingStatus.ACTIVE
            and self.verification_status == self.VerificationStatus.VERIFIED
        )


class SocialAccount(TimeStampedModel):
    """External identity (Google/Apple) linked to a Pumzika user.

    Identity is (provider, provider_user_id) — never email alone, since
    email changes and Apple private-relay addresses are not stable keys.
    """

    class Provider(models.TextChoices):
        GOOGLE = "GOOGLE", "Google"
        APPLE = "APPLE", "Apple"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="social_accounts"
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_user_id = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(blank=True)
    email_verified = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_user_id"],
                name="unique_social_identity",
            )
        ]
        indexes = [models.Index(fields=["user", "provider"])]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_user_id[:12]}…"


class UserRestriction(TimeStampedModel):
    """Capability-specific restriction — finer than full suspension.

    e.g. a user may keep browsing but lose BOOKING, or keep their account
    but lose PAYOUT while a fraud review is open.
    """

    class Capability(models.TextChoices):
        BOOKING = "BOOKING", "Booking"
        HOSTING = "HOSTING", "Hosting"
        PAYOUT = "PAYOUT", "Payout"
        MESSAGING = "MESSAGING", "Messaging"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="restrictions"
    )
    capability = models.CharField(max_length=20, choices=Capability.choices)
    reason = models.TextField()
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="restrictions_issued",
    )
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="NULL = indefinite"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="restrictions_revoked",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "capability", "revoked_at"])]


class VerificationCode(TimeStampedModel):
    """OTP codes for email/phone verification and password reset.

    Codes are stored hashed — the plain value only exists in the outbound
    notification.
    """

    class Purpose(models.TextChoices):
        EMAIL_VERIFY = "EMAIL_VERIFY"
        PHONE_VERIFY = "PHONE_VERIFY"
        PASSWORD_RESET = "PASSWORD_RESET"

    TTL_MINUTES = 15
    MAX_ATTEMPTS = 5

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="verification_codes")
    purpose = models.CharField(max_length=20, choices=Purpose.choices, db_index=True)
    target = models.CharField(max_length=255)  # email or phone the code was sent to
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "expires_at"])]

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def is_valid(self, code: str) -> bool:
        return (
            self.consumed_at is None
            and self.attempts < self.MAX_ATTEMPTS
            and self.expires_at > timezone.now()
            and self.code_hash == self.hash_code(code)
        )

    def mark_consumed(self) -> None:
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at", "updated_at"])

    @classmethod
    def issue(cls, user: User, purpose: str, target: str, code: str) -> "VerificationCode":
        return cls.objects.create(
            user=user,
            purpose=purpose,
            target=target,
            code_hash=cls.hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=cls.TTL_MINUTES),
        )
