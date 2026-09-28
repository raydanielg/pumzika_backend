from rest_framework import serializers

from apps.properties.serializers import PropertyPublicSerializer

from .models import Favorite


class FavoriteSerializer(serializers.ModelSerializer):
    property = PropertyPublicSerializer(read_only=True)

    class Meta:
        model = Favorite
        fields = ["id", "property", "created_at"]


class FavoriteCreateSerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
