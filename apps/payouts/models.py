"""Host wallets and payouts — immutable transaction ledger."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class HostWallet(TimeStampedModel):
    """One wallet per host. Balance is maintained via WalletTransactions."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallet"
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TZS")
    total_earned = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_paid_out = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"Wallet({self.user.email}): {self.balance} {self.currency}"


class WalletTransaction(TimeStampedModel):
    """Append-only ledger — never edit; correct with a reversal transaction."""

    class Type(models.TextChoices):
        EARNING = "EARNING", "Earning"           # completed booking payout credit
        PAYOUT = "PAYOUT", "Payout"              # debit for withdrawal
        REVERSAL = "REVERSAL", "Reversal"        # rejected payout credited back
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"  # staff correction
        REFUND_CLAWBACK = "REFUND_CLAWBACK", "Refund Clawback"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        HostWallet, on_delete=models.PROTECT, related_name="transactions"
    )
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)  # signed
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True,
        on_delete=models.PROTECT, related_name="wallet_transactions",
    )
    payout = models.ForeignKey(
        "Payout", null=True, blank=True,
        on_delete=models.PROTECT, related_name="wallet_transactions",
    )
    reference = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "transaction_type"],
                condition=models.Q(transaction_type="EARNING"),
                name="unique_earning_per_booking",
            )
        ]


class PayoutMethod(UUIDModel):
    class Type(models.TextChoices):
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
        BANK = "BANK", "Bank Transfer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="payout_methods",
    )
    method_type = models.CharField(max_length=20, choices=Type.choices)
    label = models.CharField(max_length=100)
    account_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=64)
    provider_name = models.CharField(max_length=100, blank=True)  # e.g. M-Pesa, CRDB
    currency = models.CharField(max_length=3, default="TZS")
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)


class Payout(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        REJECTED = "REJECTED", "Rejected"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payouts"
    )
    method = models.ForeignKey(
        PayoutMethod, on_delete=models.PROTECT, related_name="payouts"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reference = models.CharField(max_length=64, unique=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payouts_processed",
    )
    rejection_reason = models.TextField(blank=True)
    external_reference = models.CharField(max_length=128, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "-requested_at"]),
                   models.Index(fields=["user", "status"])]
