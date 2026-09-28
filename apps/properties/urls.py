from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "properties"

router = DefaultRouter()
router.register("", views.PropertyViewSet, basename="property")

urlpatterns = [
    path("types/", views.PropertyTypeListView.as_view(), name="types"),
    path("amenity-categories/", views.AmenityCategoryListView.as_view(), name="amenity-categories"),
    path("amenities/", views.AmenityListView.as_view(), name="amenities"),
] + router.urls
