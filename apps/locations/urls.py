from django.urls import path

from . import views

app_name = "locations"

urlpatterns = [
    path("countries/", views.CountryListView.as_view(), name="countries"),
    path("regions/", views.RegionListView.as_view(), name="regions"),
    path("cities/", views.CityListView.as_view(), name="cities"),
    path("districts/", views.DistrictListView.as_view(), name="districts"),
    path("areas/", views.AreaListView.as_view(), name="areas"),
]
