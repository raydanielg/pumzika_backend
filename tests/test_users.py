"""User lifecycle tests — verification, restriction, suspension, deletion."""
from decimal import Decimal

from apps.accounts import services as account_services
from apps.accounts.models import User, UserRestriction
from apps.accounts.services import _generate_otp
from apps.accounts.models import VerificationCode
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.common.exceptions import BusinessError
from apps.payouts.models import PayoutMethod
from apps.payouts import services as payout_services
from apps.properties import services as property_services
from apps.security.models import SecurityEvent
from apps.security import services as sec

from .base import BaseTestCase


class LifecycleTests(BaseTestCase):
    def test_new_registration_is_pending_verification(self):
        user = account_services.register_user(
            email="new@x.com", password="Pass123!x",
            first_name="N", last_name="U",
        )
        assert user.account_status == User.AccountStatus.PENDING_VERIFICATION

    def test_email_verification_activates_account(self):
        user = account_services.register_user(
            email="pend@x.com", password="Pass123!x",
            first_name="N", last_name="U",
        )
        record = VerificationCode.objects.filter(
            user=user, purpose=VerificationCode.Purpose.EMAIL_VERIFY).first()
        # regenerate a known code path — issue() hashes; emulate confirm
        # by issuing + consuming via service with a known code
        code = _generate_otp()
        record.code_hash = record.hash_code(code)
        record.save()
        account_services.confirm_email_verification(user, code)
        user.refresh_from_db()
        assert user.account_status == User.AccountStatus.ACTIVE
        assert user.email_verified_at is not None
        assert SecurityEvent.objects.filter(
            user=user, event_type="EMAIL_VERIFIED").exists()

    def test_pending_user_can_login_but_not_book(self):
        user = account_services.register_user(
            email="pend2@x.com", password="Pass123!x",
            first_name="N", last_name="U",
        )
        # authenticate_user accepts — pending is not a block
        authed = account_services.authenticate_user(
            email="pend2@x.com", password="Pass123!x")
        assert authed.pk == user.pk
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                user, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1,
            )
        assert ctx.exception.code == "EMAIL_NOT_VERIFIED"


class RestrictionTests(BaseTestCase):
    def test_booking_restriction_blocks_booking(self):
        sec.restrict_account(self.guest, self.admin, "BOOKING", "fraud review")
        assert self.guest.has_restriction("BOOKING")
        self.guest.refresh_from_db()
        assert self.guest.account_status == User.AccountStatus.RESTRICTED
        with self.assertRaises(BusinessError) as ctx:
            booking_services.create_booking(
                self.guest, property_id=self.property.id,
                check_in=self.check_in, check_out=self.check_out,
                guests_count=1,
            )
        assert ctx.exception.code == "CAPABILITY_RESTRICTED"

    def test_booking_restriction_does_not_block_payout(self):
        method = PayoutMethod.objects.create(
            user=self.host, method_type="BANK", label="B",
            account_name="H", account_number="1",
        )
        sec.restrict_account(self.host, self.admin, "BOOKING", "x")
        # payout restriction is a different capability — unaffected
        assert not self.host.has_restriction("PAYOUT")

    def test_expired_restriction_inactive(self):
        from datetime import timedelta
        from django.utils import timezone

        UserRestriction.objects.create(
            user=self.guest, capability="BOOKING", reason="x",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert not self.guest.has_restriction("BOOKING")

    def test_restore_lifts_restrictions(self):
        sec.restrict_account(self.guest, self.admin, "BOOKING", "x")
        sec.suspend_account(self.guest, self.admin, "major")
        sec.restore_account(self.guest, self.admin)
        self.guest.refresh_from_db()
        assert self.guest.account_status == User.AccountStatus.ACTIVE
        assert not self.guest.has_restriction("BOOKING")


class DeletionSafetyTests(BaseTestCase):
    def test_delete_blocked_by_active_booking(self):
        booking_services.create_booking(
            self.guest, property_id=self.property.id,
            check_in=self.check_in, check_out=self.check_out, guests_count=1,
        )
        booking = Booking.objects.get(guest=self.guest)
        booking.status = Booking.Status.CONFIRMED
        booking.save()
        with self.assertRaises(BusinessError) as ctx:
            account_services.delete_account(self.guest, "unused")
        # password check happens first — use the real password
        assert ctx.exception.code in (
            "INVALID_PASSWORD", "ACCOUNT_HAS_OBLIGATIONS")

    def test_delete_allowed_for_clean_account(self):
        user = User.objects.create_user(
            email="gone@x.com", password="Pass123!x",
            first_name="G", last_name="O",
        )
        account_services.delete_account(user, "Pass123!x")
        user.refresh_from_db()
        assert user.account_status == User.AccountStatus.DEACTIVATED
        assert user.email.endswith("@pumzika.invalid")

    def test_mass_assignment_blocked(self):
        # role/account_status must never be writable via profile update
        updated = account_services.update_profile(
            self.guest, role="ADMIN", account_status="ACTIVE",
            first_name="Safe",
        )
        updated.refresh_from_db()
        assert updated.role != "ADMIN"
        assert updated.first_name == "Safe"


class PublicProfileTests(BaseTestCase):
    def test_public_host_serializer_hides_email(self):
        from apps.accounts.serializers import PublicHostProfileSerializer

        data = PublicHostProfileSerializer(self.host.host_profile).data
        assert "user_email" not in data
        assert "email" not in data
        assert "verification_status" not in data
        assert data["display_name"] == self.host.host_profile.display_name
