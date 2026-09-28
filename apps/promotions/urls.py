from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "promotions"

router = DefaultRouter()
router.register("manage", views.PromotionViewSet, basename="promotion-manage")

urlpatterns = [
    path("validate/", views.ValidatePromoView.as_view(), name="validate"),
    path("active/", views.PromotionListPublicView.as_view(), name="active"),
] + router.urls
