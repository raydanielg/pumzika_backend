"""Messaging endpoints — only participants can read/post."""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Conversation
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    SendMessageSerializer,
    StartConversationSerializer,
)


class ConversationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer

    def get_queryset(self):
        return (
            Conversation.objects.filter(participants__user=self.request.user)
            .select_related("property", "booking")
            .prefetch_related("participants__user", "messages__sender")
            .order_by("-updated_at")
        )


class ConversationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer

    def get_object(self):
        return services.get_conversation_for_user(
            self.request.user, self.kwargs["pk"]
        )


class StartConversationView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StartConversationSerializer

    def post(self, request):
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = services.start_conversation(
            request.user,
            serializer.validated_data["property_id"],
            serializer.validated_data["body"],
            serializer.validated_data.get("booking_id"),
        )
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MessageListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer

    def get_queryset(self):
        conversation = services.get_conversation_for_user(
            self.request.user, self.kwargs["pk"]
        )
        return conversation.messages.select_related("sender").prefetch_related(
            "attachments"
        )


class SendMessageView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SendMessageSerializer

    def post(self, request, pk):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachments = list(request.FILES.getlist("attachments"))
        message = services.send_message(
            request.user, pk, serializer.validated_data["body"], attachments or None
        )
        return Response(MessageSerializer(message).data,
                        status=status.HTTP_201_CREATED)


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        services.mark_read(request.user, pk)
        return Response({"detail": "Marked as read."})
