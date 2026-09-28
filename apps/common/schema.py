"""Helpers for drf-spectacular schema generation.

`get_queryset()` on authenticated views dereferences `request.user`, which
fails during schema generation with AnonymousUser. Views guard with
`swagger_fake_view` and return `schema_empty_queryset(self)` so spectacular
can still resolve the serializer without crashing.
"""
from __future__ import annotations


def schema_empty_queryset(view):
    """Return an empty queryset for the view's model during schema generation."""
    try:
        serializer = view.get_serializer_class()
    except Exception:
        serializer = getattr(view, "serializer_class", None)
    model = getattr(getattr(serializer, "Meta", None), "model", None)
    if model is not None:
        return model.objects.none()
    queryset = getattr(view, "queryset", None)
    if queryset is not None:
        return queryset.none()
    return None
