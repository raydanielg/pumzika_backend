from django.contrib import admin

from .models import (
    Amenity,
    AmenityCategory,
    Property,
    PropertyAmenity,
    PropertyDocument,
    PropertyImage,
    PropertyPolicy,
    PropertyPricing,
    PropertyRule,
    PropertyType,
    PropertyVideo,
)


class ImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("title", "host", "city", "status", "base_price", "currency")
    list_filter = ("status", "property_type", "country")
    search_fields = ("title", "host__email", "address")
    inlines = [ImageInline]
    raw_id_fields = ("host",)


admin.site.register([
    PropertyType, AmenityCategory, Amenity, PropertyAmenity, PropertyImage,
    PropertyVideo, PropertyRule, PropertyPolicy, PropertyPricing, PropertyDocument,
])
