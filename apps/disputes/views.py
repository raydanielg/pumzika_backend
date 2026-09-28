"""Dispute endpoints — parties file/message; staff manage."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import DISPUTE_MANAGE
from apps.common.permissions import PermissionRequired
from apps.admin_panel.services import audit

from . import services
from .models import Dispute
from .serializers import (
    DisputeCreateSerializer,
    DisputeEvidenceSerializer,
    DisputeMessageCreateSerializer,
    DisputeMessageSerializer,
    DisputeResolveSerializer,
    DisputeSerializer,
    DisputeStatusUpdateSerializer,
)


class MyDisputesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DisputeSerializer

    def get_queryset(self):
        user = self.request.user
        return Dispute.objects.filter(
            booking__guest=user
        ) | Dispute.objects.filter(booking__property__host=user)


class DisputeCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DisputeCreateSerializer

    def post(self, request):
        serializer = DisputeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        dispute = services.open_dispute(
            request.user, data["booking_id"], data["category"], data["description"]
        )
        audit(actor=request.user, action="dispute.opened", target=dispute,
              request=request)
        return Response(DisputeSerializer(dispute).data,
                        status=status.HTTP_201_CREATED)


class DisputeDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DisputeSerializer

    def get_object(self):
        return services.get_dispute_for_user(self.request.user, self.kwargs["pk"])


class DisputeMessageView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DisputeMessageCreateSerializer

    def post(self, request, pk):
        dispute = services.get_dispute_for_user(request.user, pk)
        serializer = DisputeMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = dispute.messages.create(
            sender=request.user, body=serializer.validated_data["body"]
        )
        return Response(DisputeMessageSerializer(message).data,
                        status=status.HTTP_201_CREATED)


class DisputeEvidenceView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = DisputeEvidenceSerializer

    def post(self, request, pk):
        dispute = services.get_dispute_for_user(request.user, pk)
        file = request.FILES.get("file")
        if file is None:
            from apps.common.exceptions import BusinessError

            raise BusinessError("No file provided.", code="FILE_REQUIRED")
        evidence = dispute.evidence.create(
            uploaded_by=request.user, file=file,
            description=request.data.get("description", ""),
        )
        return Response(DisputeEvidenceSerializer(evidence).data,
                        status=status.HTTP_201_CREATED)


# ------------------------------- staff -------------------------------------

class StaffDisputeListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (DISPUTE_MANAGE,)
    serializer_class = DisputeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "category"]

    def get_queryset(self):
        return Dispute.objects.select_related(
            "booking", "opened_by"
        ).order_by("-created_at")


class StaffDisputeStatusView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (DISPUTE_MANAGE,)
    serializer_class = DisputeStatusUpdateSerializer

    def post(self, request, pk):
        dispute = services.get_dispute_for_user(request.user, pk)
        serializer = DisputeStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_status(
            dispute, serializer.validated_data["status"], request.user,
            serializer.validated_data.get("note", ""),
        )
        audit(actor=request.user, action="dispute.status_changed",
              target=dispute, request=request)
        return Response(DisputeSerializer(dispute).data)


class StaffDisputeResolveView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (DISPUTE_MANAGE,)
    serializer_class = DisputeResolveSerializer

    def post(self, request, pk):
        serializer = DisputeResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resolution = services.resolve_dispute(
            request.user, pk,
            serializer.validated_data["outcome"],
            serializer.validated_data.get("notes", ""),
            serializer.validated_data.get("refund_amount", 0),
        )
        audit(actor=request.user, action="dispute.resolved",
              target=resolution.dispute, request=request,
              metadata={"outcome": resolution.outcome})
        return Response(DisputeSerializer(resolution.dispute).data)
