"""KYC workflow — submission and staff review."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import HostProfile
from apps.common.exceptions import BusinessError, NotFoundError

from .models import KYCProfile, KYCStatus, KYCStatusHistory, KYCVerification


def get_or_create_profile(user) -> KYCProfile:
    profile, _ = KYCProfile.objects.get_or_create(user=user)
    return profile


def _record_status(profile: KYCProfile, to_status: str, changed_by=None, reason: str = ""):
    KYCStatusHistory.objects.create(
        profile=profile,
        from_status=profile.status,
        to_status=to_status,
        changed_by=changed_by,
        reason=reason,
    )


@transaction.atomic
def submit_profile(user, data: dict) -> KYCProfile:
    """Fill in legal details and move the profile to UNDER_REVIEW."""
    profile = get_or_create_profile(user)
    if profile.status in (KYCStatus.VERIFIED, KYCStatus.UNDER_REVIEW):
        raise BusinessError("KYC already submitted or verified.", code="KYC_INVALID_STATE")
    for key in ("legal_first_name", "legal_last_name", "date_of_birth",
                "nationality", "country_of_residence"):
        if key in data:
            setattr(profile, key, data[key])
    profile.status = KYCStatus.PENDING
    profile.save()
    return profile


@transaction.atomic
def add_document(user, document_type: str, file, **extra):
    profile = get_or_create_profile(user)
    if profile.status == KYCStatus.VERIFIED:
        raise BusinessError("KYC already verified.", code="KYC_INVALID_STATE")
    return profile.documents.create(
        document_type=document_type, file=file, **extra
    )


@transaction.atomic
def submit_for_review(user) -> KYCVerification:
    profile = get_or_create_profile(user)
    if profile.status == KYCStatus.VERIFIED:
        raise BusinessError("KYC already verified.", code="KYC_ALREADY_VERIFIED")
    if not profile.documents.exists():
        raise BusinessError("At least one identity document is required.",
                            code="KYC_DOCUMENTS_REQUIRED")
    if not (profile.legal_first_name and profile.legal_last_name):
        raise BusinessError("Legal name is required.", code="KYC_INCOMPLETE")

    verification = profile.verifications.create(status=KYCStatus.UNDER_REVIEW)
    profile.status = KYCStatus.UNDER_REVIEW
    profile.submitted_at = timezone.now()
    profile.save(update_fields=["status", "submitted_at", "updated_at"])
    _record_status(profile, KYCStatus.UNDER_REVIEW, changed_by=user)

    from apps.notifications.tasks import notify_kyc_submitted

    transaction.on_commit(
        lambda: notify_kyc_submitted.delay(str(user.id))
    )
    return verification


@transaction.atomic
def review_verification(reviewer, verification_id, decision: str, reason: str = ""):
    """Staff decision. KYCReview is append-only; every decision is logged."""
    from .models import KYCReview

    verification = (
        KYCVerification.objects.select_for_update()
        .select_related("profile__user")
        .filter(pk=verification_id)
        .first()
    )
    if verification is None:
        raise NotFoundError("Verification not found.", code="KYC_NOT_FOUND")
    if verification.status != KYCStatus.UNDER_REVIEW:
        raise BusinessError("This verification has already been decided.",
                            code="KYC_ALREADY_DECIDED")

    profile = verification.profile
    KYCReview.objects.create(
        verification=verification, reviewer=reviewer,
        decision=decision, reason=reason,
    )

    if decision == KYCReview.Decision.APPROVED:
        new_status = KYCStatus.VERIFIED
        profile.verified_at = timezone.now()
        profile.rejection_reason = ""
    elif decision == KYCReview.Decision.REJECTED:
        new_status = KYCStatus.REJECTED
        profile.rejection_reason = reason
    else:
        new_status = KYCStatus.PENDING  # more info requested

    verification.status = new_status
    verification.completed_at = timezone.now()
    verification.save(update_fields=["status", "completed_at"])

    _record_status(profile, new_status, changed_by=reviewer, reason=reason)
    profile.status = new_status
    profile.save()

    # Keep HostProfile in sync — hosts cannot publish until verified.
    HostProfile.objects.filter(user=profile.user).update(
        verification_status=(
            HostProfile.VerificationStatus.VERIFIED
            if new_status == KYCStatus.VERIFIED
            else (
                HostProfile.VerificationStatus.REJECTED
                if new_status == KYCStatus.REJECTED
                else HostProfile.VerificationStatus.PENDING
            )
        )
    )

    from apps.notifications.tasks import notify_kyc_decision

    transaction.on_commit(
        lambda: notify_kyc_decision.delay(
            str(profile.user_id),
            new_status == KYCStatus.VERIFIED,
            reason,
        )
    )
    return verification
