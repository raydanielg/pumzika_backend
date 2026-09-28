"""Admin API — configuration, moderation, user management, metrics.

All endpoints require granular permission codes, not just role checks.
"""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import decorators, filters, generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import constants as perms
from apps.accounts.models import User
from apps.analytics.services import dashboard_metrics
from apps.common.exceptions import NotFoundError
from apps.common.permissions import PermissionRequired
from apps.locations.models import Area, City, Country, District, Region
from apps.notifications.models import NotificationTemplate
from apps.properties import services as property_services
from apps.properties.models import Amenity, AmenityCategory, Property, PropertyType
from apps.properties.serializers import PropertyHostSerializer

from .models import AuditLog, CommissionRule, PlatformSetting, TaxRule
from .serializers import (
    AdminUserSerializer,
    AmenityAdminSerializer,
    AmenityCategoryAdminSerializer,
    AreaAdminSerializer,
    AuditLogSerializer,
    CityAdminSerializer,
    CommissionRuleSerializer,
    CountryAdminSerializer,
    DistrictAdminSerializer,
    NotificationTemplateAdminSerializer,
    PlatformSettingSerializer,
    PropertyModerationSerializer,
    PropertyTypeAdminSerializer,
    RegionAdminSerializer,
    TaxRuleSerializer,
    UserRoleUpdateSerializer,
)
from .services import audit


class DashboardView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.ANALYTICS_VIEW,)
    serializer_class = PlatformSettingSerializer  # docs hint only

    def get(self, request):
        return Response(dashboard_metrics())


class AuditLogListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.AUDIT_VIEW,)
    serializer_class = AuditLogSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["action", "actor", "target_type"]
    search_fields = ["action", "target_id"]

    def get_queryset(self):
        return AuditLog.objects.select_related("actor")


class PlatformSettingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.SETTINGS_UPDATE,)
    serializer_class = PlatformSettingSerializer
    queryset = PlatformSetting.objects.all()

    def perform_create(self, serializer):
        obj = serializer.save()
        audit(actor=self.request.user, action="settings.created", target=obj,
              request=self.request, after=serializer.data)

    def perform_update(self, serializer):
        before = PlatformSettingSerializer(self.get_object()).data
        obj = serializer.save()
        audit(actor=self.request.user, action="settings.updated", target=obj,
              request=self.request, before=before, after=serializer.data)


class CommissionRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.SETTINGS_UPDATE,)
    serializer_class = CommissionRuleSerializer
    queryset = CommissionRule.objects.select_related("country", "property_type", "host")


class TaxRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.TAX_MANAGE,)
    serializer_class = TaxRuleSerializer
    queryset = TaxRule.objects.select_related("country")


class AdminUserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.USER_VIEW,)
    action_permissions = {
        "role": (perms.USER_MANAGE,),
        "deactivate": (perms.USER_MANAGE,),
        "activate": (perms.USER_MANAGE,),
    }
    serializer_class = AdminUserSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["role", "is_active", "is_email_verified"]
    search_fields = ["email", "phone", "first_name", "last_name"]
    ordering_fields = ["created_at", "last_login", "email"]

    def get_queryset(self):
        return User.objects.select_related("country").order_by("-created_at")

    @decorators.action(detail=True, methods=["post"])
    def role(self, request, pk=None):
        user = self.get_object()
        serializer = UserRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = {"role": user.role}
        user.role = serializer.validated_data["role"]
        user.is_staff = user.is_staff_role
        user.save(update_fields=["role", "is_staff", "updated_at"])
        audit(actor=request.user, action="user.role_changed", target=user,
              request=request, before=before, after={"role": user.role})
        return Response(AdminUserSerializer(user).data)

    @decorators.action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        user.deactivate()
        audit(actor=request.user, action="user.deactivated_by_admin",
              target=user, request=request)
        return Response({"detail": "User deactivated."})

    @decorators.action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])
        audit(actor=request.user, action="user.activated_by_admin",
              target=user, request=request)
        return Response({"detail": "User activated."})


class PendingPropertiesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.PROPERTY_VIEW_ALL,)
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "country", "property_type"]

    serializer_class = PropertyHostSerializer

    def get_queryset(self):
        qs = Property.objects.select_related(
            "host", "property_type", "city", "country"
        ).prefetch_related("images")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            return qs.filter(status=status_filter).order_by("-created_at")
        return qs.order_by("-created_at")


class PropertyApproveView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.PROPERTY_APPROVE,)
    serializer_class = PropertyModerationSerializer

    def post(self, request, pk):
        prop = Property.objects.filter(pk=pk).first()
        if prop is None:
            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        prop = property_services.approve_property(prop, admin=request.user)
        audit(actor=request.user, action="property.approved", target=prop,
              request=request)
        return Response({"status": prop.status})


class PropertyRejectView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.PROPERTY_APPROVE,)
    serializer_class = PropertyModerationSerializer

    def post(self, request, pk):
        prop = Property.objects.filter(pk=pk).first()
        if prop is None:
            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        reason = request.data.get("reason", "")
        prop = property_services.reject_property(prop, reason)
        audit(actor=request.user, action="property.rejected", target=prop,
              request=request, metadata={"reason": reason})
        return Response({"status": prop.status})


class PropertySuspendView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.PROPERTY_SUSPEND,)
    serializer_class = PropertyModerationSerializer

    def post(self, request, pk):
        prop = Property.objects.filter(pk=pk).first()
        if prop is None:
            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        reason = request.data.get("reason", "")
        prop = property_services.suspend_property(prop, reason)
        audit(actor=request.user, action="property.suspended", target=prop,
              request=request, metadata={"reason": reason})
        return Response({"status": prop.status})


# ---------------------------------------------------------------------------
# Admin CRUD for configuration data
# ---------------------------------------------------------------------------

class CountryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.LOCATION_MANAGE,)
    serializer_class = CountryAdminSerializer
    queryset = Country.objects.all()


class RegionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.LOCATION_MANAGE,)
    serializer_class = RegionAdminSerializer
    queryset = Region.objects.select_related("country")
    filterset_fields = ["country"]


class CityViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.LOCATION_MANAGE,)
    serializer_class = CityAdminSerializer
    queryset = City.objects.select_related("region__country")
    filterset_fields = ["region"]


class DistrictViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.LOCATION_MANAGE,)
    serializer_class = DistrictAdminSerializer
    queryset = District.objects.select_related("city")
    filterset_fields = ["city"]


class AreaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.LOCATION_MANAGE,)
    serializer_class = AreaAdminSerializer
    queryset = Area.objects.select_related("district__city")
    filterset_fields = ["district"]


class AmenityViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.AMENITY_MANAGE,)
    serializer_class = AmenityAdminSerializer
    queryset = Amenity.objects.select_related("category")
    filterset_fields = ["category", "is_active"]


class AmenityCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.AMENITY_MANAGE,)
    serializer_class = AmenityCategoryAdminSerializer
    queryset = AmenityCategory.objects.all()


class PropertyTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.AMENITY_MANAGE,)
    serializer_class = PropertyTypeAdminSerializer
    queryset = PropertyType.objects.all()


class NotificationTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (perms.NOTIFICATION_TEMPLATE_MANAGE,)
    serializer_class = NotificationTemplateAdminSerializer
    queryset = NotificationTemplate.objects.all()
