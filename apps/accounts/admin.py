from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import HostProfile, RolePermission, User, VerificationCode


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "role", "is_active", "is_email_verified", "created_at")
    list_filter = ("role", "is_active", "is_email_verified")
    search_fields = ("email", "phone", "first_name", "last_name")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "phone", "avatar",
                                 "date_of_birth", "country", "preferred_language",
                                 "preferred_currency")}),
        ("Status", {"fields": ("role", "is_active", "is_staff", "is_superuser",
                               "is_email_verified", "is_phone_verified", "deleted_at")}),
        ("Timestamps", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login", "deleted_at")
    add_fieldsets = (
        (None, {"classes": ("wide",),
                "fields": ("email", "password1", "password2", "first_name", "last_name")}),
    )


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "code")
    list_filter = ("role",)
    search_fields = ("code",)


@admin.register(HostProfile)
class HostProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "hosting_status", "verification_status", "rating")
    list_filter = ("hosting_status", "verification_status")
    search_fields = ("user__email", "display_name")


@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "target", "expires_at", "consumed_at")
    list_filter = ("purpose",)
    readonly_fields = ("code_hash",)
