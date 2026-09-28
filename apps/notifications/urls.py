from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("<uuid:pk>/", views.NotificationDetailView.as_view(), name="detail"),
    path("read/", views.MarkReadView.as_view(), name="read-all"),
    path("<uuid:pk>/read/", views.MarkReadView.as_view(), name="read-one"),
    path("unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("preferences/", views.PreferenceListUpdateView.as_view(), name="preferences"),
]
