"""Property search — only publicly-bookable properties are returned."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.properties.models import Property

BLOCKING = [
    AvailabilityStatus.UNAVAILABLE,
    AvailabilityStatus.BLOCKED,
    AvailabilityStatus.BOOKED,
    AvailabilityStatus.MAINTENANCE,
]

SORT_MAP = {
    "price_asc": "base_price",
    "price_desc": "-base_price",
    "rating": "-rating",
    "newest": "-created_at",
    "relevance": None,  # handled explicitly
}


def search_properties(params: dict) -> QuerySet:
    """Build the filtered queryset from validated query params."""
    qs = (
        Property.objects.filter(status=Property.Status.PUBLISHED)
        .select_related("property_type", "country", "region", "city",
                        "district", "area", "host__host_profile")
        .prefetch_related("images", "amenities")
    )

    # ---- destination / structured location --------------------------------
    destination = params.get("destination")
    if destination:
        qs = qs.filter(
            Q(title__icontains=destination)
            | Q(city__name__icontains=destination)
            | Q(region__name__icontains=destination)
            | Q(district__name__icontains=destination)
            | Q(area__name__icontains=destination)
        )
    for field, param in (("country", "country"), ("region", "region"),
                         ("city", "city"), ("district", "district"),
                         ("area", "area")):
        if params.get(param):
            qs = qs.filter(**{f"{field}_id": params[param]})

    # ---- geo radius (bounding box — upgrade to PostGIS for scale) ---------
    lat, lng, radius = params.get("latitude"), params.get("longitude"), params.get("radius")
    if lat is not None and lng is not None:
        radius = Decimal(str(radius or 10))  # km
        lat_d = Decimal(str(lat))
        lng_d = Decimal(str(lng))
        lat_delta = radius / Decimal("111")
        import math

        lng_delta = radius / (Decimal("111") * Decimal(str(math.cos(math.radians(float(lat_d))))) or Decimal("1"))
        qs = qs.filter(
            latitude__gte=lat_d - lat_delta, latitude__lte=lat_d + lat_delta,
            longitude__gte=lng_d - lng_delta, longitude__lte=lng_d + lng_delta,
        )

    # ---- stay filters ------------------------------------------------------
    if params.get("guests"):
        qs = qs.filter(max_guests__gte=params["guests"])
    if params.get("bedrooms"):
        qs = qs.filter(bedrooms__gte=params["bedrooms"])
    if params.get("bathrooms"):
        qs = qs.filter(bathrooms__gte=params["bathrooms"])
    if params.get("property_type"):
        qs = qs.filter(property_type_id=params["property_type"])
    if params.get("amenities"):
        for amenity_id in params["amenities"]:
            qs = qs.filter(amenities__id=amenity_id)
        qs = qs.distinct()
    if params.get("min_price") is not None:
        qs = qs.filter(base_price__gte=params["min_price"])
    if params.get("max_price") is not None:
        qs = qs.filter(base_price__lte=params["max_price"])
    if params.get("min_rating"):
        qs = qs.filter(rating__gte=params["min_rating"])
    if params.get("verified_host"):
        qs = qs.filter(host__host_profile__verification_status="VERIFIED")

    # ---- date availability -------------------------------------------------
    check_in, check_out = params.get("check_in"), params.get("check_out")
    if check_in and check_out:
        blocked_ids = AvailabilityDate.objects.filter(
            date__gte=check_in, date__lt=check_out, status__in=BLOCKING
        ).values("property_id")
        qs = qs.exclude(id__in=blocked_ids)
        qs = qs.filter(min_nights__lte=(check_out - check_in).days)
        qs = qs.filter(
            Q(max_nights__isnull=True)
            | Q(max_nights__gte=(check_out - check_in).days)
        )

    # ---- sorting ------------------------------------------------------------
    sort = params.get("sort") or "relevance"
    if sort == "relevance":
        qs = qs.order_by("-rating", "-review_count", "-created_at")
    elif sort in SORT_MAP:
        qs = qs.order_by(SORT_MAP[sort])
    else:
        qs = qs.order_by("-created_at")
    return qs
