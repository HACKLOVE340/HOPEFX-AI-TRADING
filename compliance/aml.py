"""
AML (Anti-Money Laundering) gate for withdrawals.

Rules enforced:
- Single withdrawal cap (default $10,000)
- Daily withdrawal limit per user (default $50,000)
- Velocity check: max N withdrawals per 24 h (default 5)
- KYC required for withdrawals above $1,000
- Suspicious pattern flag: withdrawal within 1 h of deposit of same amount

All limits are configurable via environment variables.
Decisions are logged to the compliance audit trail.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Configurable limits ───────────────────────────────────────────────────────
SINGLE_WITHDRAWAL_CAP = Decimal(os.getenv("AML_SINGLE_WITHDRAWAL_CAP", "10000"))
DAILY_WITHDRAWAL_LIMIT = Decimal(os.getenv("AML_DAILY_WITHDRAWAL_LIMIT", "50000"))
MAX_WITHDRAWALS_PER_DAY = int(os.getenv("AML_MAX_WITHDRAWALS_PER_DAY", "5"))
KYC_THRESHOLD = Decimal(os.getenv("AML_KYC_THRESHOLD", "1000"))
RAPID_TURNAROUND_HOURS = int(os.getenv("AML_RAPID_TURNAROUND_HOURS", "1"))


@dataclass
class AMLDecision:
    allowed: bool
    reason: str
    risk_score: float  # 0.0 – 1.0
    flags: list


class AMLGate:
    """
    Stateless AML gate. Requires a SQLAlchemy session_factory to query
    transaction history. Falls back to allow-all when DB is unavailable.
    """

    def __init__(self, session_factory=None):
        self._sf = session_factory

    def check_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        kyc_status: str = "unverified",
        currency: str = "USD",
    ) -> AMLDecision:
        """
        Evaluate a withdrawal request against AML rules.

        Returns AMLDecision. Caller must check `.allowed` before proceeding.
        """
        flags = []
        risk_score = 0.0

        # ── Rule 1: Single withdrawal cap ─────────────────────────────────────
        if amount > SINGLE_WITHDRAWAL_CAP:
            return AMLDecision(
                allowed=False,
                reason=f"Withdrawal of {amount} {currency} exceeds single-transaction cap of {SINGLE_WITHDRAWAL_CAP}",
                risk_score=1.0,
                flags=["EXCEEDS_SINGLE_CAP"],
            )

        # ── Rule 2: KYC required above threshold ──────────────────────────────
        if amount > KYC_THRESHOLD and kyc_status != "approved":
            return AMLDecision(
                allowed=False,
                reason=f"KYC approval required for withdrawals above {KYC_THRESHOLD} {currency}",
                risk_score=0.9,
                flags=["KYC_REQUIRED"],
            )

        # ── DB-dependent rules ────────────────────────────────────────────────
        if self._sf:
            try:
                decision = self._check_db_rules(user_id, amount, currency, flags, risk_score)
                if decision:
                    return decision
            except Exception as exc:
                logger.warning("AML DB check failed for user %s: %s — allowing (fail open)", user_id, exc)

        # ── Approved ──────────────────────────────────────────────────────────
        if flags:
            risk_score = min(risk_score + 0.1 * len(flags), 0.8)
            logger.warning("AML: withdrawal allowed with flags %s for user %s amount %s", flags, user_id, amount)
        else:
            logger.info("AML: withdrawal approved for user %s amount %s %s", user_id, amount, currency)

        return AMLDecision(allowed=True, reason="Approved", risk_score=risk_score, flags=flags)

    def _check_db_rules(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        flags: list,
        risk_score: float,
    ) -> Optional[AMLDecision]:
        """DB-backed rules. Returns AMLDecision to block, or None to continue."""
        from database.models import WalletTransaction

        now = datetime.now(timezone.utc)
        day_start = now - timedelta(hours=24)

        with self._sf() as session:
            recent = (
                session.query(WalletTransaction)
                .filter(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.transaction_type == "withdrawal",
                    WalletTransaction.created_at >= day_start,
                    WalletTransaction.status == "completed",
                )
                .all()
            )

            # Rule 3: Daily withdrawal count
            if len(recent) >= MAX_WITHDRAWALS_PER_DAY:
                return AMLDecision(
                    allowed=False,
                    reason=f"Daily withdrawal limit of {MAX_WITHDRAWALS_PER_DAY} transactions reached",
                    risk_score=0.85,
                    flags=["VELOCITY_LIMIT"],
                )

            # Rule 4: Daily withdrawal volume
            daily_total = sum(Decimal(str(t.amount)) for t in recent)
            if daily_total + amount > DAILY_WITHDRAWAL_LIMIT:
                return AMLDecision(
                    allowed=False,
                    reason=f"Daily withdrawal limit of {DAILY_WITHDRAWAL_LIMIT} {currency} would be exceeded "
                           f"(current: {daily_total}, requested: {amount})",
                    risk_score=0.9,
                    flags=["DAILY_LIMIT_EXCEEDED"],
                )

            # Rule 5: Rapid turnaround — withdrawal within N hours of same-amount deposit
            turnaround_window = now - timedelta(hours=RAPID_TURNAROUND_HOURS)
            recent_deposits = (
                session.query(WalletTransaction)
                .filter(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.transaction_type == "deposit",
                    WalletTransaction.created_at >= turnaround_window,
                )
                .all()
            )
            for dep in recent_deposits:
                if abs(Decimal(str(dep.amount)) - amount) < Decimal("0.01"):
                    flags.append("RAPID_TURNAROUND")
                    risk_score = max(risk_score, 0.7)
                    logger.warning(
                        "AML: rapid turnaround detected for user %s — deposit %.2f then withdrawal %.2f within %dh",
                        user_id, dep.amount, amount, RAPID_TURNAROUND_HOURS,
                    )
                    break

        return None  # no block from DB rules


# Module-level singleton (wired at startup with session_factory)
_aml_gate: Optional[AMLGate] = None


def get_aml_gate() -> AMLGate:
    global _aml_gate
    if _aml_gate is None:
        _aml_gate = AMLGate()  # no DB — fail-open
    return _aml_gate


def init_aml_gate(session_factory) -> AMLGate:
    global _aml_gate
    _aml_gate = AMLGate(session_factory=session_factory)
    return _aml_gate
