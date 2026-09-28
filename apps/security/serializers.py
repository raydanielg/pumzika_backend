from __future__ import annotations

from rest_framework import serializers

from .models import SecurityEvent, SecurityIncident


class SecurityEventSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True,
                                       default=None)

    class Meta:
        model = SecurityEvent
        fields = [
            "id", "event_type", "severity", "user", "user_email",
            "ip_address", "request_id", "resource_type", "resource_id",
            "metadata", "resolved_at", "resolved_by", "created_at",
        ]
        read_only_fields = fields


class SecurityIncidentSerializer(serializers.ModelSerializer):
    assigned_email = serializers.CharField(source="assigned_to.email",
                                           read_only=True, default=None)
    event_count = serializers.IntegerField(source="events.count",
                                           read_only=True)

    class Meta:
        model = SecurityIncident
        fields = [
            "id", "incident_ref", "severity", "incident_type", "title",
            "description", "affected_service", "status", "detected_at",
            "assigned_to", "assigned_email", "resolution", "resolved_at",
            "event_count", "created_at",
        ]
        read_only_fields = fields


class IncidentTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=SecurityIncident.Status.choices, help_text="target status"
    )
    resolution = serializers.CharField(required=False, allow_blank=True)
    assigned_to = serializers.UUIDField(required=False)
