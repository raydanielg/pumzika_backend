from rest_framework import serializers

from .models import Area, City, Country, District, Region


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "code", "name", "currency_code", "phone_code",
                  "timezone", "languages", "is_active", "flag"]
        read_only_fields = ["id"]


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ["id", "country", "name", "code", "is_active"]
        read_only_fields = ["id"]


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["id", "region", "name", "latitude", "longitude", "is_active"]
        read_only_fields = ["id"]


class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ["id", "city", "name", "is_active"]
        read_only_fields = ["id"]


class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "district", "name", "is_active"]
        read_only_fields = ["id"]
