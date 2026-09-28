"""KYC endpoints — owner submits; staff review via permission codes."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.schema import schema_empty_queryset
from apps.accounts.constants import KYC_REVIEW, KYC_SUBMIT, KYC_VIEW_ALL
from apps.common.permissions import PermissionRequired
from apps.admin_panel.services import audit

from . import services
from .models import KYCVerification
from .serializers import (
    KYCDocumentSerializer,
    KYCDocumentUploadSerializer,
    KYCProfileSerializer,
    KYCProfileUpdateSerializer,
    KYCReviewDecisionSerializer,
    KYCStatusHistorySerializer,
    KYCVerificationSerializer,
)


class MyKYCProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_SUBMIT,)

    def get_object(self):
        return services.get_or_create_profile(self.request.user)

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return KYCProfileUpdateSerializer
        return KYCProfileSerializer

    def perform_update(self, serializer):
        services.submit_profile(self.request.user, serializer.validated_data)


class MyKYCDocumentView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_SUBMIT,)
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = KYCDocumentUploadSerializer

    def post(self, request):
        serializer = KYCDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = services.add_document(request.user, **serializer.validated_data)
        audit(actor=request.user, action="kyc.document_uploaded",
              target=document, request=request)
        return Response(KYCDocumentSerializer(document).data,
                        status=status.HTTP_201_CREATED)


class MyKYCDocumentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_SUBMIT,)
    serializer_class = KYCDocumentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        return services.get_or_create_profile(self.request.user).documents.all()


class MyKYCSubmitView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_SUBMIT,)
    serializer_class = KYCVerificationSerializer

    def post(self, request):
        verification = services.submit_for_review(request.user)
        audit(actor=request.user, action="kyc.submitted",
              target=verification, request=request)
        return Response(KYCVerificationSerializer(verification).data,
                        status=status.HTTP_201_CREATED)


class MyKYCHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = KYCStatusHistorySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        profile = services.get_or_create_profile(self.request.user)
        return profile.status_history.all()


# ------------------------------- staff ------------------------------------

class StaffVerificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_VIEW_ALL,)
    serializer_class = KYCVerificationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        return KYCVerification.objects.select_related("profile__user").order_by(
            "-submitted_at"
        )


class StaffVerificationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_VIEW_ALL,)
    serializer_class = KYCVerificationSerializer
    queryset = KYCVerification.objects.select_related("profile__user").prefetch_related(
        "profile__documents"
    )


class StaffVerificationReviewView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (KYC_REVIEW,)
    serializer_class = KYCReviewDecisionSerializer

    def post(self, request, pk):
        serializer = KYCReviewDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = services.review_verification(
            reviewer=request.user,
            verification_id=pk,
            decision=serializer.validated_data["decision"],
            reason=serializer.validated_data.get("reason", ""),
        )
        audit(actor=request.user,
              action=f"kyc.{serializer.validated_data['decision'].lower()}",
              target=verification, request=request)
        return Response(KYCVerificationSerializer(verification).data)
