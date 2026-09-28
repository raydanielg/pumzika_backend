from django.contrib import admin

from .models import HostWallet, Payout, PayoutMethod, WalletTransaction


@admin.register(HostWallet)
class HostWalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "currency", "total_earned", "total_paid_out")
    search_fields = ("user__email",)
    readonly_fields = ("balance", "total_earned", "total_paid_out")


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "transaction_type", "amount", "balance_after",
                    "reference", "created_at")
    list_filter = ("transaction_type",)
    search_fields = ("wallet__user__email", "reference")

    def has_change_permission(self, request, obj=None):
        return False  # ledger is append-only


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "currency", "status", "requested_at")
    list_filter = ("status", "currency")
    search_fields = ("reference", "user__email")


admin.site.register(PayoutMethod)
