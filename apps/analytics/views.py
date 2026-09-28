from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AnalyticsEvent


class TrackEventView(APIView):
    """Client-side analytics events — anonymous allowed."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        AnalyticsEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            event_type=request.data.get("event_type", "")[:50],
            object_type=request.data.get("object_type", "")[:50],
            object_id=str(request.data.get("object_id", ""))[:64],
            session_id=request.data.get("session_id", "")[:64],
            metadata=request.data.get("metadata", {}),
        )
        return Response({"detail": "Tracked."}, status=201)
