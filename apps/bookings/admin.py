from django.contrib import admin

from .models import (
    Booking,
    BookingCancellation,
    BookingGuest,
    BookingPrice,
    BookingStatusHistory,
    CancellationPolicy,
    CancellationRule,
)


class RuleInline(admin.TabularInline):
    model = CancellationRule
    extra = 0


@admin.register(CancellationPolicy)
class CancellationPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    inlines = [RuleInline]


class PriceInline(admin.StackedInline):
    model = BookingPrice
    can_delete = False
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "guest", "property", "check_in", "check_out",
                    "status", "currency")
    list_filter = ("status", "currency")
    search_fields = ("reference", "guest__email", "property__title")
    raw_id_fields = ("guest", "property")
    inlines = [PriceInline]
    date_hierarchy = "check_in"


admin.site.register([BookingGuest, BookingStatusHistory, BookingCancellation])
