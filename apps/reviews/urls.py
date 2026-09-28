from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("properties/<uuid:property_id>/", views.PropertyReviewListView.as_view(),
         name="property-reviews"),
    path("property/", views.CreatePropertyReviewView.as_view(), name="create-property"),
    path("host/", views.CreateHostReviewView.as_view(), name="create-host"),
    path("guest/", views.CreateGuestReviewView.as_view(), name="create-guest"),
    path("hosts/<uuid:host_id>/", views.HostReviewsView.as_view(), name="host-reviews"),
    path("moderate/<str:review_type>/<uuid:pk>/", views.ModerateReviewView.as_view(),
         name="moderate"),
]
