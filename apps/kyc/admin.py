from django.contrib import admin

from .models import KYCDocument, KYCProfile, KYCReview, KYCStatusHistory, KYCVerification


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "submitted_at", "verified_at")
    list_filter = ("status",)
    search_fields = ("user__email", "legal_first_name", "legal_last_name")


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("profile", "document_type", "document_number", "created_at")
    list_filter = ("document_type",)


admin.site.register([KYCVerification, KYCReview, KYCStatusHistory])
