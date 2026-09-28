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


class PaymentSerializer(serializers.ModelSerializer):
    checkout_url = serializers.CharField(
        source="metadata.checkout_url", read_only=True, default=None
    )

    class Meta:
        model = Payment
        fields = [
            "id", "booking", "reference", "amount", "currency", "status",
            "provider", "checkout_url", "paid_at", "expires_at", "created_at",
        ]
        read_only_fields = fields


class PaymentInitiateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    provider = serializers.CharField(max_length=20)
    idempotency_key = serializers.CharField(
        max_length=64, required=False, default="",
        help_text="May also be supplied via the Idempotency-Key header",
    )
    method_details = serializers.DictField(required=False)


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ["id", "payment", "booking", "amount", "currency", "status",
                  "reason", "processed_at", "created_at"]
        read_only_fields = fields


class RefundCreateSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2,
                                      min_value=Decimal("0.01"))
    reason = serializers.CharField(required=False, allow_blank=True)
