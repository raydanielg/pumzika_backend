"""Object-level permissions for properties."""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsPropertyHostOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff_role or user.is_superuser:
            return True
        return obj.host_id == user.id


class PublicReadOrHostWrite(BasePermission):
    """Guests may read PUBLISHED listings; only hosts may create/edit."""

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.has_perm_code("properties.create")
        )
