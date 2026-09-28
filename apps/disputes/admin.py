from django.contrib import admin

from .models import (
    Dispute,
    DisputeEvidence,
    DisputeMessage,
    DisputeResolution,
    DisputeStatusHistory,
)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("booking", "opened_by", "category", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("booking__reference", "opened_by__email")


admin.site.register([DisputeMessage, DisputeEvidence, DisputeStatusHistory,
                     DisputeResolution])
