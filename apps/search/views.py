"""Search endpoint — public, paginated, only bookable properties."""
from __future__ import annotations

from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from apps.properties.serializers import PropertyPublicSerializer

from .serializers import SearchParamsSerializer
from .services import search_properties


class PropertySearchView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PropertyPublicSerializer

    def get_queryset(self):
        params = SearchParamsSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        return search_properties(params.validated_data)
