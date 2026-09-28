from django.urls import path

from . import views

app_name = "search"

urlpatterns = [
    path("properties/", views.PropertySearchView.as_view(), name="properties"),
    path("match/", views.MatchView.as_view(), name="match"),
    path("match/preferences/", views.MatchPreferencesView.as_view(),
         name="match-preferences"),
]
