from datetime import date
from decimal import Decimal

from rest_framework import serializers


class DateRangeSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    unit_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["start_date"] >= attrs["end_date"]:
            raise serializers.ValidationError("end_date must be after start_date.")
        if attrs["start_date"] < date.today():
            raise serializers.ValidationError("start_date cannot be in the past.")
        return attrs


class BlockDatesSerializer(DateRangeSerializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class DatePricingSerializer(DateRangeSerializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2,
                                     min_value=Decimal("0"))
    min_nights = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class CalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    status = serializers.CharField()
    price = serializers.CharField()
    min_nights = serializers.IntegerField()


class CalendarQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    unit_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["start_date"] >= attrs["end_date"]:
            raise serializers.ValidationError("end_date must be after start_date.")
        if (attrs["end_date"] - attrs["start_date"]).days > 370:
            raise serializers.ValidationError("Range cannot exceed 370 days.")
        return attrs
