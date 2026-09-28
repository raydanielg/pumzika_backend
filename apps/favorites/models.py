from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class Favorite(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE, related_name="favorited_by"
    )

    class Meta:
        unique_together = ("user", "property")
        indexes = [models.Index(fields=["user", "-created_at"])]
