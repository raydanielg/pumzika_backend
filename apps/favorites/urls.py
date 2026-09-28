from django.urls import path

from . import views

app_name = "favorites"

urlpatterns = [
    path("", views.FavoriteListView.as_view(), name="list"),
    path("add/", views.FavoriteAddView.as_view(), name="add"),
    path("<uuid:property_id>/", views.FavoriteRemoveView.as_view(), name="remove"),
    path("<uuid:property_id>/check/", views.FavoriteCheckView.as_view(), name="check"),
]
