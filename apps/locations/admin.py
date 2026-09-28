from django.contrib import admin

from .models import Area, City, Country, District, Region


class ChildInline(admin.TabularInline):
    extra = 0
    fields = ("name", "is_active")


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "currency_code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "is_active")
    list_filter = ("country", "is_active")
    search_fields = ("name",)


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "is_active")
    list_filter = ("region__country", "is_active")
    search_fields = ("name",)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "is_active")
    search_fields = ("name",)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "is_active")
    search_fields = ("name",)
