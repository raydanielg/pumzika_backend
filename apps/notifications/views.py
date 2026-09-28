"""Notification endpoints."""
from __future__ import annotations

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .models import Notification, NotificationPreference
from .serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
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
