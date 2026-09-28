from rest_framework import serializers


class SearchParamsSerializer(serializers.Serializer):
    destination = serializers.CharField(required=False, allow_blank=True)
    country = serializers.IntegerField(required=False)
    region = serializers.IntegerField(required=False)
    city = serializers.IntegerField(required=False)
    district = serializers.IntegerField(required=False)
    area = serializers.IntegerField(required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6,
                                        required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6,
                                         required=False)
    radius = serializers.DecimalField(max_digits=6, decimal_places=2,
                                      required=False, min_value=0)
    check_in = serializers.DateField(required=False)
    check_out = serializers.DateField(required=False)
    guests = serializers.IntegerField(min_value=1, required=False)
    bedrooms = serializers.IntegerField(min_value=0, required=False)
    bathrooms = serializers.DecimalField(max_digits=3, decimal_places=1,
                                         min_value=0, required=False)
    property_type = serializers.IntegerField(required=False)
    amenities = serializers.ListField(child=serializers.IntegerField(),
                                      required=False)
    min_price = serializers.DecimalField(max_digits=12, decimal_places=2,
                                         min_value=0, required=False)
    max_price = serializers.DecimalField(max_digits=12, decimal_places=2,
                                         min_value=0, required=False)
    min_rating = serializers.DecimalField(max_digits=3, decimal_places=2,
                                          min_value=0, max_value=5,
                                          required=False)
    verified_host = serializers.BooleanField(required=False)
    sort = serializers.ChoiceField(
        choices=["relevance", "price_asc", "price_desc", "rating", "newest"],
        required=False, default="relevance",
    )

    def validate(self, attrs):
        check_in, check_out = attrs.get("check_in"), attrs.get("check_out")
        if bool(check_in) != bool(check_out):
            raise serializers.ValidationError(
                "check_in and check_out must be provided together."
            )
        if check_in and check_out and check_in >= check_out:
            raise serializers.ValidationError("check_out must be after check_in.")
        return attrs
