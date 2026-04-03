# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
monetization/revenue_split.py
==============================
Revenue split engine and seller payout system for the Strategy Marketplace.

Revenue split model
-------------------
Every purchase/subscription generates a transaction that is split between:
  - Platform fee:  20% of gross revenue (covers hosting, support, fraud)
  - Creator share: 80% of gross revenue (paid out to strategy author)

Payout schedule
---------------
Payouts are batched weekly (every Monday) for all creators with a pending
balance >= $10.00. Stripe Connect is used for payouts to creator accounts.

Payout states:
  PENDING   → balance accrued, not yet paid
  PROCESSING → payout initiated with Stripe
  PAID      → confirmed by Stripe webhook
  FAILED    → Stripe payout failed (retried next cycle)

Usage
-----
    from monetization.revenue_split import RevenueSplitEngine
    engine = RevenueSplitEngine()
    txn = engine.record_sale(
        strategy_id="strat-001",
        creator_id="creator-001",
        buyer_id="user-001",
        gross_amount=49.99,
        currency="USD",
    )
    print(txn.creator_amount)  # 39.99

    payouts = engine.process_weekly_payouts()
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from decimal import ROUND_HALF_UP, Decimal

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):  # Python 3.10 compat
        pass

logger = logging.getLogger(__name__)

# ── optional Stripe ───────────────────────────────────────────────────────────
try:
    import stripe as _stripe  # type: ignore

    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe = None  # type: ignore
    _STRIPE_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────
PLATFORM_FEE_PCT = Decimal("0.20")  # 20% platform fee
CREATOR_SHARE_PCT = Decimal("0.80")  # 80% to creator
MIN_PAYOUT_USD = Decimal("10.00")  # minimum payout threshold


class PayoutStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"


class TransactionType(StrEnum):
    PURCHASE = "purchase"
    SUBSCRIPTION = "subscription"
    REFUND = "refund"


@dataclass
class SaleTransaction:
    """A single marketplace sale, split between platform and creator."""

    transaction_id: str
    strategy_id: str
    creator_id: str
    buyer_id: str
    gross_amount: Decimal
    platform_fee: Decimal
    creator_amount: Decimal
    currency: str
    transaction_type: TransactionType
    stripe_payment_intent_id: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "strategy_id": self.strategy_id,
            "creator_id": self.creator_id,
            "buyer_id": self.buyer_id,
            "gross_amount": float(self.gross_amount),
            "platform_fee": float(self.platform_fee),
            "creator_amount": float(self.creator_amount),
            "currency": self.currency,
            "transaction_type": self.transaction_type.value,
            "stripe_payment_intent_id": self.stripe_payment_intent_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CreatorBalance:
    """Pending payout balance for a creator."""

    creator_id: str
    pending_usd: Decimal = Decimal("0.00")
    total_earned_usd: Decimal = Decimal("0.00")
    total_paid_usd: Decimal = Decimal("0.00")
    last_payout_at: datetime | None = None
    stripe_account_id: str | None = None  # Stripe Connect account

    @property
    def is_payout_eligible(self) -> bool:
        return self.pending_usd >= MIN_PAYOUT_USD and self.stripe_account_id is not None


@dataclass
class PayoutRecord:
    """A payout disbursement to a creator."""

    payout_id: str
    creator_id: str
    amount_usd: Decimal
    currency: str
    status: PayoutStatus
    stripe_transfer_id: str | None
    transaction_ids: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "payout_id": self.payout_id,
            "creator_id": self.creator_id,
            "amount_usd": float(self.amount_usd),
            "currency": self.currency,
            "status": self.status.value,
            "stripe_transfer_id": self.stripe_transfer_id,
            "transaction_count": len(self.transaction_ids),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "failure_reason": self.failure_reason,
        }


