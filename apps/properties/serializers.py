"""Property serializers."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import (
    Amenity,
    AmenityCategory,
    Property,
    PropertyDocument,
    PropertyImage,
    PropertyPolicy,
    PropertyPricing,
    PropertyRule,
    PropertyType,
    PropertyUnit,
)


class PropertyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyType
        fields = ["id", "code", "name", "icon", "is_active", "sort_order"]
        read_only_fields = ["id"]


class AmenityCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityCategory
        fields = ["id", "name", "sort_order"]
        read_only_fields = ["id"]


class AmenitySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Amenity
        fields = ["id", "name", "icon", "category", "category_name",
                  "is_active", "sort_order"]
        read_only_fields = ["id"]


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = ["id", "image", "caption", "sort_order", "is_cover", "created_at"]
        read_only_fields = ["id", "created_at"]


class PropertyRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyRule
        fields = ["id", "title", "description", "sort_order"]
        read_only_fields = ["id"]


class PropertyPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyPolicy
        fields = ["pets_allowed", "smoking_allowed", "parties_allowed",
                  "children_allowed", "extra_policy"]


class PropertyPricingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyPricing
        fields = ["id", "start_date", "end_date", "nightly_price", "min_nights"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError("start_date must be before end_date.")
        return attrs


class PropertyDocumentSerializer(serializers.ModelSerializer):
    """Documents are staff/host-visible only — never in public payloads."""

    class Meta:
        model = PropertyDocument
        fields = ["id", "document_type", "file", "created_at"]
        read_only_fields = ["id", "created_at"]


class PropertyUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyUnit
        fields = [
            "id", "name", "description", "quantity",
            "max_guests", "beds", "bedrooms", "bathrooms",
            "price_per_night", "is_active", "sort_order",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class PropertyPublicSerializer(serializers.ModelSerializer):
    """What guests see — no internal fields."""

    images = PropertyImageSerializer(many=True, read_only=True)
    amenities = AmenitySerializer(many=True, read_only=True)
    property_type = PropertyTypeSerializer(read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True)
    country_name = serializers.CharField(source="country.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    host_name = serializers.CharField(source="host.host_profile.display_name", read_only=True)
    host_rating = serializers.DecimalField(
        source="host.host_profile.rating", max_digits=3, decimal_places=2,
        read_only=True, default=None,
    )
    host_verified = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    units = serializers.SerializerMethodField()
    # Location privacy: exact coordinates/address are only revealed to a
    # guest with a confirmed booking — the public gets an approximate pin.
    approximate_latitude = serializers.SerializerMethodField()
    approximate_longitude = serializers.SerializerMethodField()
    exact_location_available = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            "id", "slug", "title", "description", "property_type",
            "country", "country_name", "country_code",
            "region", "region_name", "city", "city_name",
            "district", "area",
            "approximate_latitude", "approximate_longitude",
            "exact_location_available",
            "max_guests", "bedrooms", "beds", "bathrooms",
            "base_price", "currency", "cleaning_fee",
            "min_nights", "max_nights",
            "check_in_time", "check_out_time", "instant_book",
            "rating", "review_count",
            "images", "cover_image", "amenities",
            "host_name", "host_rating", "host_verified", "units",
            "created_at",
        ]

    def get_units(self, obj):
        return PropertyUnitSerializer(obj.units.filter(is_active=True), many=True).data

    def get_host_verified(self, obj) -> bool:
        profile = getattr(obj.host, "host_profile", None)
        return bool(profile and profile.verification_status == "VERIFIED")

    def get_cover_image(self, obj):
        for img in obj.images.all():
            if img.is_cover:
                return PropertyImageSerializer(img).data
        first = obj.images.first()
        return PropertyImageSerializer(first).data if first else None

    @staticmethod
    def _approx(value):
        # ~1.1 km rounding — enough for discovery, not enough to find the door.
        return str(value.quantize(Decimal("0.01"))) if value is not None else None

    def get_approximate_latitude(self, obj):
        return self._approx(obj.latitude)

    def get_approximate_longitude(self, obj):
        return self._approx(obj.longitude)

    def get_exact_location_available(self, obj) -> bool:
        return False


class PropertyHostSerializer(PropertyPublicSerializer):
    """Host's own view — includes workflow fields and the real address."""

    policy = PropertyPolicySerializer(read_only=True)
    rules = PropertyRuleSerializer(many=True, read_only=True)
    special_pricings = PropertyPricingSerializer(many=True, read_only=True)
    readiness_errors = serializers.SerializerMethodField()

    class Meta(PropertyPublicSerializer.Meta):
        fields = PropertyPublicSerializer.Meta.fields + [
            "status", "address", "latitude", "longitude", "rejection_reason",
            "published_at", "approved_at",
            "cancellation_policy", "policy", "rules", "special_pricings",
            "readiness_errors", "updated_at",
        ]

    def get_exact_location_available(self, obj) -> bool:
        return True

    def get_readiness_errors(self, obj):
        from .services import publish_readiness_errors

        return publish_readiness_errors(obj)


class PropertyCreateSerializer(serializers.ModelSerializer):
    amenity_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = Property
        fields = [
            "title", "description", "property_type",
            "country", "region", "city", "district", "area",
            "address", "latitude", "longitude",
            "max_guests", "bedrooms", "beds", "bathrooms",
            "base_price", "currency", "cleaning_fee",
            "min_nights", "max_nights",
            "check_in_time", "check_out_time", "instant_book",
            "cancellation_policy", "amenity_ids",
        ]

    def validate_currency(self, value):
        return value.upper()


class ImageOrderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(child=serializers.UUIDField())
