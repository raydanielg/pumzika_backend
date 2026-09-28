"""Development seed data — Tanzania hierarchy, amenities, types, policies.

Safe for dev/staging only. No real customer data.
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management import call_command

from apps.accounts.models import User, HostProfile
from apps.admin_panel.models import PlatformSetting, CommissionRule, TaxRule
from apps.bookings.models import CancellationPolicy, CancellationRule
from apps.locations.models import Area, City, Country, District, Region
from apps.payments.models import PaymentProvider
from apps.properties.models import Amenity, AmenityCategory, PropertyType


TZ_REGIONS = {
    "Dar es Salaam": {
        "cities": {
            "Dar es Salaam": {
                "districts": {
                    "Ilala": ["Upanga", "Kariakoo", "Posta"],
                    "Kinondoni": ["Masaki", "Mikocheni", "Mbezi"],
                    "Temeke": ["Mbagala", "Kigamboni"],
                },
                "lat": "-6.7924", "lng": "39.2083",
            },
        },
    },
    "Arusha": {
        "cities": {
            "Arusha": {
                "districts": {"Arusha Urban": ["Central", "Njiro", "Sakina"]},
                "lat": "-3.3869", "lng": "36.6830",
            },
        },
    },
    "Zanzibar": {
        "cities": {
            "Zanzibar City": {
                "districts": {"Mjini Magharibi": ["Stone Town", "Nungwi", "Kendwa"]},
                "lat": "-6.1659", "lng": "39.2026",
            },
        },
    },
    "Mwanza": {
        "cities": {
            "Mwanza": {
                "districts": {"Ilemela": ["Nyamagana", "Buzuruga"]},
                "lat": "-2.5164", "lng": "32.9175",
            },
        },
    },
    "Mbeya": {
        "cities": {
            "Mbeya": {
                "districts": {"Mbeya Urban": ["Central", "Uyole"]},
                "lat": "-8.9094", "lng": "33.4608",
            },
        },
    },
}

PROPERTY_TYPES = [
    ("APARTMENT", "Apartment"), ("HOUSE", "House"), ("VILLA", "Villa"),
    ("HOTEL", "Hotel"), ("LODGE", "Lodge"), ("ROOM", "Room"),
    ("RESORT", "Resort"), ("GUEST_HOUSE", "Guest House"), ("OTHER", "Other"),
]

AMENITIES = {
    "Essentials": ["WiFi", "Hot Water", "Kitchen", "TV", "Workspace",
                   "Washing Machine"],
    "Features": ["Swimming Pool", "Parking", "Balcony", "Garden", "Gym",
                 "Sea View"],
    "Safety": ["Security", "CCTV", "Smoke Detector", "First Aid Kit",
               "Security Guard"],
    "Comfort": ["Air Conditioning", "Heating", "Breakfast", "Restaurant",
                "Room Service"],
}

CANCELLATION_POLICIES = [
    ("Flexible", "FLEXIBLE", [
        (24, Decimal("100"), True),
        (0, Decimal("0"), False),
    ]),
    ("Moderate", "MODERATE", [
        (120, Decimal("100"), True),   # 5 days
        (24, Decimal("50"), False),
        (0, Decimal("0"), False),
    ]),
    ("Strict", "STRICT", [
        (336, Decimal("100"), True),   # 14 days
        (168, Decimal("50"), False),   # 7 days
        (0, Decimal("0"), False),
    ]),
]


class Command(BaseCommand):
    help = "Seed development data for Pumzika Africa (Tanzania)."

    def handle(self, *args, **options):
        call_command("seed_permissions")

        tz, _ = Country.objects.get_or_create(
            code="TZ",
            defaults={
                "name": "Tanzania",
                "currency_code": "TZS",
                "phone_code": "+255",
                "timezone": "Africa/Dar_es_Salaam",
                "languages": ["sw", "en"],
            },
        )
        self.stdout.write(f"Country: {tz}")

        for region_name, region_data in TZ_REGIONS.items():
            region, _ = Region.objects.get_or_create(
                country=tz, name=region_name
            )
            for city_name, city_data in region_data["cities"].items():
                city, _ = City.objects.get_or_create(
                    region=region, name=city_name,
                    defaults={
                        "latitude": city_data["lat"],
                        "longitude": city_data["lng"],
                    },
                )
                for district_name, areas in city_data["districts"].items():
                    district, _ = District.objects.get_or_create(
                        city=city, name=district_name
                    )
                    for area_name in areas:
                        Area.objects.get_or_create(district=district, name=area_name)

        for i, (code, name) in enumerate(PROPERTY_TYPES):
            PropertyType.objects.get_or_create(
                code=code, defaults={"name": name, "sort_order": i}
            )

        for cat_i, (cat_name, names) in enumerate(AMENITIES.items()):
            category, _ = AmenityCategory.objects.get_or_create(
                name=cat_name, defaults={"sort_order": cat_i}
            )
            for j, name in enumerate(names):
                Amenity.objects.get_or_create(
                    category=category, name=name, defaults={"sort_order": j}
                )

        for name, code, rules in CANCELLATION_POLICIES:
            policy, _ = CancellationPolicy.objects.get_or_create(
                name=name, defaults={"code": code}
            )
            for hours, pct, refund_fee in rules:
                CancellationRule.objects.get_or_create(
                    policy=policy, hours_before_check_in=hours,
                    defaults={"guest_refund_percent": pct,
                              "refund_service_fee": refund_fee},
                )

        PaymentProvider.objects.get_or_create(
            code="MOCK",
            defaults={
                "name": "Sandbox Provider",
                "is_active": True,
                "is_default": True,
                "supported_currencies": ["TZS", "KES", "USD"],
            },
        )
        # Selcom is registered but only active when credentials are present.
        PaymentProvider.objects.update_or_create(
            code="SELCOM",
            defaults={
                "name": "Selcom",
                "is_active": bool(
                    settings.SELCOM_API_KEY and settings.SELCOM_VENDOR_ID
                ),
                "is_default": bool(settings.SELCOM_API_KEY),
                "supported_currencies": ["TZS"],
                "countries": ["TZ"],
            },
        )

        defaults = {
            "SERVICE_FEE_PERCENT": "12",
            "DEFAULT_COMMISSION_PERCENT": "15",
            "MIN_BOOKING_AMOUNT": "0",
            "MAX_BOOKING_AMOUNT": "50000000",
            "SUPPORTED_CURRENCIES": ["TZS", "KES", "UGX", "ZAR", "USD"],
            "BOOKING_PAYMENT_WINDOW_MINUTES": "30",
            "PAYOUT_MINIMUM": "10000",
            "MAINTENANCE_MODE": False,
        }
        for key, value in defaults.items():
            PlatformSetting.objects.get_or_create(
                key=key, defaults={"value": value,
                                   "description": f"Seeded default for {key}"}
            )

        CommissionRule.objects.get_or_create(
            scope=CommissionRule.Scope.GLOBAL,
            defaults={"percent": Decimal("15")},
        )
        TaxRule.objects.get_or_create(
            name="Tanzania VAT", country=tz,
            defaults={"percent": Decimal("18")},
        )

        # Dev users — never use in production.
        admin_user, _ = User.objects.get_or_create(
            email="admin@pumzika.dev",
            defaults={
                "first_name": "Dev", "last_name": "Admin",
                "role": User.Role.SUPER_ADMIN,
                "is_staff": True, "is_superuser": True,
                "is_email_verified": True,
            },
        )
        admin_user.set_password("Admin123!x")
        admin_user.save()

        host, _ = User.objects.get_or_create(
            email="host@pumzika.dev",
            defaults={
                "first_name": "Dev", "last_name": "Host",
                "role": User.Role.HOST, "is_email_verified": True,
            },
        )
        host.set_password("Host123!x")
        host.save()
        HostProfile.objects.update_or_create(
            user=host,
            defaults={
                "display_name": "Dev Host",
                "verification_status": HostProfile.VerificationStatus.VERIFIED,
            },
        )

        guest, _ = User.objects.get_or_create(
            email="guest@pumzika.dev",
            defaults={
                "first_name": "Dev", "last_name": "Guest",
                "role": User.Role.GUEST, "is_email_verified": True,
            },
        )
        guest.set_password("Guest123!x")
        guest.save()

        self.stdout.write(self.style.SUCCESS(
            "Seed complete. Dev users: admin@pumzika.dev / host@pumzika.dev / "
            "guest@pumzika.dev (dev passwords — do not deploy)."
        ))
