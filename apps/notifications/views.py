"""Notification endpoints."""
from __future__ import annotations

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .models import (
    Notification,
    NotificationPreference,
    UserDevice,
    UserNotificationSettings,
)
from .serializers import (
    DeviceRegisterSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    UserDeviceSerializer,
    UserNotificationSettingsSerializer,
)


class NotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return self.request.user.notifications.filter(channel="IN_APP")


class NotificationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()

    def get_queryset(self):
        return self.request.user.notifications.all()


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def post(self, request, pk=None):
        qs = request.user.notifications.filter(read_at__isnull=True)
        if pk:
            qs = qs.filter(pk=pk)
        qs.update(read_at=timezone.now(), status=Notification.Status.READ)
        return Response({"detail": "Marked as read."})


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get(self, request):
        count = request.user.notifications.filter(read_at__isnull=True).count()
        return Response({"unread": count})


class PreferenceListUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    def get(self, request):
        prefs = NotificationPreference.objects.filter(user=request.user)
        return Response(NotificationPreferenceSerializer(prefs, many=True).data)

    def post(self, request):
        serializer = NotificationPreferenceSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        for item in serializer.validated_data:
            NotificationPreference.objects.update_or_create(
                user=request.user,
                event_type=item["event_type"],
                channel=item["channel"],
                defaults={"enabled": item["enabled"]},
            )
        return Response({"detail": "Preferences updated."})


class SettingsView(APIView):
    """Broad channel/category switches — the per-event table refines these."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSettingsSerializer

    def get(self, request):
        row, _ = UserNotificationSettings.objects.get_or_create(
            user=request.user
        )
        return Response(UserNotificationSettingsSerializer(row).data)

    def patch(self, request):
        row, _ = UserNotificationSettings.objects.get_or_create(
            user=request.user
        )
        serializer = UserNotificationSettingsSerializer(
            row, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DeviceListCreateView(generics.ListCreateAPIView):
    """Register/list push devices — a user may have many devices."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return (DeviceRegisterSerializer if self.request.method == "POST"
                else UserDeviceSerializer)

    def get_queryset(self):
        return UserDevice.objects.filter(user=self.request.user, is_active=True)

    def perform_create(self, serializer):
        UserDevice.objects.update_or_create(
            user=self.request.user,
            device_id=serializer.validated_data["device_id"],
            defaults={
                "platform": serializer.validated_data.get(
                    "platform", UserDevice.Platform.OTHER),
                "push_token": serializer.validated_data.get("push_token", ""),
                "app_version": serializer.validated_data.get("app_version", ""),
                "is_active": True,
            },
        )


class DeviceDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserDeviceSerializer

    def delete(self, request, pk):
        device = UserDevice.objects.filter(pk=pk, user=request.user).first()
        if device:
            device.is_active = False
            device.push_token = ""
            device.save(update_fields=["is_active", "push_token", "updated_at"])
        return Response(status=204)
