"""KYC serializers — document files are never exposed in public payloads."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import KYCDocument, KYCProfile, KYCStatusHistory, KYCVerification


class KYCProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCProfile
        fields = [
            "id", "status", "legal_first_name", "legal_last_name",
            "date_of_birth", "nationality", "country_of_residence",
            "submitted_at", "verified_at", "expires_at", "rejection_reason",
        ]
        read_only_fields = ["id", "status", "submitted_at", "verified_at",
                            "expires_at", "rejection_reason"]


class KYCProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCProfile
        fields = ["legal_first_name", "legal_last_name", "date_of_birth",
                  "nationality", "country_of_residence"]


class KYCDocumentSerializer(serializers.ModelSerializer):
    """Returned only to the owner/staff — file is a private-storage reference."""

    class Meta:
        model = KYCDocument
        fields = ["id", "document_type", "document_number", "issuing_country",
                  "expires_on", "created_at"]
        read_only_fields = ["id", "created_at"]


class KYCDocumentUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCDocument
        fields = ["document_type", "file", "document_number",
                  "issuing_country", "expires_on"]


class KYCVerificationSerializer(serializers.ModelSerializer):
    documents = serializers.SerializerMethodField()

    class Meta:
        model = KYCVerification
        fields = ["id", "status", "submitted_at", "completed_at", "notes",
                  "documents"]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_documents(self, obj):
        # Only rendered for owner/staff views.
        return KYCDocumentSerializer(obj.profile.documents.all(), many=True).data


class KYCReviewDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["APPROVED", "REJECTED", "MORE_INFO"])
    reason = serializers.CharField(required=False, allow_blank=True)


class KYCStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCStatusHistory
        fields = ["from_status", "to_status", "reason", "created_at"]
