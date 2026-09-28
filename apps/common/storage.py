"""Object storage backends for media files."""
from __future__ import annotations

from storages.backends.s3boto3 import S3Boto3Storage


class MediaStorage(S3Boto3Storage):
    """S3-compatible storage for user-uploaded media.

    Works with AWS S3 and any S3-compatible service (MinIO, DigitalOcean
    Spaces, Wasabi, ...) via ``AWS_S3_ENDPOINT_URL``.
    """

    location = "media"
    file_overwrite = False
    default_acl = "private"


class PrivateDocumentStorage(S3Boto3Storage):
    """Storage for sensitive documents (KYC) — never publicly readable."""

    location = "private"
    file_overwrite = False
    default_acl = "private"
    custom_domain = None
    querystring_auth = True
