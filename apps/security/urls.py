from django.urls import path

from . import views

urlpatterns = [
    path("events/", views.SecurityEventListView.as_view(), name="sec-events"),
    path("incidents/", views.IncidentListView.as_view(), name="incidents"),
    path("incidents/<uuid:pk>/", views.IncidentDetailView.as_view(),
         name="incident-detail"),
    path("incidents/<uuid:pk>/transition/",
         views.IncidentTransitionView.as_view(), name="incident-transition"),
    path("monitoring/", views.SecurityMonitoringView.as_view(),
         name="monitoring"),
    path("users/<uuid:pk>/action/", views.SecuritySuspensionsView.as_view(),
         name="user-action"),
]
