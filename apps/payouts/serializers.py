from rest_framework import serializers

from .models import HostWallet, Payout, PayoutMethod, WalletTransaction


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = HostWallet
        fields = ["balance", "currency", "total_earned", "total_paid_out"]
        read_only_fields = fields


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ["id", "transaction_type", "amount", "balance_after",
                  "currency", "reference", "description", "created_at"]
        read_only_fields = fields


class PayoutMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutMethod
        fields = ["id", "method_type", "label", "account_name",
                  "account_number", "provider_name", "currency",
                  "is_default", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class PayoutSerializer(serializers.ModelSerializer):
    method = PayoutMethodSerializer(read_only=True)

    class Meta:
        model = Payout
        fields = ["id", "reference", "amount", "currency", "status",
                  "method", "requested_at", "processed_at", "rejection_reason"]
        read_only_fields = fields


class PayoutRequestSerializer(serializers.Serializer):
    method_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)


class PayoutProcessSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True)
