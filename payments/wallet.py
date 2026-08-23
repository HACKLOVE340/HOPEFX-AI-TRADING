# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Wallet Management Module

Handles user wallet operations including balance management,
deposits, withdrawals, and transaction tracking.

Note: This wallet ONLY handles subscription fees and commission payments.
Trading capital is managed directly by brokers/prop firms.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from invariants.enforcement import enforce_wallet_movement
from invariants.payments import verify_amount_valid

#: Every balance in this wallet is an exact multiple of a cent. See _validate_amount.
CENTS = Decimal("0.01")

logger = logging.getLogger(__name__)


class WalletType:
    """Wallet type constants"""

    SUBSCRIPTION = "subscription"
    COMMISSION = "commission"


class WalletStatus:
    """Wallet status constants"""

    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Wallet:
    """Represents a user's wallet"""

    def __init__(
        self,
        wallet_id: str,
        user_id: str,
        subscription_balance: Decimal = Decimal("0.00"),
        commission_balance: Decimal = Decimal("0.00"),
        currency: str = "USD",
        status: str = WalletStatus.ACTIVE,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.wallet_id = wallet_id
        self.user_id = user_id
        self.subscription_balance = subscription_balance
        self.commission_balance = commission_balance
        self.currency = currency
        self.status = status
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)

    def to_dict(self) -> dict:
        """Convert wallet to dictionary"""
        return {
            "wallet_id": self.wallet_id,
            "user_id": self.user_id,
            "subscription_balance": float(self.subscription_balance),
            "commission_balance": float(self.commission_balance),
            "total_balance": float(self.subscription_balance + self.commission_balance),
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class WalletManager:
    """
    Manages wallet operations with DB persistence.

    Pass a SQLAlchemy session_factory to enable persistence.
    Without it, falls back to in-memory storage (tests / paper trading).
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        # In-memory fallback
        self._wallets: dict[str, Wallet] = {}
        self._transaction_history: dict[str, list[dict]] = {}
        # Serialises every balance read-modify-write. ``balance += amount`` and
        # the check-then-subtract in debit_wallet are not atomic: without this,
        # concurrent credits lose deposits and concurrent debits overdraw the
        # account past zero (both reproduced in tests/unit/test_wallet_ledger.py).
        # Re-entrant because transfer_between_wallets holds it across a debit
        # and a credit that each take it again.
        self._lock = threading.RLock()
        logger.info("WalletManager initialized (DB=%s)", session_factory is not None)

    @staticmethod
    def _new_transaction_id() -> str:
        """
        A ledger row identity.

        ``TXN-%Y%m%d%H%M%S`` is a timestamp, not an identity: two movements in
        the same second produce the same string, and ``transaction_id`` is a
        UNIQUE column. The second INSERT is rejected while the in-memory balance
        has already moved. Mirrors payments/transaction_manager.py.
        """
        return f"TXN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def _validate_amount(amount: Decimal) -> str | None:
        """Return an error message if ``amount`` may not move money, else None.

        Runs before any comparison: ``Decimal("NaN") <= 0`` raises
        InvalidOperation rather than returning False, so a NaN amount used to
        crash the caller instead of being refused.
        """
        try:
            as_float = float(amount)
        except (TypeError, ValueError, ArithmeticError):
            return "Amount is not a valid number"
        if verify_amount_valid(as_float):
            return "Amount must be positive"
        # Sub-cent amounts are refused rather than rounded. balance_after is
        # persisted to a Float column; a balance that is an exact multiple of a
        # cent survives that round-trip exactly, while a sub-cent residue would
        # live in memory and be lost on restart — money destroyed silently.
        # Rounding it here would instead move money without the caller asking.
        # This wallet carries subscription fees and commissions; neither has a
        # legitimate sub-cent movement.
        try:
            if amount != amount.quantize(CENTS, rounding=ROUND_HALF_UP):
                return "Amount must be a whole number of cents"
        except (InvalidOperation, AttributeError):
            return "Amount is not a valid number"
        return None

    @staticmethod
    def _read_balance(wallet: "Wallet", wallet_type: str) -> Decimal | None:
        if wallet_type == WalletType.SUBSCRIPTION:
            return wallet.subscription_balance
        if wallet_type == WalletType.COMMISSION:
            return wallet.commission_balance
        return None

    @staticmethod
    def _write_balance(wallet: "Wallet", wallet_type: str, value: Decimal) -> None:
        if wallet_type == WalletType.SUBSCRIPTION:
            wallet.subscription_balance = value
        else:
            wallet.commission_balance = value

    def set_session_factory(self, session_factory):
        """Wire in DB session factory after construction."""
        self._session_factory = session_factory

    def _persist_transaction(self, user_id: str, txn: dict) -> bool:
        """
        Write a transaction record to the DB.

        Returns True when the row is durable — or when there is no DB configured
        at all, which is the in-memory mode used by tests and paper trading and
        is not a failure. Returns False only when a configured backend rejected
        the write; the caller must then undo the balance change rather than
        report a credit the ledger has no record of.
        """
        if not self._session_factory:
            return True
        try:
            from database.models import WalletTransaction

            with self._session_factory() as session:
                session.add(
                    WalletTransaction(
                        transaction_id=txn["transaction_id"],
                        user_id=user_id,
                        transaction_type=txn["type"],
                        amount=txn["amount"],
                        balance_after=txn["balance_after"],
                        currency=txn.get("currency", "USD"),
                        reference=txn.get("reference"),
                        status=txn.get("status", "completed"),
                        notes=txn.get("wallet_type"),
                    )
                )
                session.commit()
            return True
        except Exception:
            logger.exception("Wallet ledger write failed: user=%s txn=%s", user_id, txn.get("transaction_id"))
            return False

    def _load_balance_from_db(self, user_id: str, wallet_type: str = WalletType.SUBSCRIPTION) -> Decimal | None:
        """
        Read the latest balance_after for one of the user's two wallets.

        The wallet type has to be part of the filter. Without it this took the
        newest row for the user regardless of which wallet it belonged to and
        assigned its balance_after to ``subscription_balance``, so a commission
        credit followed by a restart silently overwrote the subscription balance
        with an unrelated number. credit/debit_wallet store the type in
        ``notes``, which is what makes the filter possible.
        """
        if not self._session_factory:
            return None
        try:
            from database.models import WalletTransaction

            with self._session_factory() as session:
                row = (
                    session.query(WalletTransaction)
                    .filter_by(user_id=user_id, notes=wallet_type)
                    .order_by(WalletTransaction.id.desc())
                    .first()
                )
                if row:
                    return Decimal(str(row.balance_after))
        except Exception:
            logger.exception("Wallet DB read failed: user=%s wallet_type=%s", user_id, wallet_type)
        return None

    def create_wallet(
        self,
        user_id: str,
        initial_balance: Decimal = Decimal("0.00"),
        currency: str = "USD",
    ) -> Wallet:
        """
        Create a new wallet for a user

        Args:
            user_id: User identifier
            initial_balance: Starting balance
            currency: Wallet currency (default: USD)

        Returns:
            Created Wallet object
        """
        wallet_id = f"WAL-{user_id}"

        with self._lock:
            # Check if wallet already exists in memory
            if wallet_id in self._wallets:
                return self._wallets[wallet_id]

            # Restore each balance from its own ledger rows. Reading one number
            # and applying it to the subscription wallet conflated the two.
            db_subscription = self._load_balance_from_db(user_id, WalletType.SUBSCRIPTION)
            db_commission = self._load_balance_from_db(user_id, WalletType.COMMISSION)
            starting_balance = db_subscription if db_subscription is not None else initial_balance
            starting_commission = db_commission if db_commission is not None else Decimal("0.00")

            wallet = Wallet(
                wallet_id=wallet_id,
                user_id=user_id,
                subscription_balance=starting_balance,
                commission_balance=starting_commission,
                currency=currency,
                status=WalletStatus.ACTIVE,
            )

            self._wallets[wallet_id] = wallet
            self._transaction_history.setdefault(user_id, [])

        logger.info(
            "Created wallet %s for user %s (subscription=%s commission=%s)",
            wallet_id,
            user_id,
            starting_balance,
            starting_commission,
        )

        return wallet

    def get_wallet(self, user_id: str) -> Wallet | None:
        """
        Get wallet for a user

        Args:
            user_id: User identifier

        Returns:
            Wallet object or None if not found
        """
        wallet_id = f"WAL-{user_id}"
        with self._lock:
            return self._wallets.get(wallet_id)

    def get_balance(self, user_id: str, wallet_type: str | None = None) -> dict:
        """
        Get wallet balance(s)

        Args:
            user_id: User identifier
            wallet_type: Specific wallet type or None for all

        Returns:
            Balance information dictionary
        """
        # Under the lock: a transfer is two movements, and a reader that samples
        # between them sees a total short by the transferred amount. Locking the
        # writers is not enough — the read has to be a snapshot too.
        with self._lock:
            wallet = self._wallets.get(f"WAL-{user_id}")

            if not wallet:
                return {
                    "subscription_balance": 0.00,
                    "commission_balance": 0.00,
                    "total_balance": 0.00,
                    "currency": "USD",
                }

            subscription = wallet.subscription_balance
            commission = wallet.commission_balance
            currency = wallet.currency

        if wallet_type == WalletType.SUBSCRIPTION:
            return {
                "balance": float(subscription),
                "wallet_type": "subscription",
                "currency": currency,
            }
        if wallet_type == WalletType.COMMISSION:
            return {
                "balance": float(commission),
                "wallet_type": "commission",
                "currency": currency,
            }
        return {
            "subscription_balance": float(subscription),
            "commission_balance": float(commission),
            "total_balance": float(subscription + commission),
            "currency": currency,
        }

    def _apply_movement(
        self,
        *,
        user_id: str,
        amount: Decimal,
        wallet_type: str,
        transaction_type: str,
        sign: int,
        method: str | None = None,
        reference: str | None = None,
    ) -> tuple[bool, str, dict | None]:
        """
        The single balance write path, shared by credit and debit.

        Everything from reading the balance to persisting the ledger row happens
        under one lock. Splitting it — read, check, then write — is what let
        concurrent credits lose deposits and concurrent debits overdraw the
        account past zero. The movement is committed only if it reconciles and
        the ledger row is durable; otherwise the balance is restored.
        """
        error = self._validate_amount(amount)
        if error:
            return False, error, None

        with self._lock:
            wallet = self.get_wallet(user_id)
            if not wallet:
                if sign < 0:
                    return False, "Wallet not found", None
                wallet = self.create_wallet(user_id)

            if wallet.status != WalletStatus.ACTIVE:
                return False, f"Wallet is {wallet.status}", None

            before = self._read_balance(wallet, wallet_type)
            if before is None:
                return False, f"Invalid wallet type: {wallet_type}", None

            if sign < 0 and before < amount:
                kind = "subscription" if wallet_type == WalletType.SUBSCRIPTION else "commission"
                return False, f"Insufficient {kind} balance", None

            delta = amount if sign > 0 else -amount
            expected = before + delta
            self._write_balance(wallet, wallet_type, expected)
            previous_updated_at = wallet.updated_at
            wallet.updated_at = datetime.now(UTC)

            transaction = {
                "transaction_id": self._new_transaction_id(),
                "type": transaction_type,
                "wallet_type": wallet_type,
                "amount": float(amount),
                "reference": reference,
                # Read back from the wallet rather than reusing `expected`: this
                # is the number that goes into the ledger, so it is the number
                # that has to reconcile.
                "balance_after": float(self._read_balance(wallet, wallet_type)),
                "status": "completed",
                "created_at": datetime.now(UTC).isoformat(),
            }
            if method is not None:
                transaction["method"] = method

            def _rollback() -> None:
                self._write_balance(wallet, wallet_type, before)
                wallet.updated_at = previous_updated_at

            # Exact check first: Decimal arithmetic on whole cents is exact, so
            # any mismatch is corruption, not drift. This refuses regardless of
            # HOPEFX_INVARIANT_MODE — a balance that does not reconcile must
            # never be recorded.
            recorded = Decimal(str(transaction["balance_after"]))
            if recorded != expected:
                _rollback()
                logger.error(
                    "Wallet balance did not reconcile — movement refused: user=%s wallet_type=%s "
                    "before=%s delta=%s recorded=%s",
                    user_id,
                    wallet_type,
                    before,
                    delta,
                    recorded,
                )
                return False, "Balance did not reconcile; movement refused", None

            # Then the constitutional invariant, so the violation is counted,
            # logged and visible through enforcement.status. In `enforce` mode it
            # can also refuse; in `monitor` mode it observes.
            decision = enforce_wallet_movement(
                before=float(before),
                delta=float(delta),
                after=transaction["balance_after"],
                available=float(before) if sign < 0 else None,
            )
            if not decision.allowed:
                _rollback()
                return False, f"Movement refused by invariant: {decision.reason}", None

            history = self._transaction_history.setdefault(user_id, [])
            history.append(transaction)

            if not self._persist_transaction(user_id, transaction):
                history.pop()
                _rollback()
                return False, "Ledger write failed; movement refused", None

        verb = "Credited" if sign > 0 else "Debited"
        logger.info("%s %s %s %s wallet for user %s", verb, amount, "to" if sign > 0 else "from", wallet_type, user_id)
        return True, f"Wallet {'credited' if sign > 0 else 'debited'} successfully", transaction

    def credit_wallet(
        self,
        user_id: str,
        amount: Decimal,
        wallet_type: str = WalletType.SUBSCRIPTION,
        transaction_type: str = "deposit",
        method: str = "unknown",
        reference: str | None = None,
    ) -> tuple[bool, str, dict | None]:
        """
        Credit (add funds to) a wallet.

        Returns (success, message, transaction). Success means the balance moved
        **and** the ledger row is durable; if either fails nothing is changed.

        Args:
            user_id: User identifier
            amount: Amount to credit (must be a positive whole number of cents)
            wallet_type: Type of wallet to credit
            transaction_type: Type of transaction
            method: Payment method used
            reference: Transaction reference
        """
        return self._apply_movement(
            user_id=user_id,
            amount=amount,
            wallet_type=wallet_type,
            transaction_type=transaction_type,
            sign=1,
            method=method,
            reference=reference,
        )

    def debit_wallet(
        self,
        user_id: str,
        amount: Decimal,
        wallet_type: str = WalletType.SUBSCRIPTION,
        transaction_type: str = "withdrawal",
        reference: str | None = None,
    ) -> tuple[bool, str, dict | None]:
        """
        Debit (remove funds from) a wallet.

        Returns (success, message, transaction). Success means the balance moved
        **and** the ledger row is durable; if either fails nothing is changed.

        Args:
            user_id: User identifier
            amount: Amount to debit (must be a positive whole number of cents)
            wallet_type: Type of wallet to debit
            transaction_type: Type of transaction
            reference: Transaction reference
        """
        error = self._validate_amount(amount)
        if error:
            return False, error, None

        # AML gate — only applied to actual withdrawals, not internal debits.
        # Runs before the lock is taken: it does network/DB work and must not
        # hold up every other wallet movement in the process.
        if transaction_type == "withdrawal":
            wallet = self.get_wallet(user_id)
            if not wallet:
                return False, "Wallet not found", None
            try:
                from compliance.aml import get_aml_gate

                # Resolve the REAL KYC status from the authoritative compliance
                # manager. Wallet has no kyc_status field, so the previous
                # getattr() always yielded "unverified", making the gate's KYC
                # check operate on hardcoded data. Default to "unverified"
                # (fail closed) when the manager is unavailable.
                kyc_status = "unverified"
                try:
                    from core.app_state import app_state as _app_state

                    _cm = getattr(_app_state, "compliance_manager", None)
                    if _cm is not None:
                        kyc_status = "approved" if _cm.is_kyc_approved(user_id) else "unverified"
                except Exception:  # nosec B110 - fail closed: treat as unverified
                    kyc_status = "unverified"

                decision = get_aml_gate().check_withdrawal(
                    user_id=user_id,
                    amount=amount,
                    kyc_status=kyc_status,
                )
                if not decision.allowed:
                    logger.warning(
                        "AML blocked withdrawal for user %s: %s",
                        user_id,
                        decision.reason,
                    )
                    return False, f"Withdrawal blocked: {decision.reason}", None
            except Exception as _aml_err:
                # Fail CLOSED: never allow a money movement when the compliance
                # gate itself errors. A blocked withdrawal is recoverable; an
                # unscreened one is a regulatory violation.
                logger.error(
                    "AML check error — BLOCKING withdrawal (fail-closed) for user %s: %s",
                    user_id,
                    _aml_err,
                )
                return False, "Withdrawal temporarily unavailable (compliance check failed)", None

        return self._apply_movement(
            user_id=user_id,
            amount=amount,
            wallet_type=wallet_type,
            transaction_type=transaction_type,
            sign=-1,
            reference=reference,
        )

    def transfer_between_wallets(
        self, user_id: str, amount: Decimal, from_wallet: str, to_wallet: str
    ) -> tuple[bool, str]:
        """
        Transfer funds between wallet types

        Args:
            user_id: User identifier
            amount: Amount to transfer
            from_wallet: Source wallet type
            to_wallet: Destination wallet type

        Returns:
            Tuple of (success, message)
        """
        if amount <= 0:
            return False, "Amount must be positive"

        if from_wallet == to_wallet:
            return False, "Cannot transfer to same wallet"

        # The lock is re-entrant, and held across both legs so no observer ever
        # reads the state where the money has left one wallet and not arrived in
        # the other. Without it, get_balance() between the two calls reports a
        # total that is short by `amount`.
        with self._lock:
            # Debit from source
            success, message, _ = self.debit_wallet(
                user_id, amount, from_wallet, "transfer", f"Transfer to {to_wallet}"
            )

            if not success:
                return False, message

            # Credit to destination
            success, message, _ = self.credit_wallet(
                user_id,
                amount,
                to_wallet,
                "transfer",
                "internal",
                f"Transfer from {from_wallet}",
            )

            if not success:
                # Rollback debit. If the reversal itself fails the money is
                # stranded, so it is logged as a discrepancy rather than
                # reported as a clean rollback.
                reversed_ok, reversal_msg, _ = self.credit_wallet(
                    user_id,
                    amount,
                    from_wallet,
                    "reversal",
                    "internal",
                    "Transfer rollback",
                )
                if not reversed_ok:
                    logger.error(
                        "Transfer rollback FAILED — %s is unaccounted for: user=%s from=%s reason=%s",
                        amount,
                        user_id,
                        from_wallet,
                        reversal_msg,
                    )
                    return False, f"Transfer failed and rollback failed: {message}"
                return False, f"Transfer failed: {message}"

        logger.info("Transferred %s from %s to %s for user %s", amount, from_wallet, to_wallet, user_id)

        return True, "Transfer successful"

    def freeze_wallet(self, user_id: str) -> tuple[bool, str]:
        """
        Freeze a wallet (prevent transactions)

        Args:
            user_id: User identifier

        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            wallet = self._wallets.get(f"WAL-{user_id}")
            if not wallet:
                return False, "Wallet not found"

            wallet.status = WalletStatus.FROZEN
            wallet.updated_at = datetime.now(UTC)

        logger.warning("Wallet frozen for user %s", user_id)

        return True, "Wallet frozen successfully"

    def unfreeze_wallet(self, user_id: str) -> tuple[bool, str]:
        """
        Unfreeze a wallet

        Args:
            user_id: User identifier

        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            wallet = self._wallets.get(f"WAL-{user_id}")
            if not wallet:
                return False, "Wallet not found"

            wallet.status = WalletStatus.ACTIVE
            wallet.updated_at = datetime.now(UTC)

        logger.info("Wallet unfrozen for user %s", user_id)

        return True, "Wallet activated successfully"

    def get_transaction_history(self, user_id: str, limit: int = 50) -> list[dict]:
        """
        Get transaction history for a user

        Args:
            user_id: User identifier
            limit: Maximum number of transactions to return

        Returns:
            List of transaction dictionaries
        """
        with self._lock:
            transactions = self._transaction_history.get(user_id)
            if not transactions:
                return []
            # Copy under the lock: the caller must not hold a live reference to
            # a list a concurrent movement is appending to.
            return list(transactions[-limit:] if len(transactions) > limit else transactions)


# Global instance
wallet_manager = WalletManager()
