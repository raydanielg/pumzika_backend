"""Auth, registration, and permission-code tests."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User, VerificationCode


class AuthTests(APITestCase):
    def test_register_creates_guest_user(self):
        resp = self.client.post("/api/v1/auth/register/", {
            "email": "new@test.dev", "password": "Secret1234!",
            "first_name": "New", "last_name": "User",
        })
        assert resp.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email="new@test.dev")
        assert user.role == User.Role.GUEST
        assert "access" in resp.json()["data"]["tokens"]

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(
            email="dup@test.dev", password="Pass1234!",
            first_name="A", last_name="B",
        )
        resp = self.client.post("/api/v1/auth/register/", {
            "email": "dup@test.dev", "password": "Secret1234!",
            "first_name": "X", "last_name": "Y",
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error"]["code"] == "EMAIL_TAKEN"

    def test_login_returns_tokens(self):
        User.objects.create_user(
            email="login@test.dev", password="Pass1234!",
            first_name="A", last_name="B",
        )
        resp = self.client.post("/api/v1/auth/login/", {
            "email": "login@test.dev", "password": "Pass1234!",
        })
        assert resp.status_code == status.HTTP_200_OK
        assert "access" in resp.json()["data"]["tokens"]

    def test_login_rejects_bad_password(self):
        User.objects.create_user(
            email="bad@test.dev", password="Pass1234!",
            first_name="A", last_name="B",
        )
        resp = self.client.post("/api/v1/auth/login/", {
            "email": "bad@test.dev", "password": "wrong",
        })
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_email_verification_flow(self):
        user = User.objects.create_user(
            email="verify@test.dev", password="Pass1234!",
            first_name="A", last_name="B",
        )
        self.client.force_authenticate(user)
        self.client.post("/api/v1/auth/email/verify/")
        code_record = VerificationCode.objects.filter(
            user=user, purpose="EMAIL_VERIFY"
        ).latest("created_at")
        # consume_code checks the hash — craft via service for the raw code.
        from apps.accounts.services import confirm_email_verification
        import hashlib

        # find the OTP the code would hash to isn't feasible; issue a fresh one
        raw = "123456"
        code_record.code_hash = hashlib.sha256(raw.encode()).hexdigest()
        code_record.save()
        resp = self.client.post("/api/v1/auth/email/verify/confirm/", {"code": raw})
        assert resp.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.is_email_verified

    def test_me_requires_auth(self):
        resp = self.client.get("/api/v1/users/me/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_returns_profile(self):
        user = User.objects.create_user(
            email="me@test.dev", password="Pass1234!",
            first_name="M", last_name="E",
        )
        self.client.force_authenticate(user)
        resp = self.client.get("/api/v1/users/me/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["data"]["email"] == "me@test.dev"
