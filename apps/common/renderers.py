"""Wraps successful API responses in the standard success envelope."""
from __future__ import annotations

import json

from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        request = (renderer_context or {}).get("request")
        request_id = getattr(request, "request_id", "") if request else ""

        if data is None:
            return super().render(None, accepted_media_type, renderer_context)

        # Already enveloped (error handler or explicit service response).
        if isinstance(data, dict) and "success" in data:
            if "request_id" not in data:
                data["request_id"] = request_id
            return super().render(data, accepted_media_type, renderer_context)

        if response is not None and response.status_code >= 400:
            return super().render(data, accepted_media_type, renderer_context)

        enveloped = {
            "success": True,
            "data": data,
            "message": "Request successful",
            "request_id": request_id,
        }
        return super().render(enveloped, accepted_media_type, renderer_context)
