from rest_framework import serializers

from .models import GuestReview, HostReview, PropertyReview


class PropertyReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.first_name", read_only=True)

    class Meta:
        model = PropertyReview
        fields = ["id", "booking", "reviewer", "reviewer_name", "rating",
                  "comment", "cleanliness", "communication", "location",
                  "value", "accuracy", "created_at"]
        read_only_fields = ["id", "reviewer", "booking", "created_at"]


class HostReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.first_name", read_only=True)

    class Meta:
        model = HostReview
        fields = ["id", "booking", "reviewer", "reviewer_name", "host", "rating",
                  "comment", "communication", "hospitality", "created_at"]
        read_only_fields = ["id", "reviewer", "booking", "host", "created_at"]


class GuestReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestReview
        fields = ["id", "booking", "reviewer", "guest", "rating", "comment",
                  "cleanliness", "communication", "house_rules_respect",
                  "created_at"]
        read_only_fields = ["id", "reviewer", "booking", "guest", "created_at"]


class ReviewCreateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True)
    cleanliness = serializers.IntegerField(min_value=1, max_value=5, required=False)
    communication = serializers.IntegerField(min_value=1, max_value=5, required=False)
    location = serializers.IntegerField(min_value=1, max_value=5, required=False)
    value = serializers.IntegerField(min_value=1, max_value=5, required=False)
    accuracy = serializers.IntegerField(min_value=1, max_value=5, required=False)


class GuestReviewCreateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True)
    cleanliness = serializers.IntegerField(min_value=1, max_value=5, required=False)
    communication = serializers.IntegerField(min_value=1, max_value=5, required=False)
    house_rules_respect = serializers.IntegerField(min_value=1, max_value=5,
                                                   required=False)
