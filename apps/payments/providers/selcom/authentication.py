"""Selcom request signing — isolated so it can be unit-tested with vectors.

Selcom authenticates each request with:

    Authorization: SELCOM <base64(api_key)>
    Timestamp: <ISO 8601>
    Digest-Method: HS256
    Digest: <base64 HMAC-SHA256(secret, signing_string)>
    Signed-Fields: <csv of signed keys>

The signing string is ``timestamp=<ts>&<field1>=<v1>&<field2>=<v2>...``
using exactly the fields listed in Signed-Fields, in that order.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Mapping


def selcom_timestamp(dt: datetime | None = None) -> str:
    """ISO 8601 timestamp with local offset, e.g. 2019-02-26T09:30:46+03:00."""
    return (dt or datetime.now().astimezone()).isoformat(timespec="seconds")


def signed_fields_list(parameters: Mapping, fields: list[str]) -> str:
    return ",".join(fields)


def build_signing_string(timestamp: str, parameters: Mapping,
                         signed_fields: list[str]) -> str:
    """timestamp=<ts>&k1=v1&k2=v2 in signed_fields order."""
    parts = [f"timestamp={timestamp}"]
    for field in signed_fields:
        parts.append(f"{field}={parameters.get(field, '')}")
    return "&".join(parts)


def compute_digest(signing_string: str, api_secret: str) -> str:
    """Base64(HMAC-SHA256(api_secret, signing_string)) — HS256 method."""
    digest = hmac.new(
        api_secret.encode(), signing_string.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode()


def auth_headers(api_key: str, api_secret: str, parameters: Mapping,
                 signed_fields: list[str],
                 timestamp: str | None = None) -> dict[str, str]:
    """Full header set for a signed Selcom request."""
    ts = timestamp or selcom_timestamp()
    signing = build_signing_string(ts, parameters, signed_fields)
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"SELCOM {base64.b64encode(api_key.encode()).decode()}",
        "Digest-Method": "HS256",
        "Digest": compute_digest(signing, api_secret),
        "Timestamp": ts,
        "Signed-Fields": signed_fields_list(parameters, signed_fields),
    }
