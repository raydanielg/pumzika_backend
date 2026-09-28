"""Payment serializers — internal fields stay server-side."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import Payment, PaymentProvider, PaymentTransaction, Refund


class PaymentProviderSerializer(serializers.ModelSerializer):
    """Public: which providers are usable. No config/secrets."""

    class Meta:
        model = PaymentProvider
        fields = ["code", "name", "supported_currencies", "supports_refund"]


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ["event_type", "from_status", "to_status", "created_at"]


class PaymentInitiateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    provider = serializers.CharField(max_length=20)
    payment_method = serializers.CharField(
        max_length=30, required=False, allow_blank=True,
        help_text="e.g. mobile_money, card",
    )
    idempotency_key = serializers.CharField(
        max_length=64, required=False, default="",
        help_text="May also be supplied via the Idempotency-Key header",
    )
    method_details = serializers.DictField(required=False)


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ["id", "reference", "payment", "booking", "amount", "currency",
                  "status", "reason", "processed_at", "created_at"]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    checkout_url = serializers.CharField(
        source="metadata.checkout_url", read_only=True, default=None
    )
    refunds = RefundSerializer(many=True, read_only=True)
    refunded_amount = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "booking", "reference", "amount", "currency", "status",
            "provider", "payment_method", "checkout_url", "paid_at",
            "expires_at", "refunds", "refunded_amount", "created_at",
        ]
        read_only_fields = fields

    def get_refunded_amount(self, obj):
        refunded = sum(
            r.amount for r in obj.refunds.all()
            if r.status == "SUCCESS"
        )
        return str(refunded)


class RefundCreateSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2,
                                      min_value=Decimal("0.01"))
    reason = serializers.CharField(required=False, allow_blank=True)
