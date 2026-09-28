from rest_framework import serializers

from .models import Promotion, PromotionUsage


class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = [
            "id", "code", "name", "discount_type", "value", "currency",
            "valid_from", "valid_until", "max_uses", "per_user_limit",
            "min_booking_amount", "max_discount", "country", "properties",
            "is_active", "times_used",
        ]
        read_only_fields = ["id", "times_used"]


class PromotionUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromotionUsage
        fields = ["id", "promotion", "user", "booking", "discount_amount",
                  "created_at"]
        read_only_fields = fields


class ValidatePromoSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50)
    property_id = serializers.UUIDField()
    check_in = serializers.DateField()
    check_out = serializers.DateField()
