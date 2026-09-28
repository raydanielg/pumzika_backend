"""Account business logic — registration, verification, passwords, deletion."""
from __future__ import annotations

import secrets

from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import BusinessError, NotFoundError
from apps.common.validators import validate_phone_number

from .models import HostProfile, User, VerificationCode


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _otp_event(user: User, purpose: str) -> None:
    try:
        from apps.security.services import record_event
        from apps.security.models import SecurityEvent

        record_event(SecurityEvent.Type.OTP_FAILED, user=user,
                     metadata={"purpose": purpose})
    except Exception:
        pass


def _dispatch_code(user: User, purpose: str, target: str, code: str) -> None:
    """Queue the OTP for delivery via Celery (never blocks the request)."""
    from apps.notifications.tasks import send_verification_code

    send_verification_code.delay(
        user_id=str(user.id), purpose=purpose, target=target, code=code
    )


@transaction.atomic
def register_user(*, email: str, password: str, first_name: str, last_name: str,
                  phone: str | None = None, role: str = User.Role.GUEST,
                  **extra) -> User:
    if User.objects.filter(email__iexact=email).exists():
        raise BusinessError("An account with this email already exists.", code="EMAIL_TAKEN")
    if phone:
        phone = validate_phone_number(phone)
        if User.objects.filter(phone=phone).exists():
            raise BusinessError("An account with this phone number already exists.",
                                code="PHONE_TAKEN")
    if role not in (User.Role.GUEST, User.Role.HOST):
        role = User.Role.GUEST  # privileged roles are assigned by admins only
    user = User.objects.create_user(
        email=email, password=password, first_name=first_name,
        last_name=last_name, phone=phone or None, role=role,
        account_status=User.AccountStatus.PENDING_VERIFICATION, **extra,
    )
    if role == User.Role.HOST:
        HostProfile.objects.get_or_create(
            user=user, defaults={"display_name": user.full_name}
        )
    send_email_verification(user)
    from apps.notifications.tasks import notify_welcome

    transaction.on_commit(lambda: notify_welcome.delay(str(user.id)))
    return user


def authenticate_user(*, email: str, password: str) -> User:
    user = authenticate(username=email, password=password)
    if user is None:
        raise BusinessError("Invalid credentials.", code="INVALID_CREDENTIALS",
                            http_status=401)
    from apps.security.services import auto_lift_suspension

    auto_lift_suspension(user)
    if user.is_access_blocked:
        raise BusinessError(
            "This account is not active.", code="ACCOUNT_INACTIVE",
            http_status=403,
        )
    return user


def send_email_verification(user: User) -> VerificationCode:
    if user.is_email_verified:
        raise BusinessError("Email is already verified.", code="ALREADY_VERIFIED")
    code = _generate_otp()
    record = VerificationCode.issue(user, VerificationCode.Purpose.EMAIL_VERIFY,
                                    user.email, code)
    _dispatch_code(user, VerificationCode.Purpose.EMAIL_VERIFY, user.email, code)
    return record


def send_phone_verification(user: User, phone: str) -> VerificationCode:
    phone = validate_phone_number(phone)
    code = _generate_otp()
    record = VerificationCode.issue(user, VerificationCode.Purpose.PHONE_VERIFY,
                                    phone, code)
    _dispatch_code(user, VerificationCode.Purpose.PHONE_VERIFY, phone, code)
    return record


