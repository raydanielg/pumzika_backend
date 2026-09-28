from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AnalyticsEvent


class EventSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=50)
    object_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    object_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    session_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    metadata = serializers.DictField(required=False)


class TrackEventView(APIView):
    """Client-side analytics events."""

    permission_classes = [IsAuthenticated]
    serializer_class = EventSerializer

    def post(self, request):
        serializer = EventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AnalyticsEvent.objects.create(
            user=request.user,
            **serializer.validated_data,
        )
        return Response({"detail": "Tracked."}, status=201)
