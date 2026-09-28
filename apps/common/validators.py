"""Reusable validators — file uploads, phones, etc."""
from __future__ import annotations

import os

import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image

Image.MAX_IMAGE_PIXELS = 200_000_000  # decompression bomb guard


def validate_phone_number(value: str) -> str:
    """Validate/normalize an international phone number to E.164."""
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("Invalid phone number format.") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationError("Invalid phone number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def validate_image_file(file) -> None:
    """Verify a file is a real image within size/type/dimension limits.

    Never trusts the declared MIME type — the content is decoded with Pillow.
    """
    if file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            f"File too large. Maximum size is "
            f"{settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB."
        )

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValidationError("Unsupported file extension.")

    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()
        file.seek(0)
        with Image.open(file) as img:
            fmt = img.format or ""
            width, height = img.size
    except Exception as exc:
        raise ValidationError("File is not a valid image.") from exc
    finally:
        file.seek(0)

    mime_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    if mime_map.get(fmt) not in settings.ALLOWED_IMAGE_TYPES:
        raise ValidationError("Unsupported image format.")

    if width < settings.MIN_IMAGE_DIMENSION or height < settings.MIN_IMAGE_DIMENSION:
        raise ValidationError(
            f"Image too small. Minimum {settings.MIN_IMAGE_DIMENSION}px per side."
        )
    if width > settings.MAX_IMAGE_DIMENSION or height > settings.MAX_IMAGE_DIMENSION:
        raise ValidationError(
            f"Image too large. Maximum {settings.MAX_IMAGE_DIMENSION}px per side."
        )
