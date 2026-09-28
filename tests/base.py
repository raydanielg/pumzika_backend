"""Shared test fixtures — builds the minimum viable world."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.constants import ROLE_DEFAULTS
from apps.accounts.models import HostProfile, RolePermission, User
from apps.admin_panel.models import CommissionRule, PlatformSetting, TaxRule
from apps.bookings.models import CancellationPolicy, CancellationRule
from apps.locations.models import Area, City, Country, District, Region
from apps.payments.models import PaymentProvider
from apps.properties.models import Property, PropertyImage, PropertyType


class BaseTestCase(TestCase):
    """Country/city chain + roles + policies, ready for booking tests."""

    @classmethod
    def setUpTestData(cls):
        for role, codes in ROLE_DEFAULTS.items():
            for code in codes:
                RolePermission.objects.get_or_create(role=role, code=code)

        cls.country = Country.objects.create(
            code="TZ", name="Tanzania", currency_code="TZS"
        )
        cls.region = Region.objects.create(country=cls.country, name="Dar es Salaam")
        cls.city = City.objects.create(region=cls.region, name="Dar es Salaam")
        cls.district = District.objects.create(city=cls.city, name="Kinondoni")
        cls.area = Area.objects.create(district=cls.district, name="Masaki")

        cls.prop_type = PropertyType.objects.create(code="APARTMENT", name="Apartment")

        cls.policy = CancellationPolicy.objects.create(name="Moderate", code="MODERATE")
        CancellationRule.objects.create(
            policy=cls.policy, hours_before_check_in=24,
            guest_refund_percent=Decimal("100"), refund_service_fee=True,
        )
        CancellationRule.objects.create(
            policy=cls.policy, hours_before_check_in=0,
            guest_refund_percent=Decimal("0"), refund_service_fee=False,
        )

        CommissionRule.objects.create(
            scope=CommissionRule.Scope.GLOBAL, percent=Decimal("15")
        )
        TaxRule.objects.create(name="VAT", country=cls.country, percent=Decimal("18"))
        PlatformSetting.objects.create(key="SERVICE_FEE_PERCENT", value="12")
        PlatformSetting.objects.create(key="MIN_BOOKING_AMOUNT", value="0")
        PlatformSetting.objects.create(key="MAX_BOOKING_AMOUNT", value="100000000")
        PlatformSetting.objects.create(key="PAYOUT_MINIMUM", value="1000")

        cls.guest = User.objects.create_user(
            email="guest@test.dev", password="Pass1234!",
            first_name="G", last_name="Guest", role=User.Role.GUEST,
            is_email_verified=True,
        )
        cls.other_guest = User.objects.create_user(
            email="guest2@test.dev", password="Pass1234!",
            first_name="G2", last_name="Guest", role=User.Role.GUEST,
            is_email_verified=True,
        )
        cls.host = User.objects.create_user(
            email="host@test.dev", password="Pass1234!",
            first_name="H", last_name="Host", role=User.Role.HOST,
            is_email_verified=True,
        )
        cls.host_profile = HostProfile.objects.create(
            user=cls.host, display_name="H Host",
            verification_status=HostProfile.VerificationStatus.VERIFIED,
        )
        cls.admin = User.objects.create_user(
            email="admin@test.dev", password="Pass1234!",
            first_name="A", last_name="Admin", role=User.Role.ADMIN,
            is_staff=True, is_email_verified=True,
        )

        cls.property = Property.objects.create(
            host=cls.host, title="Sea View Apartment",
            description="Nice place", property_type=cls.prop_type,
            country=cls.country, region=cls.region, city=cls.city,
            district=cls.district, area=cls.area, address="1 Ocean Rd",
            max_guests=4, bedrooms=2, beds=2, bathrooms=2,
            base_price=Decimal("50000"), currency="TZS",
            cleaning_fee=Decimal("10000"), min_nights=1,
            cancellation_policy=cls.policy,
            status=Property.Status.PUBLISHED,
        )
        PropertyImage.objects.create(property=cls.property, is_cover=True)

        cls.provider = PaymentProvider.objects.create(
            code="MOCK", name="Sandbox", is_active=True, is_default=True,
            supported_currencies=["TZS"],
        )

        cls.check_in = date.today() + timedelta(days=10)
        cls.check_out = date.today() + timedelta(days=13)  # 3 nights

    def auth_client(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user)
        return client
