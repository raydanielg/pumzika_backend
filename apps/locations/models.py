"""Hierarchical locations — multi-country by design.

Country -> Region -> City -> District -> Area
"""
from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel


class Country(TimeStampedModel):
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    name = models.CharField(max_length=100)
    currency_code = models.CharField(max_length=3)  # ISO 4217
    phone_code = models.CharField(max_length=8, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    languages = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    flag = models.ImageField(upload_to="flags/", null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return self.name


class Region(TimeStampedModel):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="regions")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = ("country", "name")
        ordering = ["name"]
        indexes = [models.Index(fields=["country", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name}, {self.country.code}"


class City(TimeStampedModel):
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="cities")
    name = models.CharField(max_length=150)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = ("region", "name")
        ordering = ["name"]
        verbose_name_plural = "cities"
        indexes = [models.Index(fields=["region", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name}, {self.region.name}"


class District(TimeStampedModel):
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="districts")
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = ("city", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name}, {self.city.name}"


class Area(TimeStampedModel):
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="areas")
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = ("district", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name}, {self.district.name}"
