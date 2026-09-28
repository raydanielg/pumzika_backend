from django.contrib import admin

from .models import Promotion, PromotionUsage


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "is_active",
                    "times_used", "valid_until")
    list_filter = ("is_active", "discount_type")
    search_fields = ("code", "name")


admin.site.register(PromotionUsage)
