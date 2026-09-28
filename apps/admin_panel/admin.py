from django.contrib import admin

from .models import AuditLog, CommissionRule, PlatformSetting, TaxRule


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = ("scope", "percent", "country", "property_type", "host",
                    "is_active")
    list_filter = ("scope", "is_active")


@admin.register(TaxRule)
class TaxRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "percent", "is_active")
    list_filter = ("country", "is_active")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "target_type", "target_id", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("actor__email", "target_id", "action")
    readonly_fields = ("actor", "action", "target_type", "target_id",
                       "ip_address", "user_agent", "before", "after",
                       "metadata")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # append-only — corrections go through adjustments