def _consume_code(user: User, purpose: str, code: str) -> VerificationCode:
    record = (
        VerificationCode.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if record is None:
        raise BusinessError("No pending verification. Request a new code.",
                            code="NO_PENDING_VERIFICATION")
    if record.attempts >= VerificationCode.MAX_ATTEMPTS:
        _otp_event(user, purpose)
        raise BusinessError("Too many attempts. Request a new code.",
                            code="TOO_MANY_ATTEMPTS")
    if not record.is_valid(code):
        VerificationCode.objects.filter(pk=record.pk).update(attempts=record.attempts + 1)
        _otp_event(user, purpose)
        raise BusinessError("Invalid or expired code.", code="INVALID_CODE")
    record.mark_consumed()
    return record


@transaction.atomic
def confirm_email_verification(user: User, code: str) -> None:
    _consume_code(user, VerificationCode.Purpose.EMAIL_VERIFY, code)
    now = timezone.now()
    updates = {"is_email_verified": True, "email_verified_at": now}
    # Verified email graduates the account out of PENDING_VERIFICATION.
    if user.account_status == User.AccountStatus.PENDING_VERIFICATION:
        updates["account_status"] = User.AccountStatus.ACTIVE
        user.account_status = User.AccountStatus.ACTIVE
    User.objects.filter(pk=user.pk).update(**updates)
    user.is_email_verified = True
    _sec_event(user, "EMAIL_VERIFIED")


@transaction.atomic
def confirm_phone_verification(user: User, code: str) -> None:
    record = _consume_code(user, VerificationCode.Purpose.PHONE_VERIFY, code)
    phone = record.target
    if User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
        raise BusinessError("This phone number is used by another account.",
                            code="PHONE_TAKEN")
    now = timezone.now()
    User.objects.filter(pk=user.pk).update(
        phone=phone, is_phone_verified=True, phone_verified_at=now
    )
    user.phone = phone
    user.is_phone_verified = True
    _sec_event(user, "PHONE_VERIFIED")


def _sec_event(user: User, event_type: str) -> None:
    try:
        from apps.security.services import record_event
        from apps.security.models import SecurityEvent

        record_event(event_type, user=user)
    except Exception:
        pass


def request_password_reset(email: str) -> None:
    """Always succeeds from the caller's perspective (no user enumeration)."""
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return
    code = _generate_otp()
    VerificationCode.issue(user, VerificationCode.Purpose.PASSWORD_RESET,
                           user.email, code)
    _dispatch_code(user, VerificationCode.Purpose.PASSWORD_RESET, user.email, code)


def _security_alert(user: User, event: str) -> None:
    from apps.notifications.tasks import notify_security_alert

    transaction.on_commit(
        lambda: notify_security_alert.delay(str(user.id), event)
    )


@transaction.atomic
def confirm_password_reset(email: str, code: str, new_password: str) -> None:
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        raise NotFoundError("Account not found.", code="USER_NOT_FOUND")
    _consume_code(user, VerificationCode.Purpose.PASSWORD_RESET, code)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    _security_alert(user, "Password was reset")
    _sec_event(user, "PASSWORD_RESET")


@transaction.atomic
def change_password(user: User, old_password: str, new_password: str) -> None:
    if not user.check_password(old_password):
        raise BusinessError("Current password is incorrect.", code="INVALID_PASSWORD")
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    _security_alert(user, "Password was changed")
    _sec_event(user, "PASSWORD_CHANGED")


def _assert_releasable(user: User) -> None:
    """Deletion/deactivation must not orphan live financial obligations."""
    from apps.bookings.models import Booking
    from apps.payouts.models import Payout

    blockers = []
    if Booking.objects.filter(
        guest=user,
        status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN],
        check_out__gte=timezone.localdate(),
    ).exists():
        blockers.append("active bookings")
    if Booking.objects.filter(
        property__host=user,
        status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN],
    ).exists():
        blockers.append("active host bookings")
    if Payout.objects.filter(
        user=user, status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING]
    ).exists():
        blockers.append("pending payouts")
    if blockers:
        raise BusinessError(
            "Account cannot be removed while it has " + ", ".join(blockers) + ".",
            code="ACCOUNT_HAS_OBLIGATIONS",
        )


@transaction.atomic
def deactivate_account(user: User) -> None:
    _assert_releasable(user)
    user.deactivate()


@transaction.atomic
def delete_account(user: User, password: str) -> None:
    """Soft delete — anonymises PII but keeps financial/booking records."""
    if not user.check_password(password):
        raise BusinessError("Password confirmation failed.", code="INVALID_PASSWORD")
    _assert_releasable(user)
    user.soft_delete()


@transaction.atomic
def update_profile(user: User, **fields) -> User:
    allowed = {
        "first_name", "last_name", "avatar", "date_of_birth",
        "preferred_language", "preferred_currency", "country", "phone",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "phone" in updates and updates["phone"]:
        updates["phone"] = validate_phone_number(updates["phone"])
        if updates["phone"] != user.phone:
            updates["is_phone_verified"] = False
    for key, value in updates.items():
        setattr(user, key, value)
    user.save(update_fields=[*updates.keys(), "updated_at"])
    return user
