from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "bookings"

router = DefaultRouter()
router.register("", views.BookingViewSet, basename="booking")

urlpatterns = [
    path("quote/", views.BookingQuoteView.as_view(), name="quote"),
    path("cancellation-policies/", views.CancellationPolicyListView.as_view(),
         name="cancellation-policies"),
] + router.urls
