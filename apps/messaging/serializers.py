from rest_framework import serializers

from .models import Conversation, Message, MessageAttachment


class MessageAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageAttachment
        fields = ["id", "file", "name"]


class MessageSerializer(serializers.ModelSerializer):
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    sender_name = serializers.CharField(source="sender.first_name", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender", "sender_name", "body",
                  "attachments", "created_at"]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source="property.title", read_only=True,
                                           default=None)
    participants = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "property", "property_title", "booking", "subject",
                  "participants", "last_message", "unread_count", "created_at"]

    def get_participants(self, obj):
        return [
            {"id": str(p.user_id), "name": p.user.full_name}
            for p in obj.participants.select_related("user")
        ]

    def get_last_message(self, obj):
        msg = obj.messages.last()
        return MessageSerializer(msg).data if msg else None

    def get_unread_count(self, obj):
        user = self.context["request"].user
        participant = obj.participants.filter(user=user).first()
        qs = obj.messages.exclude(sender=user)
        if participant and participant.last_read_at:
            qs = qs.filter(created_at__gt=participant.last_read_at)
        return qs.count()


class StartConversationSerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
    booking_id = serializers.UUIDField(required=False, allow_null=True)
    body = serializers.CharField()


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField()
