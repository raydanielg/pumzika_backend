from django.urls import path

from . import views

app_name = "disputes"

urlpatterns = [
    path("", views.MyDisputesView.as_view(), name="mine"),
    path("create/", views.DisputeCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.DisputeDetailView.as_view(), name="detail"),
    path("<uuid:pk>/messages/", views.DisputeMessageView.as_view(), name="message"),
    path("<uuid:pk>/evidence/", views.DisputeEvidenceView.as_view(), name="evidence"),
    path("staff/", views.StaffDisputeListView.as_view(), name="staff-list"),
    path("staff/<uuid:pk>/status/", views.StaffDisputeStatusView.as_view(),
         name="staff-status"),
    path("staff/<uuid:pk>/resolve/", views.StaffDisputeResolveView.as_view(),
         name="staff-resolve"),
]
