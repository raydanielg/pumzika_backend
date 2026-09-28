"""Dashboard metrics — read-only aggregates for staff."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.disputes.models import Dispute
from apps.kyc.models import KYCVerification
from apps.payments.models import Payment
from apps.payouts.models import Payout
from apps.properties.models import Property
from apps.reviews.models import PropertyReview


def dashboard_metrics() -> dict:
    users = User.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
    )
    hosts = User.objects.filter(role=User.Role.HOST, is_active=True).count()
    properties = Property.objects.aggregate(
        total=Count("id"),
        published=Count("id", filter=Q(status=Property.Status.PUBLISHED)),
        pending=Count("id", filter=Q(status=Property.Status.PENDING_REVIEW)),
    )
    bookings = Booking.objects.aggregate(
        total=Count("id"),
        confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
        cancelled=Count("id", filter=Q(status=Booking.Status.CANCELLED)),
        completed=Count("id", filter=Q(status=Booking.Status.COMPLETED)),
    )
    payment_volume = Payment.objects.filter(status=Payment.Status.SUCCESS).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0"))
    )["total"]
    platform_revenue = Booking.objects.filter(
        status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN,
                    Booking.Status.COMPLETED]
    ).aggregate(total=Coalesce(Sum("price__commission_amount"), Decimal("0")))["total"]

    return {
        "total_users": users["total"],
        "active_users": users["active"],
        "active_hosts": hosts,
        "total_properties": properties["total"],
        "published_properties": properties["published"],
        "pending_properties": properties["pending"],
        "total_bookings": bookings["total"],
        "confirmed_bookings": bookings["confirmed"],
        "cancelled_bookings": bookings["cancelled"],
        "completed_bookings": bookings["completed"],
        "payment_volume": str(payment_volume),
        "platform_revenue": str(platform_revenue),
        "pending_payouts": Payout.objects.filter(status=Payout.Status.PENDING).count(),
        "pending_kyc": KYCVerification.objects.filter(status="UNDER_REVIEW").count(),
        "open_disputes": Dispute.objects.filter(
            status__in=[Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW,
                        Dispute.Status.WAITING_FOR_USER]
        ).count(),
        "total_reviews": PropertyReview.objects.count(),
    }
