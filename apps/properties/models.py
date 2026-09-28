"""Property listings, media, amenities, rules and policies."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel
from apps.common.validators import secure_upload_to, validate_image_file


class PropertyType(TimeStampedModel):
    """Database-driven property types — never hardcode."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class AmenityCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "amenity categories"

    def __str__(self) -> str:
        return self.name


class Amenity(TimeStampedModel):
    category = models.ForeignKey(
        AmenityCategory, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="amenities",
    )
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = ("category", "name")
        verbose_name_plural = "amenities"

    def __str__(self) -> str:
        return self.name


class Property(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        PUBLISHED = "PUBLISHED", "Published"
        SUSPENDED = "SUSPENDED", "Suspended"
        REJECTED = "REJECTED", "Rejected"
        ARCHIVED = "ARCHIVED", "Archived"

    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="properties"
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=220, unique=True, db_index=True, null=True, blank=True,
        help_text="Public URL slug — stable, generated once from the title.",
    )
    description = models.TextField()
    property_type = models.ForeignKey(
        PropertyType, on_delete=models.PROTECT, related_name="properties"
    )

    # Structured location (all levels optional except country)
    country = models.ForeignKey("locations.Country", on_delete=models.PROTECT,
                                related_name="properties")
    region = models.ForeignKey("locations.Region", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="properties")
    city = models.ForeignKey("locations.City", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="properties")
    district = models.ForeignKey("locations.District", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="properties")
    area = models.ForeignKey("locations.Area", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="properties")
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    max_guests = models.PositiveIntegerField(default=1)
    bedrooms = models.PositiveIntegerField(default=1)
    beds = models.PositiveIntegerField(default=1)
    bathrooms = models.DecimalField(max_digits=3, decimal_places=1, default=1)

    base_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    currency = models.CharField(max_length=3)
    cleaning_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    min_nights = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    max_nights = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )

    check_in_time = models.TimeField(default="14:00")
    check_out_time = models.TimeField(default="11:00")
    instant_book = models.BooleanField(default=False)

    cancellation_policy = models.ForeignKey(
        "bookings.CancellationPolicy", on_delete=models.PROTECT,
        null=True, blank=True, related_name="properties",
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="properties_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, db_index=True)
    review_count = models.PositiveIntegerField(default=0)

    amenities = models.ManyToManyField(
        Amenity, through="PropertyAmenity", related_name="properties", blank=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["status", "country"]),
            models.Index(fields=["host", "status"]),
            models.Index(fields=["city", "status"]),
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["property_type", "status"]),
        ]
        verbose_name_plural = "properties"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._make_slug()
        super().save(*args, **kwargs)

    def _make_slug(self) -> str:
        import secrets

        from django.utils.text import slugify

        base = slugify(self.title)[:190] or "stay"
        slug = base
        while type(self).objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{secrets.token_hex(3)}"
        return slug

    @property
    def is_publicly_bookable(self) -> bool:
        return self.status == self.Status.PUBLISHED


class PropertyAmenity(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("property", "amenity")


class PropertyImage(UUIDModel):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to=secure_upload_to("properties/images"), validators=[validate_image_file])
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "created_at"]
        indexes = [models.Index(fields=["property", "sort_order"])]

    def save(self, *args, **kwargs):
        # A property can only have one cover image.
        if self.is_cover:
            PropertyImage.objects.filter(
                property=self.property, is_cover=True
            ).exclude(pk=self.pk).update(is_cover=False)
        super().save(*args, **kwargs)


class PropertyVideo(UUIDModel):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="videos"
    )
    video = models.FileField(upload_to=secure_upload_to("properties/videos"))
    thumbnail = models.ImageField(
        upload_to=secure_upload_to("properties/videos/thumbs"),
        validators=[validate_image_file], null=True, blank=True,
    )
    sort_order = models.PositiveIntegerField(default=0)


class PropertyRule(TimeStampedModel):
    """House rules, e.g. pets allowed, quiet hours, smoking policy."""

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="rules"
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]


class PropertyPolicy(TimeStampedModel):
    """Structured stay policy booleans + free-text extras."""

    property = models.OneToOneField(
        Property, on_delete=models.CASCADE, related_name="policy"
    )
    pets_allowed = models.BooleanField(default=False)
    smoking_allowed = models.BooleanField(default=False)
    parties_allowed = models.BooleanField(default=False)
    children_allowed = models.BooleanField(default=True)
    extra_policy = models.TextField(blank=True)


class PropertyPricing(TimeStampedModel):
    """Host-defined special pricing for a date range (seasonal rates)."""

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="special_pricings"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    nightly_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    min_nights = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["property", "start_date", "end_date"])]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("start_date must be on or before end_date.")


class PropertyDocument(UUIDModel):
    """Ownership/authorization documents — private, staff-visible only."""

    class DocumentType(models.TextChoices):
        TITLE_DEED = "TITLE_DEED", "Title Deed"
        LEASE = "LEASE", "Lease Agreement"
        AUTHORIZATION = "AUTHORIZATION", "Authorization Letter"
        BUSINESS_LICENSE = "BUSINESS_LICENSE", "Business License"
        OTHER = "OTHER", "Other"

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    file = models.FileField(upload_to=secure_upload_to("property-documents"))
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="uploaded_property_documents",
    )

    class Meta:
        indexes = [models.Index(fields=["property", "document_type"])]
