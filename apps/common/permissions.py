"""Granular permission enforcement.

Views declare ``required_permissions = ("properties.approve", ...)`` and use
:class:`PermissionRequired`. Codes are resolved against the user's role via
the database-driven RolePermission table (see apps.accounts).
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission


class PermissionRequired(BasePermission):
    """Requires the authenticated user to hold ALL required permission codes.

    ``view.required_permissions`` applies to the whole view. A view may also
    define ``action_permissions`` mapping action/method names to codes for
    finer-grained control (viewsets).
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        required = list(getattr(view, "required_permissions", ()))
        action_map = getattr(view, "action_permissions", {}) or {}
        action = getattr(view, "action", None)
        required += list(action_map.get(action, action_map.get(request.method, ())))
        return all(user.has_perm_code(code) for code in required)


class ReadOnlyOrPermission(PermissionRequired):
    """Safe methods allowed for any authenticated user; writes need codes."""

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS and request.user and request.user.is_authenticated:
            return True
        return super().has_permission(request, view)


class IsOwnerOrStaff(BasePermission):
    """Object-level check: owner (obj.user / obj.owner) or staff/admin role."""

    OWNER_ATTRS = ("user", "owner", "host", "guest")

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff_role or user.is_superuser:
            return True
        for attr in self.OWNER_ATTRS:
            owner = getattr(obj, attr, None)
            if owner is not None and owner.pk == user.pk:
                return True
        return False
