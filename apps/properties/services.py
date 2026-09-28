"""Property business logic — creation, lifecycle, media management."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError

from .models import Amenity, Property, PropertyImage


def get_host_property(user, property_id) -> Property:
    prop = Property.objects.filter(pk=property_id).first()
    if prop is None:
        raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
    if prop.host_id != user.id and not user.is_staff_role:
        raise PermissionDeniedError("You do not own this property.")
    return prop


def assert_host_can_list(user) -> None:
    """A suspended/restricted host cannot create new bookable listings."""
    if user.has_restriction("HOSTING"):
        raise BusinessError(
            "Your account is restricted from hosting.",
            code="CAPABILITY_RESTRICTED", http_status=403,
        )
    profile = getattr(user, "host_profile", None)
    if profile is None:
        from apps.accounts.models import HostProfile

        profile = HostProfile.objects.create(
            user=user, display_name=user.full_name
        )
    if profile.hosting_status == profile.HostingStatus.SUSPENDED:
        raise BusinessError(
            "Your hosting account is suspended.", code="HOST_SUSPENDED",
            http_status=403,
        )


def _validate_location_chain(prop_data: dict) -> None:
    """Ensure region/city/district/area actually belong to each other."""
    country = prop_data.get("country")
    region = prop_data.get("region")
    city = prop_data.get("city")
    district = prop_data.get("district")
    area = prop_data.get("area")
    if region and region.country_id != (country.id if country else None):
        raise BusinessError("Region does not belong to the selected country.",
                            code="INVALID_LOCATION")
    if city and region and city.region_id != region.id:
        raise BusinessError("City does not belong to the selected region.",
                            code="INVALID_LOCATION")
    if district and city and district.city_id != city.id:
        raise BusinessError("District does not belong to the selected city.",
                            code="INVALID_LOCATION")
    if area and district and area.district_id != district.id:
        raise BusinessError("Area does not belong to the selected district.",
                            code="INVALID_LOCATION")


@transaction.atomic
def create_property(user, data: dict, amenity_ids: list | None = None) -> Property:
    assert_host_can_list(user)
    _validate_location_chain(data)
    prop = Property.objects.create(host=user, **data)
    if amenity_ids:
        set_amenities(prop, amenity_ids)
    return prop


@transaction.atomic
def update_property(prop: Property, data: dict, amenity_ids: list | None = None) -> Property:
    if prop.status == Property.Status.ARCHIVED:
        raise BusinessError("Archived properties cannot be edited.", code="PROPERTY_ARCHIVED")
    _validate_location_chain(data)
    protected = {"status", "host", "published_at", "rating", "review_count"}
    for key, value in data.items():
        if key in protected:
            continue
        setattr(prop, key, value)
    prop.save()
    if amenity_ids is not None:
        set_amenities(prop, amenity_ids)
    # Any material change to a live listing sends it back to review.
    if prop.status == Property.Status.PUBLISHED and data:
        prop.status = Property.Status.SUBMITTED
        prop.save(update_fields=["status", "updated_at"])
    return prop


@transaction.atomic
def set_amenities(prop: Property, amenity_ids: list) -> None:
    amenities = list(Amenity.objects.filter(id__in=amenity_ids, is_active=True))
    if len(amenities) != len(set(amenity_ids)):
        raise BusinessError("One or more amenities are invalid.", code="INVALID_AMENITIES")
    prop.amenities.set(amenities)


def _min_images() -> int:
    from apps.admin_panel.models import PlatformSetting

    try:
        return int(PlatformSetting.get("MIN_PROPERTY_IMAGES", 3))
    except (TypeError, ValueError):
        return 3


def submission_errors(prop: Property) -> dict[str, str]:
    """Field-level reasons a property cannot be submitted for review."""
    errors: dict[str, str] = {}
    if not prop.title:
        errors["title"] = "Title is required."
    if not prop.description:
        errors["description"] = "Description is required."
    if prop.property_type_id is None:
        errors["property_type"] = "Property type is required."
    if prop.city_id is None:
        errors["city"] = "A city is required."
    if not prop.base_price or prop.base_price <= 0:
        errors["base_price"] = "A valid base price is required."
    if prop.max_guests < 1:
        errors["max_guests"] = "Guest capacity is required."
    image_count = prop.images.count()
    min_images = _min_images()
    if image_count < min_images:
        errors["images"] = f"At least {min_images} images are required."
    if not prop.images.filter(is_cover=True).exists():
        errors["cover_image"] = "A cover image is required."
    if not prop.amenities.exists():
        errors["amenities"] = "At least one amenity is required."
    if prop.cancellation_policy_id is None:
        errors["cancellation_policy"] = "A cancellation policy is required."
    profile = getattr(prop.host, "host_profile", None)
    if profile is None or not profile.can_publish:
        errors["host_kyc"] = "Host identity verification (KYC) must be approved."
    return errors


def publish_readiness_errors(prop: Property) -> list[str]:
    """Flat list for backwards-compat / quick checks."""
    return list(submission_errors(prop).values())


@transaction.atomic
def submit_for_review(prop: Property) -> Property:
    if prop.status not in (Property.Status.DRAFT, Property.Status.REJECTED):
        raise BusinessError("Only draft or rejected properties can be submitted.",
                            code="INVALID_STATE")
    errors = submission_errors(prop)
    if errors:
        raise BusinessError("Property is incomplete.", code="PROPERTY_INCOMPLETE",
                            details=errors)
    prop.status = Property.Status.SUBMITTED
    prop.rejection_reason = ""
    prop.save(update_fields=["status", "rejection_reason", "updated_at"])

    from apps.notifications.tasks import notify_property_event

    transaction.on_commit(
        lambda: notify_property_event.delay(str(prop.id), "PROPERTY_SUBMITTED")
    )
    return prop


@transaction.atomic
def approve_property(prop: Property, admin=None) -> Property:
    """Staff approval — the listing may then be published by the host."""
    if prop.status not in (Property.Status.SUBMITTED, Property.Status.UNDER_REVIEW):
        raise BusinessError("Only submitted properties can be approved.",
                            code="INVALID_STATE")
    prop.status = Property.Status.APPROVED
    prop.approved_by = admin
    prop.approved_at = timezone.now()
    prop.rejection_reason = ""
    prop.save(update_fields=["status", "approved_by", "approved_at",
                             "rejection_reason", "updated_at"])

    from apps.notifications.tasks import notify_property_event

    transaction.on_commit(
        lambda: notify_property_event.delay(str(prop.id), "PROPERTY_APPROVED")
    )
    return prop


@transaction.atomic
def publish_property(prop: Property) -> Property:
    """Host publishes an approved listing — final readiness re-check."""
    if prop.status != Property.Status.APPROVED:
        raise BusinessError(
            "Only approved properties can be published.", code="INVALID_STATE"
        )
    errors = submission_errors(prop)
    if errors:
        raise BusinessError("Property is incomplete.", code="PROPERTY_INCOMPLETE",
                            details=errors)
    prop.status = Property.Status.PUBLISHED
    prop.published_at = timezone.now()
    prop.save(update_fields=["status", "published_at", "updated_at"])
    return prop


@transaction.atomic
def unpublish_property(prop: Property) -> Property:
    """Host takes a listing offline — it goes back to draft."""
    if prop.status != Property.Status.PUBLISHED:
        raise BusinessError("Only published properties can be unpublished.",
                            code="INVALID_STATE")
    prop.status = Property.Status.DRAFT
    prop.save(update_fields=["status", "updated_at"])
    return prop


@transaction.atomic
def reject_property(prop: Property, reason: str) -> Property:
    if not reason:
        raise BusinessError("A rejection reason is required.",
                            code="REASON_REQUIRED")
    prop.status = Property.Status.REJECTED
    prop.rejection_reason = reason
    prop.approved_by = None
    prop.approved_at = None
    prop.save(update_fields=["status", "rejection_reason", "approved_by",
                             "approved_at", "updated_at"])

    from apps.notifications.tasks import notify_property_event

    transaction.on_commit(
        lambda: notify_property_event.delay(
            str(prop.id), "PROPERTY_REJECTED", reason
        )
    )
    return prop


@transaction.atomic
def suspend_property(prop: Property, reason: str = "") -> Property:
    if not reason:
        raise BusinessError("A suspension reason is required.",
                            code="REASON_REQUIRED")
    prop.status = Property.Status.SUSPENDED
    prop.rejection_reason = reason
    prop.save(update_fields=["status", "rejection_reason", "updated_at"])

    from apps.notifications.tasks import notify_property_event

    transaction.on_commit(
        lambda: notify_property_event.delay(
            str(prop.id), "PROPERTY_SUSPENDED", reason
        )
    )
    return prop


@transaction.atomic
def archive_property(prop: Property) -> Property:
    prop.status = Property.Status.ARCHIVED
    prop.save(update_fields=["status", "updated_at"])
    return prop


@transaction.atomic
def add_image(prop: Property, image_file, caption: str = "") -> PropertyImage:
    if prop.images.count() >= 25:
        raise BusinessError("Maximum of 25 images per property.", code="TOO_MANY_IMAGES")
    is_first = not prop.images.exists()
    image = PropertyImage.objects.create(
        property=prop,
        image=image_file,
        caption=caption,
        sort_order=(prop.images.count()),
        is_cover=is_first,
    )
    return image


@transaction.atomic
def delete_image(prop: Property, image_id) -> None:
    image = prop.images.filter(pk=image_id).first()
    if image is None:
        raise NotFoundError("Image not found.", code="IMAGE_NOT_FOUND")
    was_cover = image.is_cover
    image.delete()
    if was_cover:
        first = prop.images.order_by("sort_order").first()
        if first:
            first.is_cover = True
            first.save(update_fields=["is_cover"])


@transaction.atomic
def set_cover_image(prop: Property, image_id) -> PropertyImage:
    image = prop.images.filter(pk=image_id).first()
    if image is None:
        raise NotFoundError("Image not found.", code="IMAGE_NOT_FOUND")
    image.is_cover = True
    image.save(update_fields=["is_cover"])
    return image


@transaction.atomic
def reorder_images(prop: Property, ordered_ids: list) -> None:
    images = {str(img.id): img for img in prop.images.all()}
    if set(ordered_ids) != set(images.keys()):
        raise BusinessError("Image list does not match this property's images.",
                            code="INVALID_IMAGE_ORDER")
    for position, image_id in enumerate(ordered_ids):
        img = images[image_id]
        if img.sort_order != position:
            img.sort_order = position
            img.save(update_fields=["sort_order"])
