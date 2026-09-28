from django.contrib import admin

from .models import SecurityEvent, SecurityIncident


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Read-only — events are append-only evidence."""

    list_display = ("event_type", "severity", "user", "ip_address",
                    "resource_type", "created_at")
    list_filter = ("severity", "event_type")
    search_fields = ("request_id", "resource_id", "user__email")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SecurityIncident)
class SecurityIncidentAdmin(admin.ModelAdmin):
    list_display = ("incident_ref", "title", "severity", "status",
                    "affected_service", "detected_at")
    list_filter = ("status", "severity", "incident_type")
    search_fields = ("incident_ref", "title")
    readonly_fields = ("incident_ref", "detected_at")

    def has_delete_permission(self, request, obj=None):
        return False
