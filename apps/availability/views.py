"""Availability/calendar endpoints."""
from __future__ import annotations

from datetime import date

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import NotFoundError, PermissionDeniedError
from apps.properties.models import Property

from . import services
from .serializers import (
    BlockDatesSerializer,
    CalendarDaySerializer,
    CalendarQuerySerializer,
    DatePricingSerializer,
    DateRangeSerializer,
)


def _get_property_for_calendar(property_id):
    prop = Property.objects.filter(pk=property_id).first()
    if prop is None:
        raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
    return prop


def _get_host_property(request, property_id):
    prop = _get_property_for_calendar(property_id)
    if prop.host_id != request.user.id and not request.user.is_staff_role:
        raise PermissionDeniedError("You do not own this property.")
    return prop


class CalendarView(APIView):
    """Public calendar — guests see busy/free days to plan a stay."""

    permission_classes = [AllowAny]

    def get(self, request, property_id):
        prop = _get_property_for_calendar(property_id)
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_calendar(
            prop,
            query.validated_data["start_date"],
            query.validated_data["end_date"],
        )
        return Response(CalendarDaySerializer(data, many=True).data)


class BlockDatesView(APIView):
    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = BlockDatesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.block_dates(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
            serializer.validated_data.get("reason", ""),
        )
        return Response({"blocked": count})


class UnblockDatesView(APIView):
    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = DateRangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.unblock_dates(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
        )
        return Response({"unblocked": count})


class DatePricingView(APIView):
    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = DatePricingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.set_date_pricing(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
            serializer.validated_data["price"],
            serializer.validated_data.get("min_nights"),
        )
        return Response({"updated": count})
