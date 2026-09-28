"""Search endpoint — public, paginated, only bookable properties."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import AnalyticsEvent
from apps.properties.serializers import PropertyPublicSerializer

from .matching import PREFERENCE_KEYWORDS, match_stays, suggest_adjustments
from .serializers import MatchRequestSerializer, SearchParamsSerializer
from .services import search_properties


class PropertySearchView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PropertyPublicSerializer

    def get_queryset(self):
        params = SearchParamsSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        return search_properties(params.validated_data)


class MatchedPropertySerializer(PropertyPublicSerializer):
    """Public property payload + match metadata."""
    match_label = drf_serializers.CharField()
    match_reasons = drf_serializers.ListField(
        child=drf_serializers.CharField())
    total_price = drf_serializers.CharField(allow_null=True)

    class Meta(PropertyPublicSerializer.Meta):
        fields = PropertyPublicSerializer.Meta.fields + [
            "match_label", "match_reasons", "total_price",
        ]


class MatchView(APIView):
    """POST /api/v1/search/match/ — Smart Stay Match.

    Deterministic matching over live inventory: destination, dates,
    guests, budget and stay-style preferences. Availability and prices
    always come from the real inventory and pricing services.
    """

    permission_classes = [AllowAny]
    throttle_scope = "match"
    serializer_class = MatchRequestSerializer

    @extend_schema(
        tags=["search"],
        summary="Find stays that fit a trip",
        request=MatchRequestSerializer,
        responses={200: MatchedPropertySerializer(many=True)},
    )
    def post(self, request):
        params = MatchRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        page, page_size = data["page"], data["page_size"]
        results = match_stays(data, limit=100)
        total = len(results)
        start, end = (page - 1) * page_size, page * page_size
        items = results[start:end]

        payload = []
        for m in items:
            row = PropertyPublicSerializer(m.property).data
            row["match_label"] = m.label
            row["match_reasons"] = m.reasons
            row["total_price"] = (
                str(m.total_price) if m.total_price is not None else None
            )
            payload.append(row)

        AnalyticsEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            event_type="smart_match_search",
            session_id=request.headers.get("X-Session-ID", "")[:64],
            metadata={
                "destination": data.get("destination", ""),
                "guests": data["guests"],
                "preferences": data.get("preferences") or [],
                "results": total,
                "request_id": getattr(request, "request_id", ""),
            },
        )

        return Response({
            "results": payload,
            "count": total,
            "page": page,
            "page_size": page_size,
            "suggestions": suggest_adjustments(data) if total == 0 else [],
            "preferences_available": sorted(PREFERENCE_KEYWORDS),
        })


class MatchPreferencesView(APIView):
    """GET /api/v1/search/match/preferences/ — valid preference keys."""

    permission_classes = [AllowAny]
    serializer_class = None

    @extend_schema(
        tags=["search"],
        summary="List stay-style preferences",
        responses={200: inline_serializer(
            name="MatchPreferences",
            fields={
                "preferences": drf_serializers.ListField(
                    child=drf_serializers.CharField())
            },
        )},
    )
    def get(self, request):
        return Response({"preferences": sorted(PREFERENCE_KEYWORDS)})
