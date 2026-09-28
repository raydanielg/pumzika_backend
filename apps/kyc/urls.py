from django.urls import path

from . import views

app_name = "kyc"

urlpatterns = [
    path("me/", views.MyKYCProfileView.as_view(), name="me"),
    path("me/documents/", views.MyKYCDocumentListView.as_view(), name="documents"),
    path("me/documents/upload/", views.MyKYCDocumentView.as_view(), name="document-upload"),
    path("me/submit/", views.MyKYCSubmitView.as_view(), name="submit"),
    path("me/history/", views.MyKYCHistoryView.as_view(), name="history"),
    path("verifications/", views.StaffVerificationListView.as_view(), name="verifications"),
    path("verifications/<uuid:pk>/", views.StaffVerificationDetailView.as_view(), name="verification-detail"),
    path("verifications/<uuid:pk>/review/", views.StaffVerificationReviewView.as_view(), name="verification-review"),
]
