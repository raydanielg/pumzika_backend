from django.contrib import admin

from .models import (
    Payment,
    PaymentAttempt,
    PaymentProvider,
    PaymentTransaction,
    Refund,
    RefundTransaction,
    WebhookEvent,
)


@admin.register(PaymentProvider)
class PaymentProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "is_default")
    # Credentials never live here — only non-secret config.


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "booking", "amount", "currency", "status", "provider")
    list_filter = ("status", "provider", "currency")
    search_fields = ("reference", "external_reference", "booking__reference")
    readonly_fields = ("amount", "currency", "idempotency_key")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_type", "external_event_id", "status",
                    "received_at")
    list_filter = ("provider", "status")
    readonly_fields = ("payload", "payload_hash")


admin.site.register([PaymentTransaction, PaymentAttempt, Refund, RefundTransaction])
