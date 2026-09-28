"""Role-based DRF permissions for the accounts domain."""
from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import User


class IsHost(BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.HOST
        )


class IsStaff(BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(
            request.user and request.user.is_authenticated and request.user.is_staff_role
        )


class IsAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.ADMIN, User.Role.SUPER_ADMIN)
        )
