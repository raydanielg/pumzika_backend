"""Location browsing (public read) — management happens in admin_panel."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.permissions import AllowAny

from .models import Area, City, Country, District, Region
from .serializers import (
    AreaSerializer,
    CitySerializer,
    CountrySerializer,
    DistrictSerializer,
    RegionSerializer,
)


class CountryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CountrySerializer
    queryset = Country.objects.filter(is_active=True)
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "code"]
    pagination_class = None


class RegionListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["country"]
    search_fields = ["name"]

    def get_queryset(self):
        return Region.objects.filter(is_active=True).select_related("country")


class CityListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CitySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["region", "region__country"]
    search_fields = ["name"]

    def get_queryset(self):
        return City.objects.filter(is_active=True).select_related("region__country")


class DistrictListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = DistrictSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["city"]
    search_fields = ["name"]

    def get_queryset(self):
        return District.objects.filter(is_active=True).select_related("city")


class AreaListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = AreaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["district", "district__city"]
    search_fields = ["name"]

    def get_queryset(self):
        return Area.objects.filter(is_active=True).select_related("district__city")
