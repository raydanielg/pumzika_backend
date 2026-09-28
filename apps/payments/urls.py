from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("providers/", views.ProviderListView.as_view(), name="providers"),
    path("initiate/", views.InitiatePaymentView.as_view(), name="initiate"),
    path("mine/", views.MyPaymentsView.as_view(), name="mine"),
    path("<uuid:pk>/", views.PaymentDetailView.as_view(), name="detail"),
    path("<uuid:pk>/receipt/", views.PaymentReceiptView.as_view(), name="receipt"),
    path("webhooks/<str:provider>/", views.ProviderWebhookView.as_view(), name="webhook"),
    path("refunds/", views.AdminRefundListView.as_view(), name="refunds"),
    path("refunds/mine/", views.MyRefundsView.as_view(), name="my-refunds"),
    path("refunds/create/", views.AdminRefundView.as_view(), name="refund-create"),
    path("admin/", views.AdminPaymentListView.as_view(), name="admin-list"),
    path("admin/reconcile/", views.AdminPaymentReconcileView.as_view(),
         name="admin-reconcile"),
]
