from django.urls import path

from . import views

app_name = "availability"

urlpatterns = [
    path("<uuid:property_id>/calendar/", views.CalendarView.as_view(), name="calendar"),
    path("<uuid:property_id>/block/", views.BlockDatesView.as_view(), name="block"),
    path("<uuid:property_id>/unblock/", views.UnblockDatesView.as_view(), name="unblock"),
    path("<uuid:property_id>/pricing/", views.DatePricingView.as_view(), name="pricing"),
]
