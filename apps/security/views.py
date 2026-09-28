"""Security dashboard — events, incidents, monitoring aggregates."""
from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import INCIDENT_MANAGE, SECURITY_VIEW
from apps.common.permissions import PermissionRequired
from apps.admin_panel.models import AuditLog
from apps.admin_panel.services import audit
from apps.common.exceptions import NotFoundError
from apps.payments.models import Payment, WebhookEvent

from .models import SecurityEvent, SecurityIncident
from .serializers import (
    IncidentTransitionSerializer,
    SecurityEventSerializer,
    SecurityIncidentSerializer,
)
from . import services


class SecurityEventListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (SECURITY_VIEW,)
    serializer_class = SecurityEventSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["event_type", "severity", "user", "request_id"]

    def get_queryset(self):
        qs = SecurityEvent.objects.select_related("user", "resolved_by")
        params = self.request.query_params
        if since := params.get("since"):
            qs = qs.filter(created_at__gte=since)
        if until := params.get("until"):
            qs = qs.filter(created_at__lte=until)
        return qs


class IncidentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (SECURITY_VIEW,)
    serializer_class = SecurityIncidentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["severity", "status", "incident_type"]

    def get_queryset(self):
        return SecurityIncident.objects.select_related(
            "assigned_to").prefetch_related("events")


class IncidentDetailView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (SECURITY_VIEW,)
    serializer_class = SecurityIncidentSerializer

    def get(self, request, pk):
        incident = SecurityIncident.objects.filter(pk=pk).first()
        if incident is None:
            raise NotFoundError("Incident not found.", code="INCIDENT_NOT_FOUND")
        return Response(SecurityIncidentSerializer(incident).data)


class IncidentTransitionView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (INCIDENT_MANAGE,)
    serializer_class = IncidentTransitionSerializer

    def post(self, request, pk):
        serializer = IncidentTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = SecurityIncident.objects.select_for_update().filter(
            pk=pk).first()
        if incident is None:
            raise NotFoundError("Incident not found.", code="INCIDENT_NOT_FOUND")
        incident = services.transition_incident(
            incident,
            serializer.validated_data["status"],
            actor=request.user,
            resolution=serializer.validated_data.get("resolution", ""),
        )
        audit(actor=request.user, action="security.incident_transition",
              target=incident, request=request)
        return Response(SecurityIncidentSerializer(incident).data)


class SecurityMonitoringView(APIView):
    """Operational aggregates — never raw payloads."""

    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (SECURITY_VIEW,)
    serializer_class = SecurityEventSerializer  # docs hint only

    def get(self, request):
        since_24h = timezone.now() - timedelta(hours=24)
        return Response({
            "security_events_24h": SecurityEvent.objects.filter(
                created_at__gte=since_24h).count(),
            "critical_events_24h": SecurityEvent.objects.filter(
                created_at__gte=since_24h,
                severity=SecurityEvent.Severity.CRITICAL).count(),
            "login_failures_24h": SecurityEvent.objects.filter(
                created_at__gte=since_24h,
                event_type=SecurityEvent.Type.LOGIN_FAILED).count(),
            "webhook_failures_24h": WebhookEvent.objects.filter(
                received_at__gte=since_24h,
                status=WebhookEvent.Status.FAILED).count(),
            "pending_payments": Payment.objects.filter(
                status__in=[Payment.Status.PENDING,
                            Payment.Status.PROCESSING]).count(),
            "open_incidents": SecurityIncident.objects.exclude(
                status=SecurityIncident.Status.CLOSED).count(),
            "recent_admin_actions": AuditLog.objects.filter(
                action__startswith="admin.").order_by("-created_at")[:10].count(),
        })


class SecuritySuspensionsView(APIView):
    """Suspend / restore a user — guarded by user.suspend permission."""

    permission_classes = [IsAuthenticated, PermissionRequired]
    serializer_class = SecurityIncidentSerializer  # docs hint only

    def post(self, request, pk):
        from apps.accounts.models import User
        from apps.accounts.constants import USER_MANAGE

        if not request.user.has_perm_code(USER_MANAGE):
            raise NotFoundError("Insufficient permission.",
                                code="PERMISSION_DENIED")
        target = User.objects.filter(pk=pk).first()
        if target is None:
            raise NotFoundError("User not found.", code="USER_NOT_FOUND")
        action = request.data.get("action")
        if action == "suspend":
            reason = request.data.get("reason", "")
            if not reason:
                from apps.common.exceptions import BusinessError
                raise BusinessError("Suspension requires a reason.",
                                    code="REASON_REQUIRED")
            services.suspend_account(
                target, request.user, reason,
                minutes=request.data.get("minutes"), request=request,
            )
        elif action == "restore":
            services.restore_account(target, request.user, request=request)
        else:
            from apps.common.exceptions import BusinessError
            raise BusinessError("action must be 'suspend' or 'restore'.",
                                code="INVALID_ACTION")
        audit(actor=request.user, action=f"security.user_{action}",
              target=target, request=request,
              metadata={"reason": request.data.get("reason", "")})
        return Response({"status": target.account_status})
