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
    logger.info(txn.creator_amount)  # 39.99

    payouts = engine.process_weekly_payouts()
"""

from __future__ import annotations

import logging
import threading
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
MIN_PAYOUT_USD = Decimal("10.00")


def to_cents(amount: Decimal) -> int:
    """Convert a money amount to integer cents, rounding half-up.

    `int(amount * 100)` truncates toward zero, which always favours the
    platform: $10.999 became 1099 cents, not 1100. Sub-cent amounts arise in
    normal operation because the creator's share is the remainder left after
    quantising the platform fee (F206).
    """
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)  # minimum payout threshold


class PayoutStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    #: No transfer backend was available, so nothing was sent. Distinct from
    #: PAID: the creator's balance is NOT debited and their ledger does not
    #: claim they were paid. Simulation previously reused PAID, which told a
    #: creator they had received money that never left the platform (F204).
    SIMULATED = "simulated"


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
    #: Set when a payout settles this transaction. Payouts previously listed
    #: every historical transaction for the creator, so summing across payouts
    #: double-counted and reconciliation was impossible (F207).
    settled_by_payout_id: str | None = None
    #: On a REFUND row: which refund policy was in force when it was applied.
    #: Stamped rather than re-derived from the live setting — otherwise changing
    #: the setting silently rewrites the meaning of every historical refund and
    #: the ledger stops reconciling. See monetization/refund_policy.py.
    refund_policy_applied: str | None = None

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
    #: Money the platform is owed back, under the DEDUCT_NEXT_PAYOUT policy:
    #: a sale was refunded after its payout had already sent the creator's share.
    #: Netted off future earnings before anything becomes payable. Kept separate
    #: from ``pending_usd`` so a debt never presents as a negative balance the
    #: creator cannot act on.
    recoverable_usd: Decimal = Decimal("0.00")

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
        session_factory=None,
    ) -> None:
        self.platform_fee_pct = platform_fee_pct
        self.creator_share_pct = Decimal("1.00") - platform_fee_pct
        self.min_payout_usd = min_payout_usd
        #: SQLAlchemy sessionmaker for the creator ledger tables. Without one the
        #: engine runs entirely in memory, which is the mode tests and paper
        #: trading use and is not a failure. With one, every sale, refund,
        #: balance and payout is written through and reloaded on construction.
        self._session_factory = session_factory

        self._transactions: dict[str, SaleTransaction] = {}
        self._balances: dict[str, CreatorBalance] = {}
        self._payouts: dict[str, PayoutRecord] = {}
        #: Where the refund policy is read from. None means "use the process
        #: default store"; tests inject a stand-in. Never cached — see
        #: resolve_refund_policy for why.
        self.config_store = None
        # `record_sale` credits pending_usd while `process_weekly_payouts`
        # reads it, transfers, and writes it back. There was no lock anywhere
        # in this module, so the read-modify-write raced and the payout also
        # iterated `_balances` while sales could insert into it (F203).
        self._lock = threading.RLock()

        self._load_from_db()

    # ── Persistence ───────────────────────────────────────────────────────────
    # The ledger tables are the durable record; the dictionaries above are a
    # working set loaded from them. Everything is written through, and a write
    # the database rejected raises rather than leaving memory ahead of the
    # ledger — a sale the ledger did not record has not happened.

    def _write(self, fn) -> None:
        """Run ``fn(session)`` in one transaction, or raise having changed nothing."""
        if not self._session_factory:
            return
        session = self._session_factory()
        try:
            fn(session)
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                logger.debug("Creator ledger rollback failed", exc_info=True)
            logger.exception("Creator ledger write failed")
            raise
        finally:
            try:
                session.close()
            except Exception:
                logger.debug("Creator ledger session close failed", exc_info=True)

    @staticmethod
    def _sale_row(txn: SaleTransaction):
        from database.models import CreatorSale

        return CreatorSale(
            transaction_id=txn.transaction_id,
            strategy_id=txn.strategy_id,
            creator_id=txn.creator_id,
            buyer_id=txn.buyer_id,
            gross_amount=txn.gross_amount,
            platform_fee=txn.platform_fee,
            creator_amount=txn.creator_amount,
            currency=txn.currency,
            transaction_type=str(txn.transaction_type),
            stripe_payment_intent_id=txn.stripe_payment_intent_id,
            settled_by_payout_id=txn.settled_by_payout_id,
            refund_policy_applied=txn.refund_policy_applied,
            created_at=txn.created_at,
        )

    def _upsert_payout(self, session, payout: PayoutRecord) -> None:
        from database.models import CreatorPayoutRow

        row = session.query(CreatorPayoutRow).filter_by(payout_id=payout.payout_id).one_or_none()
        if row is None:
            row = CreatorPayoutRow(
                payout_id=payout.payout_id,
                creator_id=payout.creator_id,
                # The payout id doubles as the idempotency key today, because
                # nothing retries a payout yet. The column is separate so a
                # retry path can reuse the key of the attempt it is retrying
                # rather than mint a new payout — which is the only way it stops
                # a timed-out-but-successful transfer being sent twice. Reusing
                # payout_id as the key does NOT provide that on its own.
                idempotency_key=payout.payout_id,
                created_at=payout.created_at,
            )
            session.add(row)
        row.amount_usd = payout.amount_usd
        row.currency = payout.currency
        row.status = str(payout.status)
        row.stripe_transfer_id = payout.stripe_transfer_id
        row.failure_reason = payout.failure_reason
        row.completed_at = payout.completed_at

    def _mark_settled(self, session, payout: PayoutRecord) -> None:
        from database.models import CreatorSale

        for txn_id in payout.transaction_ids:
            row = session.query(CreatorSale).filter_by(transaction_id=txn_id).one_or_none()
            if row is not None:
                row.settled_by_payout_id = payout.payout_id

    def _upsert_balance(self, session, bal: CreatorBalance) -> None:
        from database.models import CreatorBalanceRow

        row = session.get(CreatorBalanceRow, bal.creator_id)
        if row is None:
            row = CreatorBalanceRow(creator_id=bal.creator_id)
            session.add(row)
        row.pending_usd = bal.pending_usd
        row.total_earned_usd = bal.total_earned_usd
        row.total_paid_usd = bal.total_paid_usd
        row.recoverable_usd = bal.recoverable_usd
        row.stripe_account_id = bal.stripe_account_id
        row.last_payout_at = bal.last_payout_at
        # Optimistic-lock counter. Nothing reads it yet — the engine is
        # single-process today — but every write must advance it, or the column
        # is useless the moment a second worker starts writing.
        row.version = (row.version or 0) + 1

    def _load_from_db(self) -> None:
        """Restore sales, balances and payouts from the ledger tables.

        Without this the tables would be write-only: a restart would still
        forget every sale and every balance, which is the defect the tables
        exist to fix (F208).
        """
        if not self._session_factory:
            return
        from database.models import CreatorBalanceRow, CreatorPayoutRow, CreatorSale

        session = self._session_factory()
        try:
            for row in session.query(CreatorSale).all():
                self._transactions[row.transaction_id] = SaleTransaction(
                    transaction_id=row.transaction_id,
                    strategy_id=row.strategy_id,
                    creator_id=row.creator_id,
                    buyer_id=row.buyer_id,
                    gross_amount=Decimal(str(row.gross_amount)),
                    platform_fee=Decimal(str(row.platform_fee)),
                    creator_amount=Decimal(str(row.creator_amount)),
                    currency=row.currency,
                    transaction_type=TransactionType(row.transaction_type),
                    stripe_payment_intent_id=row.stripe_payment_intent_id,
                    created_at=row.created_at,
                    settled_by_payout_id=row.settled_by_payout_id,
                    refund_policy_applied=row.refund_policy_applied,
                )

            for row in session.query(CreatorBalanceRow).all():
                self._balances[row.creator_id] = CreatorBalance(
                    creator_id=row.creator_id,
                    pending_usd=Decimal(str(row.pending_usd)),
                    total_earned_usd=Decimal(str(row.total_earned_usd)),
                    total_paid_usd=Decimal(str(row.total_paid_usd)),
                    last_payout_at=row.last_payout_at,
                    stripe_account_id=row.stripe_account_id,
                    recoverable_usd=Decimal(str(row.recoverable_usd)),
                )

            for row in session.query(CreatorPayoutRow).all():
                # transaction_ids is not a column: it is exactly the set of sales
                # this payout settled, which the foreign key already records.
                settled = [
                    t.transaction_id for t in self._transactions.values() if t.settled_by_payout_id == row.payout_id
                ]
                self._payouts[row.payout_id] = PayoutRecord(
                    payout_id=row.payout_id,
                    creator_id=row.creator_id,
                    amount_usd=Decimal(str(row.amount_usd)),
                    currency=row.currency,
                    status=PayoutStatus(row.status),
                    stripe_transfer_id=row.stripe_transfer_id,
                    transaction_ids=settled,
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                    failure_reason=row.failure_reason,
                )
            logger.info(
                "Creator ledger restored: %d sales, %d balances, %d payouts",
                len(self._transactions),
                len(self._balances),
                len(self._payouts),
            )
        except Exception:
            logger.exception("Creator ledger load failed — starting from an empty working set")
        finally:
            try:
                session.close()
            except Exception:
                logger.debug("Creator ledger session close failed", exc_info=True)

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
        # Credit creator balance under the lock: a payout cycle may be reading
        # and writing this same field concurrently (F203).
        with self._lock:
            bal = self._get_or_create_balance(creator_id)
            before = (bal.pending_usd, bal.total_earned_usd, bal.recoverable_usd)
            bal.total_earned_usd += creator_amount
            # A debt carried from a refunded-after-payout sale is netted off
            # first. Without this, "deduct from next payout" would be a label on
            # a number nothing ever reads.
            if bal.recoverable_usd > 0:
                applied = min(bal.recoverable_usd, creator_amount)
                bal.recoverable_usd -= applied
                creator_amount_net = creator_amount - applied
                logger.info(
                    "Sale offset against carried refund debt: creator=%s applied=%.2f remaining_debt=%.2f",
                    creator_id,
                    float(applied),
                    float(bal.recoverable_usd),
                )
            else:
                creator_amount_net = creator_amount
            bal.pending_usd += creator_amount_net

            # Write the sale and the balance in one transaction, and only keep
            # the in-memory change if it landed. A sale the ledger rejected has
            # not happened, and reporting it would leave the balance moved in
            # memory with no durable record to reconcile against.
            try:
                self._write(lambda s: (s.add(self._sale_row(txn)), self._upsert_balance(s, bal)))
            except Exception:
                bal.pending_usd, bal.total_earned_usd, bal.recoverable_usd = (
                    before[0],
                    before[1],
                    before[2],
                )
                raise
            self._transactions[txn.transaction_id] = txn

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
        Record a refund and recover the creator's share according to policy.

        The interesting case is a sale that has already been **settled by a
        payout**: the creator's share has left the platform, so refunding the
        buyer means the money has to come back from somewhere. Which of the
        three answers applies is the operator's setting — see
        monetization/refund_policy.py — and the one actually used is stamped on
        the refund row rather than re-read later.

        For a sale that has not been paid out, the creator's share is still
        pending and every policy behaves the same: reverse it.

        This previously clamped the balance with ``max(Decimal("0.00"), ...)``
        and never looked at whether the sale had been settled, so the shortfall
        on a paid-out refund was neither deferred nor debited — it was silently
        forgotten and there was nothing left to reconcile against.

        Args:
            original_transaction_id: The transaction being refunded.
            refund_amount: Partial refund amount (None = full refund).

        Returns:
            Refund SaleTransaction, or None if original not found.
        """
        from monetization.refund_policy import RefundPolicy, resolve_refund_policy

        orig = self._transactions.get(original_transaction_id)
        if not orig:
            return None

        gross = (
            Decimal(str(refund_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if refund_amount is not None
            else orig.gross_amount
        )
        platform_fee = (gross * self.platform_fee_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Subtract rather than recompute, so platform_fee + creator_amount is
        # exactly gross even when the percentage does not divide evenly (F206).
        creator_amount = gross - platform_fee

        policy = resolve_refund_policy(store=self.config_store)

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
            refund_policy_applied=policy.value,
        )

        with self._lock:
            bal = self._get_or_create_balance(orig.creator_id)
            already_paid_out = orig.settled_by_payout_id is not None

            if not already_paid_out:
                # The money never left. Reverse it; no policy required.
                bal.pending_usd -= creator_amount
                bal.total_earned_usd -= creator_amount
            elif policy is RefundPolicy.PLATFORM_ABSORBS:
                # The creator keeps what they were paid; the platform funds the
                # buyer's refund out of its own share. Their ledger is untouched.
                pass
            elif policy is RefundPolicy.ALLOW_NEGATIVE_BALANCE:
                bal.pending_usd -= creator_amount
                bal.total_earned_usd -= creator_amount
            else:  # DEDUCT_NEXT_PAYOUT
                # Take what is pending, carry the rest as a debt against future
                # earnings. pending_usd never goes below zero.
                from_pending = min(max(bal.pending_usd, Decimal("0.00")), creator_amount)
                bal.pending_usd -= from_pending
                bal.recoverable_usd += creator_amount - from_pending
                bal.total_earned_usd -= creator_amount

            # Reversing more than a creator ever earned is not meaningful; it
            # would make total_earned a running figure rather than a total.
            if bal.total_earned_usd < 0:
                bal.total_earned_usd = Decimal("0.00")

            self._write(lambda s: (s.add(self._sale_row(refund_txn)), self._upsert_balance(s, bal)))
            self._transactions[refund_txn.transaction_id] = refund_txn

        logger.info(
            "Refund recorded: original=%s amount=%.2f settled=%s policy=%s",
            original_transaction_id,
            float(gross),
            already_paid_out,
            policy.value,
        )
        return refund_txn

    # ── Payouts ───────────────────────────────────────────────────────────────

    def register_stripe_account(self, creator_id: str, stripe_account_id: str) -> None:
        """Link a creator's Stripe Connect account for payouts."""
        with self._lock:
            bal = self._get_or_create_balance(creator_id)
            bal.stripe_account_id = stripe_account_id
            # Durable: a restart that forgets the payout account makes every
            # creator ineligible and the next cycle silently pays nobody.
            self._write(lambda s: self._upsert_balance(s, bal))
        logger.info(
            "Stripe account registered: creator=%s account=%s",
            creator_id,
            stripe_account_id,
        )

    def process_weekly_payouts(self) -> list[PayoutRecord]:
        """
        Process payouts for all eligible creators.

        Eligibility: pending_usd >= MIN_PAYOUT_USD AND stripe_account_id set.

        With no transfer backend available the payout is recorded as
        ``SIMULATED`` and the balance is left untouched — it is NOT reported as
        paid. Simulation previously reused ``PAID`` and zeroed the balance, so
        a creator's ledger claimed money that never left the platform (F204).

        Returns:
            List of PayoutRecord objects created this cycle.
        """
        payouts: list[PayoutRecord] = []

        # Snapshot under the lock: `record_sale` may insert a new creator while
        # this cycle iterates, which would raise "dictionary changed size
        # during iteration" (F203).
        with self._lock:
            balances = list(self._balances.items())

        for creator_id, bal in balances:
            if not bal.is_payout_eligible:
                continue

            amount = bal.pending_usd
            # Only transactions no previous payout has settled. This used to
            # list every transaction the creator had ever had, so summing
            # across payouts double-counted (F207).
            payout_txn_ids = [
                t.transaction_id
                for t in self._transactions.values()
                if t.creator_id == creator_id and t.creator_amount > 0 and t.settled_by_payout_id is None
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
                # No transfer backend. Record what happened without claiming a
                # payment occurred, and leave the balance intact so the money
                # is still owed and will be picked up by the next cycle (F204).
                payout.status = PayoutStatus.SIMULATED
                payout.failure_reason = (
                    "No transfer backend available (stripe package not installed "
                    "or no payout account); nothing was sent and the balance is "
                    "unchanged."
                )
                logger.warning(
                    "Payout NOT sent — no transfer backend: creator=%s amount=%.2f. Balance left pending.",
                    creator_id,
                    float(amount),
                )

            self._payouts[payout.payout_id] = payout

            if payout.status == PayoutStatus.PAID:
                self._settle_paid_payout(bal, amount, payout)
                # Payout row, the sales it settled, and the debited balance in
                # one transaction. Splitting them would let a crash leave a paid
                # payout whose sales are still unsettled — and the next cycle
                # would pay for them again (F207).
                self._write(
                    lambda s, p=payout, b=bal: (
                        self._upsert_payout(s, p),
                        self._mark_settled(s, p),
                        self._upsert_balance(s, b),
                    )
                )
            else:
                # Not paid: record what happened, but nothing is settled and the
                # balance is untouched, so only the payout row is written.
                self._write(lambda s, p=payout: self._upsert_payout(s, p))

            payouts.append(payout)

        return payouts

    def _settle_paid_payout(
        self,
        bal: CreatorBalance,
        amount: Decimal,
        payout: PayoutRecord | None = None,
    ) -> None:
        """Debit a completed payout from the creator's pending balance.

        This used to assign ``Decimal("0.00")``. The amount is captured before
        a network transfer that takes seconds, so anything ``record_sale``
        credited in that window was silently destroyed — measured at $40 lost
        on a $50 sale landing mid-payout (F203).

        Subtracting is the whole fix; the clamp guards the case where a caller
        settles more than is pending, which must not push a creator into debt.
        """
        with self._lock:
            bal.total_paid_usd += amount
            bal.pending_usd = max(Decimal("0.00"), bal.pending_usd - amount)
            bal.last_payout_at = datetime.now(UTC)
            if payout is not None:
                # Mark exactly which transactions this payout settled, so the
                # next cycle does not re-claim them (F207).
                for txn_id in payout.transaction_ids:
                    txn = self._transactions.get(txn_id)
                    if txn is not None:
                        txn.settled_by_payout_id = payout.payout_id

    def _execute_stripe_transfer(self, payout: PayoutRecord, bal: CreatorBalance) -> PayoutRecord:
        """Execute a Stripe Connect transfer to the creator's account."""
        try:
            transfer = _stripe.Transfer.create(  # type: ignore[union-attr]
                amount=to_cents(payout.amount_usd),
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
            # This had two %s placeholders and one argument, so logging raised
            # while formatting and the record was never emitted — the failure
            # path for a creator payout was diagnostically blind while
            # `failure_reason` told the operator to check logs that had nothing
            # in them (F205). logger.exception already attaches the traceback.
            logger.exception("Stripe transfer failed: creator=%s", payout.creator_id)

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
