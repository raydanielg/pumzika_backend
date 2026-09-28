from django.contrib import admin

from .models import AvailabilityDate


@admin.register(AvailabilityDate)
class AvailabilityDateAdmin(admin.ModelAdmin):
    list_display = ("property", "date", "status", "price_override")
    list_filter = ("status",)
    search_fields = ("property__title",)
    date_hierarchy = "date"
