"""Property API — public browse + host management."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import decorators, filters, generics, status, viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.common.schema import schema_empty_queryset
from apps.accounts.constants import PROPERTY_CREATE
from apps.common.exceptions import NotFoundError
from apps.common.permissions import PermissionRequired
from apps.admin_panel.services import audit

from .models import Amenity, AmenityCategory, Property, PropertyType
from .permissions import IsPropertyHostOrStaff, PublicReadOrHostWrite
from . import services
from .serializers import (
    AmenityCategorySerializer,
    AmenitySerializer,
    ImageOrderSerializer,
    PropertyCreateSerializer,
    PropertyHostSerializer,
    PropertyImageSerializer,
    PropertyPricingSerializer,
    PropertyPublicSerializer,
    PropertyRuleSerializer,
    PropertyUnitSerializer,
    PropertyTypeSerializer,
)


class PropertyTypeListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PropertyTypeSerializer
    queryset = PropertyType.objects.filter(is_active=True)
    pagination_class = None


class AmenityCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = AmenityCategorySerializer
    queryset = AmenityCategory.objects.all()
    pagination_class = None


class AmenityListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = AmenitySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category"]
    search_fields = ["name"]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        return Amenity.objects.filter(is_active=True).select_related("category")


@extend_schema(
    parameters=[
        OpenApiParameter("image_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
        OpenApiParameter("rule_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
        OpenApiParameter("pricing_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
        OpenApiParameter("unit_id", OpenApiTypes.UUID, OpenApiParameter.PATH),
    ]
)
class PropertyViewSet(viewsets.ModelViewSet):
    """Public list/detail shows only PUBLISHED properties.

    Hosts manage their own listings through the same viewset — the queryset
    and serializer switch based on role.
    """

    permission_classes = [PublicReadOrHostWrite]
    required_permissions = (PROPERTY_CREATE,)
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["country", "city", "property_type"]
    ordering_fields = ["created_at", "base_price", "rating"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        qs = (
            Property.objects.select_related(
                "host", "host__host_profile", "property_type",
                "country", "region", "city", "district", "area",
            )
            .prefetch_related("images", "amenities__category")
        )
        user = self.request.user
        mine = self.request.query_params.get("mine") == "true"
        if user.is_authenticated and (mine or self.action in {
            "update", "partial_update", "destroy", "submit_review", "archive",
            "publish", "unpublish",
            "images", "delete_image", "set_cover", "reorder_images",
            "rules", "delete_rule", "special_pricings", "delete_special_pricing",
        }):
            return qs.filter(host=user)
        if user.is_authenticated and user.is_staff_role:
            return qs
        return qs.filter(status=Property.Status.PUBLISHED)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return PropertyCreateSerializer
        user = self.request.user
        obj = getattr(self, "_resolved_obj", None)
        if user.is_authenticated and (
            user.is_staff_role or (obj and obj.host_id == user.id)
        ):
            return PropertyHostSerializer
        return PropertyPublicSerializer

    def get_object(self):
        # Public URLs use the readable slug; hosts/admin may still use the UUID.
        lookup = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        if lookup and self.action == "retrieve":
            qs = self.filter_queryset(self.get_queryset())
            obj = None
            try:
                import uuid as _uuid

                obj = qs.filter(pk=_uuid.UUID(str(lookup))).first()
            except (ValueError, AttributeError, TypeError):
                pass
            if obj is None:
                obj = qs.filter(slug=lookup).first()
            if obj is None:
                raise NotFoundError(
                    "Property not found.", code="PROPERTY_NOT_FOUND"
                )
            self.check_object_permissions(self.request, obj)
            self._resolved_obj = obj
            return obj
        obj = super().get_object()
        self._resolved_obj = obj
        return obj

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        amenity_ids = data.pop("amenity_ids", None)
        prop = services.create_property(self.request.user, data, amenity_ids)
        audit(actor=self.request.user, action="property.created",
              target=prop, request=self.request)
        self._created = prop

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            PropertyHostSerializer(self._created).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        prop = self.get_object()
        self.check_object_permissions(self.request, prop)
        data = dict(serializer.validated_data)
        amenity_ids = data.pop("amenity_ids", None)
        services.update_property(prop, data, amenity_ids)
        audit(actor=self.request.user, action="property.updated",
              target=prop, request=self.request)

    def update(self, request, *args, **kwargs):
        prop = self.get_object()
        IsPropertyHostOrStaff().has_object_permission(request, self, prop) or self.permission_denied(request)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        prop = self.get_object()
        if prop.host_id != request.user.id and not request.user.is_staff_role:
            self.permission_denied(request)
        services.archive_property(prop)
        audit(actor=request.user, action="property.archived", target=prop, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ---- host actions -----------------------------------------------------

    @decorators.action(detail=True, methods=["post"])
    def submit_review(self, request, pk=None):
        prop = services.submit_for_review(self.get_object())
        audit(actor=request.user, action="property.submitted_review",
              target=prop, request=request)
        return Response(PropertyHostSerializer(prop).data)

    @decorators.action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        prop = services.archive_property(self.get_object())
        audit(actor=request.user, action="property.archived", target=prop, request=request)
        return Response(PropertyHostSerializer(prop).data)

    @decorators.action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """Host publishes an APPROVED listing."""
        prop = services.publish_property(self.get_object())
        audit(actor=request.user, action="property.published",
              target=prop, request=request)
        return Response(PropertyHostSerializer(prop).data)

    @decorators.action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        prop = services.unpublish_property(self.get_object())
        audit(actor=request.user, action="property.unpublished",
              target=prop, request=request)
        return Response(PropertyHostSerializer(prop).data)

    # ---- images ------------------------------------------------------------

    @decorators.action(
        detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser]
    )
    def images(self, request, pk=None):
        prop = self.get_object()
        image_file = request.FILES.get("image")
        if image_file is None:
            raise NotFoundError("No image file provided.", code="IMAGE_REQUIRED")
        image = services.add_image(prop, image_file, request.data.get("caption", ""))
        return Response(PropertyImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["delete"], url_path="images/(?P<image_id>[^/.]+)")
    def delete_image(self, request, pk=None, image_id=None):
        services.delete_image(self.get_object(), image_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=["post"], url_path="images/(?P<image_id>[^/.]+)/cover")
    def set_cover(self, request, pk=None, image_id=None):
        image = services.set_cover_image(self.get_object(), image_id)
        return Response(PropertyImageSerializer(image).data)

    @decorators.action(detail=True, methods=["post"], url_path="images/reorder")
    def reorder_images(self, request, pk=None):
        serializer = ImageOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reorder_images(self.get_object(),
                                [str(i) for i in serializer.validated_data["ordered_ids"]])
        return Response({"detail": "Images reordered."})

    # ---- rules & pricing ----------------------------------------------------

    @decorators.action(detail=True, methods=["post"])
    def rules(self, request, pk=None):
        prop = self.get_object()
        serializer = PropertyRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = prop.rules.create(**serializer.validated_data)
        return Response(PropertyRuleSerializer(rule).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["delete"], url_path="rules/(?P<rule_id>[^/.]+)")
    def delete_rule(self, request, pk=None, rule_id=None):
        self.get_object().rules.filter(pk=rule_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=["post"])
    def special_pricings(self, request, pk=None):
        prop = self.get_object()
        serializer = PropertyPricingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pricing = prop.special_pricings.create(**serializer.validated_data)
        return Response(PropertyPricingSerializer(pricing).data,
                        status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["delete"],
                       url_path="special-pricings/(?P<pricing_id>[^/.]+)")
    def delete_special_pricing(self, request, pk=None, pricing_id=None):
        self.get_object().special_pricings.filter(pk=pricing_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # — Units (rooms/beds inside a multi-unit property) —

    @decorators.action(detail=True, methods=["get", "post"])
    def units(self, request, pk=None):
        prop = self.get_object()
        if request.method == "GET":
            units = prop.units.all()
            return Response(PropertyUnitSerializer(units, many=True).data)
        IsPropertyHostOrStaff().has_object_permission(request, self, prop)             or self.permission_denied(request)
        serializer = PropertyUnitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unit = prop.units.create(**serializer.validated_data)
        return Response(PropertyUnitSerializer(unit).data,
                        status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["patch", "delete"],
                       url_path="units/(?P<unit_id>[^/.]+)")
    def unit_detail(self, request, pk=None, unit_id=None):
        prop = self.get_object()
        IsPropertyHostOrStaff().has_object_permission(request, self, prop)             or self.permission_denied(request)
        unit = prop.units.filter(pk=unit_id).first()
        if unit is None:
            raise NotFoundError("Unit not found.", code="UNIT_NOT_FOUND")
        if request.method == "DELETE":
            unit.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = PropertyUnitSerializer(unit, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PropertyDetailById(generics.RetrieveAPIView):
    """Alias: public detail of a published property."""

    permission_classes = [AllowAny]
    serializer_class = PropertyPublicSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        return (
            Property.objects.filter(status=Property.Status.PUBLISHED)
            .select_related("host__host_profile", "property_type", "country",
                            "region", "city", "district", "area")
            .prefetch_related("images", "amenities__category")
        )
