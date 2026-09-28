from rest_framework import serializers

from .models import (
    Dispute,
    DisputeEvidence,
    DisputeMessage,
    DisputeResolution,
    DisputeStatusHistory,
)


class DisputeMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.first_name", read_only=True)

    class Meta:
        model = DisputeMessage
        fields = ["id", "sender", "sender_name", "body", "created_at"]
        read_only_fields = fields


class DisputeEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisputeEvidence
        fields = ["id", "file", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


class DisputeStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DisputeStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class DisputeResolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisputeResolution
        fields = ["outcome", "refund_amount", "notes", "resolved_by", "created_at"]
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    messages = DisputeMessageSerializer(many=True, read_only=True)
    evidence = DisputeEvidenceSerializer(many=True, read_only=True)
    status_history = DisputeStatusHistorySerializer(many=True, read_only=True)
    resolution = DisputeResolutionSerializer(read_only=True)
    booking_reference = serializers.CharField(source="booking.reference",
                                              read_only=True)
    opened_by_email = serializers.EmailField(source="opened_by.email",
                                             read_only=True)

    class Meta:
        model = Dispute
        fields = ["id", "booking", "booking_reference", "opened_by",
                  "opened_by_email", "category", "description", "status",
                  "messages", "evidence", "status_history", "resolution",
                  "created_at"]
        read_only_fields = fields


class DisputeCreateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=Dispute.Category.choices)
    description = serializers.CharField()


class DisputeMessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()


class DisputeResolveSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=DisputeResolution.Outcome.choices)
    notes = serializers.CharField(required=False, allow_blank=True)
    refund_amount = serializers.DecimalField(max_digits=14, decimal_places=2,
                                             default=0, min_value=0)


class DisputeStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["UNDER_REVIEW", "WAITING_FOR_USER",
                                            "CLOSED", "REJECTED"])
    note = serializers.CharField(required=False, allow_blank=True)
