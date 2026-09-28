"""KYC — identity verification for hosts (and optionally guests)."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel
from apps.common.validators import secure_upload_to


class KYCStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
    VERIFIED = "VERIFIED", "Verified"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"


class KYCProfile(UUIDModel):
    """One KYC profile per user; documents and decisions hang off it."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kyc_profile"
    )
    status = models.CharField(
        max_length=20, choices=KYCStatus.choices, default=KYCStatus.PENDING, db_index=True
    )
    legal_first_name = models.CharField(max_length=150, blank=True)
    legal_last_name = models.CharField(max_length=150, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="kyc_nationals",
    )
    country_of_residence = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="kyc_residents",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "submitted_at"])]


class KYCDocument(UUIDModel):
    class DocumentType(models.TextChoices):
        NATIONAL_ID = "NATIONAL_ID", "National ID"
        PASSPORT = "PASSPORT", "Passport"
        DRIVER_LICENSE = "DRIVER_LICENSE", "Driver License"
        BUSINESS_LICENSE = "BUSINESS_LICENSE", "Business License"
        PROPERTY_AUTHORIZATION = "PROPERTY_AUTHORIZATION", "Property Authorization"

    profile = models.ForeignKey(
        KYCProfile, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    # Stored in private storage; never served by a public URL.
    file = models.FileField(upload_to=secure_upload_to("kyc"))
    document_number = models.CharField(max_length=100, blank=True)
    issuing_country = models.ForeignKey(
        "locations.Country", null=True, blank=True, on_delete=models.SET_NULL
    )
    expires_on = models.DateField(null=True, blank=True)


class KYCVerification(UUIDModel):
    """A single submission/verification round for a profile."""

    profile = models.ForeignKey(
        KYCProfile, on_delete=models.CASCADE, related_name="verifications"
    )
    status = models.CharField(
        max_length=20, choices=KYCStatus.choices, default=KYCStatus.PENDING
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class KYCReview(UUIDModel):
    """A staff decision on a verification round — append-only."""

    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        MORE_INFO = "MORE_INFO", "More Info Required"

    verification = models.ForeignKey(
        KYCVerification, on_delete=models.CASCADE, related_name="reviews"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="kyc_reviews"
    )
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.TextField(blank=True)


class KYCStatusHistory(TimeStampedModel):
    """Append-only status trail — every transition is recorded."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        KYCProfile, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="kyc_status_changes",
    )
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
