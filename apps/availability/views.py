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


def _resolve_unit(prop, unit_id):
    if not unit_id:
        return None
    unit = prop.units.filter(pk=unit_id).first()
    if unit is None:
        raise NotFoundError("Unit not found.", code="UNIT_NOT_FOUND")
    return unit


class CalendarView(APIView):
    """Public calendar — guests see busy/free days to plan a stay."""

    permission_classes = [AllowAny]
    serializer_class = CalendarDaySerializer

    def get(self, request, property_id):
        prop = _get_property_for_calendar(property_id)
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        unit = _resolve_unit(prop, request.query_params.get("unit_id"))
        data = services.get_calendar(
            prop,
            query.validated_data["start_date"],
            query.validated_data["end_date"],
            unit=unit,
        )
        return Response(CalendarDaySerializer(data, many=True).data)


class BlockDatesView(APIView):
    serializer_class = BlockDatesSerializer

    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = BlockDatesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unit = _resolve_unit(prop, serializer.validated_data.get("unit_id"))
        count = services.block_dates(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
            serializer.validated_data.get("reason", ""),
            unit=unit,
        )
        return Response({"blocked": count})


class UnblockDatesView(APIView):
    serializer_class = DateRangeSerializer

    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = DateRangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unit = _resolve_unit(prop, serializer.validated_data.get("unit_id"))
        count = services.unblock_dates(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
            unit=unit,
        )
        return Response({"unblocked": count})


class DatePricingView(APIView):
    serializer_class = DatePricingSerializer

    def post(self, request, property_id):
        prop = _get_host_property(request, property_id)
        serializer = DatePricingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unit = _resolve_unit(prop, serializer.validated_data.get("unit_id"))
        count = services.set_date_pricing(
            prop,
            serializer.validated_data["start_date"],
            serializer.validated_data["end_date"],
            serializer.validated_data["price"],
            serializer.validated_data.get("min_nights"),
            unit=unit,
        )
        return Response({"updated": count})
