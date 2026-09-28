from django.contrib import admin

from .models import GuestReview, HostReview, PropertyReview


class BaseReviewAdmin(admin.ModelAdmin):
    list_display = ("booking", "reviewer", "rating", "is_published", "created_at")
    list_filter = ("is_published", "rating")
    search_fields = ("booking__reference", "reviewer__email")


admin.site.register(PropertyReview, BaseReviewAdmin)
admin.site.register(HostReview, BaseReviewAdmin)
admin.site.register(GuestReview, BaseReviewAdmin)
