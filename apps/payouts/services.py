"""Wallet + payout services. All balance mutations are atomic + ledger-backed."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.admin_panel.models import PlatformSetting
from apps.admin_panel.services import audit
from apps.common.exceptions import BusinessError, NotFoundError, PermissionDeniedError
from apps.common.utils import generate_reference, money

from .models import HostWallet, Payout, PayoutMethod, WalletTransaction


def get_wallet(user) -> HostWallet:
    wallet, _ = HostWallet.objects.get_or_create(
        user=user, defaults={"currency": getattr(user, "preferred_currency", "TZS")}
    )
    return wallet


@transaction.atomic
def _post(wallet_id, txn_type: str, amount: Decimal, description: str = "",
          booking=None, payout=None, reference: str = "") -> WalletTransaction:
    """Append a ledger row and update the balance — single atomic step."""
    wallet = HostWallet.objects.select_for_update().get(pk=wallet_id)
    new_balance = money(wallet.balance + amount)
    if new_balance < 0:
        raise BusinessError("Insufficient wallet balance.", code="INSUFFICIENT_FUNDS")
    txn = WalletTransaction.objects.create(
        wallet=wallet, transaction_type=txn_type, amount=amount,
        balance_after=new_balance, currency=wallet.currency,
        booking=booking, payout=payout,
        reference=reference or generate_reference("WTX"),
        description=description,
    )
    wallet.balance = new_balance
    update = {"balance", "updated_at"}
    if amount > 0 and txn_type == WalletTransaction.Type.EARNING:
        wallet.total_earned = F("total_earned") + amount
        update.add("total_earned")
    if txn_type == WalletTransaction.Type.PAYOUT:
        wallet.total_paid_out = F("total_paid_out") + abs(amount)
        update.add("total_paid_out")
    wallet.save(update_fields=list(update))
    return txn


@transaction.atomic
def credit_host_for_booking(booking) -> WalletTransaction | None:
    """Move a completed booking's host earnings into their wallet.

    Idempotent — the unique (booking, EARNING) constraint dedupes retries.
    """
    price = getattr(booking, "price", None)
    if price is None or price.host_payout_amount <= 0:
        return None
    host = booking.property.host
    wallet = get_wallet(host)
    try:
        return _post(
            wallet.id, WalletTransaction.Type.EARNING,
            money(price.host_payout_amount),
            description=f"Earnings for booking {booking.reference}",
            booking=booking,
        )
    except Exception as exc:
        # unique_earning_per_booking violation on retry -> already credited.
        from django.db import IntegrityError

        if isinstance(exc, IntegrityError):
            return None
        raise


@transaction.atomic
def request_payout(user, method_id, amount: Decimal,
                   idempotency_key: str | None = None) -> Payout:
    wallet = get_wallet(user)
    if idempotency_key:
        existing = Payout.objects.filter(
            idempotency_key=idempotency_key, user=user
        ).first()
        if existing is not None:
            return existing
    method = PayoutMethod.objects.filter(
        pk=method_id, user=user, is_active=True
    ).first()
    if method is None:
        raise NotFoundError("Payout method not found.", code="METHOD_NOT_FOUND")

    amount = money(amount)
    minimum = PlatformSetting.get_decimal("PAYOUT_MINIMUM", "1000")
    if amount < minimum:
        raise BusinessError(f"Minimum payout is {minimum} {wallet.currency}.",
                            code="BELOW_PAYOUT_MINIMUM")
    if amount > wallet.balance:
        raise BusinessError("Amount exceeds available balance.",
                            code="INSUFFICIENT_FUNDS")

    profile = getattr(user, "host_profile", None)
    if profile and profile.verification_status != profile.VerificationStatus.VERIFIED:
        raise BusinessError("Host must complete KYC before payouts.",
                            code="HOST_NOT_VERIFIED")

    payout = Payout.objects.create(
        user=user, method=method, amount=amount, currency=wallet.currency,
        reference=generate_reference("POT"), idempotency_key=idempotency_key or None,
    )
    # Funds are debited immediately and held as pending until the payout
    # resolves; a rejection posts a REVERSAL credit — the ledger stays
    # append-only.
    _post(wallet.id, WalletTransaction.Type.PAYOUT, -amount,
          description=f"Payout request {payout.reference}", payout=payout)
    HostWallet.objects.filter(pk=wallet.id).update(
        pending_balance=F("pending_balance") + amount
    )
    from apps.notifications.tasks import notify_payout_requested

    transaction.on_commit(
        lambda: notify_payout_requested.delay(str(payout.id))
    )
    return payout


@transaction.atomic
def process_payout(admin_user, payout_id, approve: bool, reason: str = "") -> Payout:
    payout = Payout.objects.select_for_update().filter(pk=payout_id).first()
    if payout is None:
        raise NotFoundError("Payout not found.", code="PAYOUT_NOT_FOUND")
    if payout.status != Payout.Status.PENDING:
        raise BusinessError("Payout already processed.", code="PAYOUT_ALREADY_PROCESSED")

    payout.processed_by = admin_user
    payout.processed_at = timezone.now()
    wallet = get_wallet(payout.user)
    if approve:
        payout.status = Payout.Status.COMPLETED
        payout.save(update_fields=["status", "processed_by", "processed_at",
                                   "updated_at"])
        HostWallet.objects.filter(pk=wallet.id).update(
            pending_balance=F("pending_balance") - payout.amount
        )
        from apps.notifications.tasks import notify_payout_completed

        notify_payout_completed.delay(str(payout.id))
    else:
        payout.status = Payout.Status.REJECTED
        payout.rejection_reason = reason
        payout.save(update_fields=["status", "rejection_reason", "processed_by",
                                   "processed_at", "updated_at"])
        HostWallet.objects.filter(pk=wallet.id).update(
            pending_balance=F("pending_balance") - payout.amount
        )
        _post(wallet.id, WalletTransaction.Type.REVERSAL, payout.amount,
              description=f"Reversal of payout {payout.reference}", payout=payout)
        from apps.notifications.tasks import notify_payout_failed

        transaction.on_commit(
            lambda: notify_payout_failed.delay(str(payout.id))
        )
    audit(actor=admin_user,
          action=f"payout.{'approved' if approve else 'rejected'}",
          target=payout, metadata={"reason": reason} if reason else None)
    return payout


def reconcile_wallet(user) -> dict:
    """Recompute balances from the ledger — the source of truth.

    ``balance`` must equal the latest transaction's ``balance_after``;
    ``pending_balance`` must equal open payouts. Any drift is corrected.
    """
    with transaction.atomic():
        wallet = HostWallet.objects.select_for_update().get(
            pk=get_wallet(user).pk
        )
        last_txn = wallet.transactions.order_by("-created_at").first()
        ledger_balance = last_txn.balance_after if last_txn else Decimal("0")
        open_payouts = Payout.objects.filter(
            user=user, status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING]
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        drift = wallet.balance != ledger_balance or wallet.pending_balance != open_payouts
        if drift:
            wallet.balance = ledger_balance
            wallet.pending_balance = open_payouts
            wallet.save(update_fields=["balance", "pending_balance", "updated_at"])
        return {
            "balance": str(wallet.balance),
            "pending_balance": str(wallet.pending_balance),
            "drift_corrected": drift,
        }
