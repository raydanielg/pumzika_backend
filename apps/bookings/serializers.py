"""Booking serializers."""
from __future__ import annotations

from datetime import date

from rest_framework import serializers

from .models import (
    Booking,
    BookingCancellation,
    BookingEvent,
    BookingGuest,
    BookingNote,
    BookingPrice,
    BookingStatusHistory,
    CancellationPolicy,
    CancellationRule,
)


class CancellationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CancellationRule
        fields = ["hours_before_check_in", "guest_refund_percent", "refund_service_fee"]


class CancellationPolicySerializer(serializers.ModelSerializer):
    rules = CancellationRuleSerializer(many=True, read_only=True)

    class Meta:
        model = CancellationPolicy
        fields = ["id", "name", "code", "description", "rules"]
        read_only_fields = ["id"]


class BookingGuestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingGuest
        fields = ["first_name", "last_name", "is_primary"]


class BookingPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingPrice
        fields = [
            "currency", "nights", "nightly_subtotal", "cleaning_fee",
            "service_fee", "tax", "discount", "total",
            "nightly_detail",
        ]
        # commission/host payout are internal — see HostBookingPriceSerializer


class HostBookingPriceSerializer(BookingPriceSerializer):
    """Hosts see the commission math; guests do not."""

    class Meta(BookingPriceSerializer.Meta):
        fields = BookingPriceSerializer.Meta.fields + [
            "commission_rate", "commission_amount", "host_payout_amount",
        ]


class BookingStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class BookingCancellationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingCancellation
        fields = ["reason", "cancelled_at", "refund_amount", "host_amount"]


class _BookingEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingEvent
        fields = ["event_type", "note", "data", "created_at"]
        read_only_fields = fields


class BookingSerializer(serializers.ModelSerializer):
    price = BookingPriceSerializer(read_only=True)
    guests = BookingGuestSerializer(many=True, read_only=True)
    property_title = serializers.CharField(source="property.title", read_only=True)
    property_city = serializers.CharField(source="property.city.name", read_only=True)
    guest_email = serializers.EmailField(source="guest.email", read_only=True)
    status_history = BookingStatusHistorySerializer(many=True, read_only=True)
    # Exact location is revealed only once the stay is confirmed.
    property_location = serializers.SerializerMethodField()

    events = _BookingEventSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "guest", "guest_email", "property",
            "property_title", "property_city", "property_location",
            "check_in", "check_out",
            "guests_count", "adults", "children", "infants",
            "status", "currency",
            "cancellation_policy_name", "cancellation_policy_snapshot",
            "promo_code", "special_requests",
            "expires_at", "confirmed_at", "cancelled_at",
            "checked_in_at", "completed_at",
            "price", "guests", "events", "status_history", "created_at",
        ]
        read_only_fields = fields

    def get_property_location(self, obj):
        if obj.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN,
                              Booking.Status.COMPLETED, Booking.Status.DISPUTED):
            return None
        prop = obj.property
        return {
            "address": prop.address,
            "latitude": str(prop.latitude) if prop.latitude is not None else None,
            "longitude": str(prop.longitude) if prop.longitude is not None else None,
        }


class HostBookingSerializer(BookingSerializer):
    price = HostBookingPriceSerializer(read_only=True)

    def get_property_location(self, obj):
        prop = obj.property
        return {
            "address": prop.address,
            "latitude": str(prop.latitude) if prop.latitude is not None else None,
            "longitude": str(prop.longitude) if prop.longitude is not None else None,
        }


class GuestDetailInputSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    is_primary = serializers.BooleanField(default=False)


class GuestBreakdownSerializer(serializers.Serializer):
    """Guests: {adults, children, infants} — infants don't count toward cap."""
    adults = serializers.IntegerField(min_value=0, default=1)
    children = serializers.IntegerField(min_value=0, default=0)
    infants = serializers.IntegerField(min_value=0, default=0)


class BookingCreateSerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    guests_count = serializers.IntegerField(
        min_value=1, required=False,
        help_text="Legacy — prefer the guests breakdown object.",
    )
    guests = GuestBreakdownSerializer(required=False)
    guest_details = GuestDetailInputSerializer(many=True, required=False)
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    special_requests = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["check_in"] >= attrs["check_out"]:
            raise serializers.ValidationError("check_out must be after check_in.")
        if attrs["check_in"] < date.today():
            raise serializers.ValidationError("check_in cannot be in the past.")
        if attrs.get("guests") is None and attrs.get("guests_count") is None:
            raise serializers.ValidationError(
                "Provide guests {adults, children, infants} or guests_count."
            )
        return attrs


class BookingNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(
        source="author.full_name", read_only=True, default=""
    )

    class Meta:
        model = BookingNote
        fields = ["id", "body", "is_internal", "author_name", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]


class BookingQuoteSerializer(serializers.Serializer):
    property_id = serializers.UUIDField()
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=50)


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