class RevenueSplitEngine:
    """
    Computes revenue splits, tracks creator balances, and processes payouts.

    All monetary values use Python Decimal for precision.
    """

    def __init__(
        self,
        platform_fee_pct: Decimal = PLATFORM_FEE_PCT,
        min_payout_usd: Decimal = MIN_PAYOUT_USD,
    ) -> None:
        self.platform_fee_pct = platform_fee_pct
        self.creator_share_pct = Decimal("1.00") - platform_fee_pct
        self.min_payout_usd = min_payout_usd

        self._transactions: dict[str, SaleTransaction] = {}
        self._balances: dict[str, CreatorBalance] = {}
        self._payouts: dict[str, PayoutRecord] = {}

    # ── Sales ─────────────────────────────────────────────────────────────────

    def record_sale(
        self,
        strategy_id: str,
        creator_id: str,
        buyer_id: str,
        gross_amount: float,
        currency: str = "USD",
        transaction_type: TransactionType = TransactionType.PURCHASE,
        stripe_payment_intent_id: str | None = None,
    ) -> SaleTransaction:
        """
        Record a marketplace sale and credit the creator's pending balance.

        Args:
            strategy_id: The strategy that was purchased.
            creator_id: The strategy author.
            buyer_id: The purchasing user.
            gross_amount: Total amount charged to buyer (USD).
            currency: ISO 4217 currency code.
            transaction_type: PURCHASE or SUBSCRIPTION.
            stripe_payment_intent_id: Stripe PI ID for reconciliation.

        Returns:
            SaleTransaction with platform_fee and creator_amount computed.
        """
        gross = Decimal(str(gross_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        platform_fee = (gross * self.platform_fee_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        creator_amount = gross - platform_fee

        txn = SaleTransaction(
            transaction_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            creator_id=creator_id,
            buyer_id=buyer_id,
            gross_amount=gross,
            platform_fee=platform_fee,
            creator_amount=creator_amount,
            currency=currency,
            transaction_type=transaction_type,
            stripe_payment_intent_id=stripe_payment_intent_id,
        )
        self._transactions[txn.transaction_id] = txn

        # Credit creator balance
        bal = self._get_or_create_balance(creator_id)
        bal.pending_usd += creator_amount
        bal.total_earned_usd += creator_amount

        logger.info(
            "Sale recorded: strategy=%s creator=%s gross=%.2f creator_share=%.2f",
            strategy_id,
            creator_id,
            float(gross),
            float(creator_amount),
        )
        return txn

    def record_refund(
        self,
        original_transaction_id: str,
        refund_amount: float | None = None,
    ) -> SaleTransaction | None:
        """
        Record a refund, debiting the creator's pending balance.

        Args:
            original_transaction_id: The transaction being refunded.
            refund_amount: Partial refund amount (None = full refund).

        Returns:
            Refund SaleTransaction, or None if original not found.
        """
        orig = self._transactions.get(original_transaction_id)
        if not orig:
            return None

        gross = (
            Decimal(str(refund_amount)).quantize(Decimal("0.01")) if refund_amount is not None else orig.gross_amount
        )
        platform_fee = (gross * self.platform_fee_pct).quantize(Decimal("0.01"))
        creator_amount = gross - platform_fee

        refund_txn = SaleTransaction(
            transaction_id=str(uuid.uuid4()),
            strategy_id=orig.strategy_id,
            creator_id=orig.creator_id,
            buyer_id=orig.buyer_id,
            gross_amount=-gross,
            platform_fee=-platform_fee,
            creator_amount=-creator_amount,
            currency=orig.currency,
            transaction_type=TransactionType.REFUND,
            stripe_payment_intent_id=None,
        )
        self._transactions[refund_txn.transaction_id] = refund_txn

        # Debit creator balance
        bal = self._get_or_create_balance(orig.creator_id)
        bal.pending_usd = max(Decimal("0.00"), bal.pending_usd - creator_amount)
        bal.total_earned_usd = max(Decimal("0.00"), bal.total_earned_usd - creator_amount)

        logger.info(
            "Refund recorded: original=%s amount=%.2f",
            original_transaction_id,
            float(gross),
        )
        return refund_txn

    # ── Payouts ───────────────────────────────────────────────────────────────

    def register_stripe_account(self, creator_id: str, stripe_account_id: str) -> None:
        """Link a creator's Stripe Connect account for payouts."""
        bal = self._get_or_create_balance(creator_id)
        bal.stripe_account_id = stripe_account_id
        logger.info(
            "Stripe account registered: creator=%s account=%s",
            creator_id,
            stripe_account_id,
        )

    def process_weekly_payouts(self) -> list[PayoutRecord]:
        """
        Process payouts for all eligible creators.

        Eligibility: pending_usd >= MIN_PAYOUT_USD AND stripe_account_id set.
        Uses Stripe Connect transfers if available, otherwise marks as PAID
        in simulation mode.

        Returns:
            List of PayoutRecord objects created this cycle.
        """
        payouts: list[PayoutRecord] = []

        for creator_id, bal in self._balances.items():
            if not bal.is_payout_eligible:
                continue

            amount = bal.pending_usd
            payout_txn_ids = [
                t.transaction_id
                for t in self._transactions.values()
                if t.creator_id == creator_id and t.creator_amount > 0
            ]

            payout = PayoutRecord(
                payout_id=str(uuid.uuid4()),
                creator_id=creator_id,
                amount_usd=amount,
                currency="USD",
                status=PayoutStatus.PROCESSING,
                stripe_transfer_id=None,
                transaction_ids=payout_txn_ids,
            )

            if _STRIPE_AVAILABLE and bal.stripe_account_id:
                payout = self._execute_stripe_transfer(payout, bal)
            else:
                # Simulation mode
                payout.status = PayoutStatus.PAID
                payout.completed_at = datetime.now(UTC)
                logger.info(
                    "Payout simulated (Stripe unavailable): creator=%s amount=%.2f",
                    creator_id,
                    float(amount),
                )

            self._payouts[payout.payout_id] = payout

            if payout.status == PayoutStatus.PAID:
                bal.total_paid_usd += amount
                bal.pending_usd = Decimal("0.00")
                bal.last_payout_at = datetime.now(UTC)

            payouts.append(payout)

        return payouts

    def _execute_stripe_transfer(self, payout: PayoutRecord, bal: CreatorBalance) -> PayoutRecord:
        """Execute a Stripe Connect transfer to the creator's account."""
        try:
            transfer = _stripe.Transfer.create(  # type: ignore[union-attr]
                amount=int(payout.amount_usd * 100),  # cents
                currency="usd",
                destination=bal.stripe_account_id,
                metadata={
                    "payout_id": payout.payout_id,
                    "creator_id": payout.creator_id,
                    "platform": "hopefx",
                },
            )
            payout.stripe_transfer_id = transfer.id
            payout.status = PayoutStatus.PAID
            payout.completed_at = datetime.now(UTC)
            logger.info(
                "Stripe transfer completed: creator=%s transfer=%s amount=%.2f",
                payout.creator_id,
                transfer.id,
                float(payout.amount_usd),
            )
        except Exception:
            payout.status = PayoutStatus.FAILED
            payout.failure_reason = "Transfer failed — check server logs"
            logger.exception("Stripe transfer failed: creator=%s error=%s", payout.creator_id)

        return payout

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_creator_balance(self, creator_id: str) -> CreatorBalance:
        return self._get_or_create_balance(creator_id)

    def get_creator_transactions(self, creator_id: str) -> list[SaleTransaction]:
        return [t for t in self._transactions.values() if t.creator_id == creator_id]

    def get_creator_payouts(self, creator_id: str) -> list[PayoutRecord]:
        return [p for p in self._payouts.values() if p.creator_id == creator_id]

    def get_platform_revenue(self) -> dict:
        """Return aggregate platform revenue metrics."""
        total_gross = sum(t.gross_amount for t in self._transactions.values() if t.gross_amount > 0)
        total_fees = sum(t.platform_fee for t in self._transactions.values() if t.platform_fee > 0)
        total_creator = sum(t.creator_amount for t in self._transactions.values() if t.creator_amount > 0)
        total_paid = sum(p.amount_usd for p in self._payouts.values() if p.status == PayoutStatus.PAID)

        return {
            "total_gross_revenue": float(total_gross),
            "total_platform_fees": float(total_fees),
            "total_creator_earnings": float(total_creator),
            "total_creator_payouts": float(total_paid),
            "total_transactions": len(self._transactions),
            "total_payouts": len(self._payouts),
            "platform_fee_pct": float(self.platform_fee_pct * 100),
        }

    def _get_or_create_balance(self, creator_id: str) -> CreatorBalance:
        if creator_id not in self._balances:
            self._balances[creator_id] = CreatorBalance(creator_id=creator_id)
        return self._balances[creator_id]


# Module-level singleton
revenue_engine = RevenueSplitEngine()
