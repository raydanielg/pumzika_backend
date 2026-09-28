from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "admin_panel"

router = DefaultRouter()
router.register("settings", views.PlatformSettingViewSet, basename="setting")
router.register("commission-rules", views.CommissionRuleViewSet, basename="commission")
router.register("tax-rules", views.TaxRuleViewSet, basename="taxrule")
router.register("users", views.AdminUserViewSet, basename="admin-user")
router.register("countries", views.CountryViewSet, basename="country")
router.register("regions", views.RegionViewSet, basename="region")
router.register("cities", views.CityViewSet, basename="city")
router.register("districts", views.DistrictViewSet, basename="district")
router.register("areas", views.AreaViewSet, basename="area")
router.register("amenities", views.AmenityViewSet, basename="amenity")
router.register("amenity-categories", views.AmenityCategoryViewSet, basename="amenity-category")
router.register("property-types", views.PropertyTypeViewSet, basename="property-type")
router.register("notification-templates", views.NotificationTemplateViewSet, basename="notif-template")

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("audit-logs/", views.AuditLogListView.as_view(), name="audit-logs"),
    path("properties/", views.PendingPropertiesView.as_view(), name="properties"),
    path("properties/<uuid:pk>/approve/", views.PropertyApproveView.as_view(), name="approve"),
    path("properties/<uuid:pk>/reject/", views.PropertyRejectView.as_view(), name="reject"),
    path("properties/<uuid:pk>/suspend/", views.PropertySuspendView.as_view(), name="suspend"),
] + router.urls
