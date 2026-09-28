"""Root URL configuration — versioned API under /api/v1/."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts.urls import auth_urlpatterns, user_urlpatterns
from apps.common.views import (
    HealthDBView,
    HealthLiveView,
    HealthReadyView,
    HealthRedisView,
    HealthView,
)

api_v1 = [
    path("auth/", include((auth_urlpatterns, "accounts"), namespace="auth")),
    path("users/", include((user_urlpatterns, "accounts"), namespace="users")),
    path("locations/", include("apps.locations.urls")),
    path("properties/", include("apps.properties.urls")),
    path("availability/", include("apps.availability.urls")),
    path("search/", include("apps.search.urls")),
    path("bookings/", include("apps.bookings.urls")),
    path("payments/", include("apps.payments.urls")),
    path("payouts/", include("apps.payouts.urls")),
    path("kyc/", include("apps.kyc.urls")),
    path("reviews/", include("apps.reviews.urls")),
    path("messages/", include("apps.messaging.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("favorites/", include("apps.favorites.urls")),
    path("promotions/", include("apps.promotions.urls")),
    path("disputes/", include("apps.disputes.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("admin/", include("apps.admin_panel.urls")),
    path("admin/security/", include("apps.security.urls")),
]

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("health/db/", HealthDBView.as_view(), name="health-db"),
    path("health/redis/", HealthRedisView.as_view(), name="health-redis"),
    path("health/live/", HealthLiveView.as_view(), name="health-live"),
    path("health/ready/", HealthReadyView.as_view(), name="health-ready"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
