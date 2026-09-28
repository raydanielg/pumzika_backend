"""Demo seed — everything in seed_dev plus a few published listings."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.management import call_command

from apps.locations.models import Area, City
from apps.properties.models import Property, PropertyImage, PropertyType
from apps.accounts.models import HostProfile, User
from apps.bookings.models import CancellationPolicy

SAMPLE_PROPERTIES = [
    {
        "title": "Oceanview Apartment — Masaki",
        "description": "Bright 2-bed apartment steps from the beach, fibre WiFi "
                       "and backup power.",
        "area_name": "Masaki", "type_code": "APARTMENT",
        "base_price": "85000", "bedrooms": 2, "beds": 3, "max_guests": 4,
        "address": "12 Ocean Road, Masaki",
        "latitude": "-6.7700", "longitude": "39.2780",
    },
    {
        "title": "Stone Town Heritage House",
        "description": "Restored Zanzibari townhouse in the heart of Stone Town.",
        "area_name": "Stone Town", "type_code": "HOUSE",
        "base_price": "120000", "bedrooms": 3, "beds": 4, "max_guests": 6,
        "address": "45 Gizenga Street",
        "latitude": "-6.1622", "longitude": "39.1921",
    },
    {
        "title": "Arusha Garden Villa",
        "description": "Quiet villa with garden and Mt. Meru views.",
        "area_name": "Njiro", "type_code": "VILLA",
        "base_price": "150000", "bedrooms": 4, "beds": 5, "max_guests": 8,
        "address": "8 Njiro Hill",
        "latitude": "-3.3690", "longitude": "36.7270",
    },
]


class Command(BaseCommand):
    help = "Seed dev data + demo listings. Development only."

    def handle(self, *args, **options):
        call_command("seed_dev")

        host = User.objects.get(email="host@pumzika.dev")
        HostProfile.objects.filter(user=host).update(
            verification_status=HostProfile.VerificationStatus.VERIFIED
        )
        policy = CancellationPolicy.objects.filter(code="MODERATE").first()

        created = 0
        for spec in SAMPLE_PROPERTIES:
            area = Area.objects.filter(name=spec["area_name"]).first()
            district = area.district if area else None
            city = district.city if district else City.objects.first()
            region = city.region if city else None
            country = region.country if region else None
            ptype = PropertyType.objects.get(code=spec["type_code"])

            prop, was_created = Property.objects.get_or_create(
                host=host, title=spec["title"],
                defaults={
                    "description": spec["description"],
                    "property_type": ptype,
                    "country": country, "region": region, "city": city,
                    "district": district, "area": area,
                    "address": spec["address"],
                    "latitude": Decimal(spec["latitude"]),
                    "longitude": Decimal(spec["longitude"]),
                    "max_guests": spec["max_guests"],
                    "bedrooms": spec["bedrooms"], "beds": spec["beds"],
                    "bathrooms": 2,
                    "base_price": Decimal(spec["base_price"]),
                    "currency": "TZS",
                    "cleaning_fee": Decimal("15000"),
                    "cancellation_policy": policy,
                    # Demo listings bypass moderation — dev only.
                    "status": Property.Status.PUBLISHED,
                },
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Demo seed complete ({created} properties created)."
        ))
