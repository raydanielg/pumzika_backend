from django.urls import path

from . import views

app_name = "accounts"

auth_urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("email/verify/", views.EmailVerifySendView.as_view(), name="email-verify"),
    path("email/verify/confirm/", views.EmailVerifyConfirmView.as_view(), name="email-verify-confirm"),
    path("phone/verify/", views.PhoneVerifySendView.as_view(), name="phone-verify"),
    path("phone/verify/confirm/", views.PhoneVerifyConfirmView.as_view(), name="phone-verify-confirm"),
    path("password/reset/", views.PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/confirm/", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password-change"),
]

user_urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("me/deactivate/", views.MeDeactivateView.as_view(), name="me-deactivate"),
    path("me/delete/", views.MeDeleteView.as_view(), name="me-delete"),
    path("me/host-profile/", views.MyHostProfileView.as_view(), name="me-host-profile"),
    path("me/sessions/", views.SessionListView.as_view(), name="me-sessions"),
    path("me/sessions/revoke-all/", views.SessionRevokeView.as_view(), name="me-sessions-revoke-all"),
    path("me/sessions/<str:jti>/revoke/", views.SessionRevokeView.as_view(), name="me-session-revoke"),
]
