from django.urls import path

from . import views

app_name = "payouts"

urlpatterns = [
    path("wallet/", views.MyWalletView.as_view(), name="wallet"),
    path("wallet/transactions/", views.MyWalletTransactionsView.as_view(), name="wallet-transactions"),
    path("methods/", views.PayoutMethodViewSet.as_view(), name="methods"),
    path("methods/<uuid:pk>/", views.PayoutMethodDetailView.as_view(), name="method-detail"),
    path("mine/", views.MyPayoutsView.as_view(), name="mine"),
    path("request/", views.RequestPayoutView.as_view(), name="request"),
    path("admin/", views.AdminPayoutListView.as_view(), name="admin-list"),
    path("admin/<uuid:pk>/process/", views.AdminPayoutProcessView.as_view(), name="admin-process"),
]
