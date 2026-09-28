from rest_framework import serializers

from apps.accounts.models import User
from apps.locations.models import Area, City, Country, District, Region
from apps.notifications.models import NotificationTemplate
from apps.properties.models import Amenity, AmenityCategory, PropertyType

from .models import AuditLog, CommissionRule, PlatformSetting, TaxRule


class PlatformSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSetting
        fields = ["id", "key", "value", "description", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class CommissionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionRule
        fields = ["id", "scope", "percent", "country", "property_type",
                  "host", "is_active"]
        read_only_fields = ["id"]


class TaxRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRule
        fields = ["id", "name", "country", "percent", "is_active"]
        read_only_fields = ["id"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True,
                                         default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_email", "action", "target_type",
                  "target_id", "ip_address", "user_agent", "before", "after",
                  "metadata", "created_at"]
        read_only_fields = fields


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "phone", "first_name", "last_name", "role",
                  "is_active", "is_email_verified", "is_phone_verified",
                  "country", "created_at", "last_login"]
        read_only_fields = ["id", "created_at", "last_login"]


class UserRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=User.Role.choices)


class PropertyModerationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class CountryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "code", "name", "currency_code", "phone_code",
                  "timezone", "languages", "is_active"]
        read_only_fields = ["id"]


class RegionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ["id", "country", "name", "code", "is_active"]
        read_only_fields = ["id"]


class CityAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["id", "region", "name", "latitude", "longitude", "is_active"]
        read_only_fields = ["id"]


class DistrictAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ["id", "city", "name", "is_active"]
        read_only_fields = ["id"]


class AreaAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "district", "name", "is_active"]
        read_only_fields = ["id"]


class AmenityAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["id", "name", "icon", "category", "is_active", "sort_order"]
        read_only_fields = ["id"]


class AmenityCategoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityCategory
        fields = ["id", "name", "sort_order"]
        read_only_fields = ["id"]


class PropertyTypeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyType
        fields = ["id", "code", "name", "icon", "is_active", "sort_order"]
        read_only_fields = ["id"]


class NotificationTemplateAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = ["id", "key", "channel", "subject", "body", "is_active"]
        read_only_fields = ["id"]
