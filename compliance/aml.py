# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

UTC = timezone.utc
from decimal import Decimal

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
            decision = AMLDecision(
                allowed=False,
                reason=f"Withdrawal of {amount} {currency} exceeds single-transaction cap of {SINGLE_WITHDRAWAL_CAP}",
                risk_score=1.0,
                flags=["EXCEEDS_SINGLE_CAP"],
            )
            self._emit_block_event(user_id, amount, currency, decision)
            return decision

        # ── Rule 2: KYC required above threshold ──────────────────────────────
        if amount > KYC_THRESHOLD and kyc_status != "approved":
            decision = AMLDecision(
                allowed=False,
                reason=f"KYC approval required for withdrawals above {KYC_THRESHOLD} {currency}",
                risk_score=0.9,
                flags=["KYC_REQUIRED"],
            )
            self._emit_block_event(user_id, amount, currency, decision)
            return decision

        # ── DB-dependent rules ────────────────────────────────────────────────
        if self._sf:
            try:
                decision = self._check_db_rules(user_id, amount, currency, flags, risk_score)
                if decision:
                    return decision
            except Exception as exc:
                # Fail CLOSED on DB outage — a regulatory violation is worse
                # than a delayed withdrawal. The operator must restore DB
                # connectivity before withdrawals can proceed.
                logger.error(
                    "AML DB check failed for user %s: %s — BLOCKING withdrawal "
                    "(fail-closed; restore DB connectivity to resume withdrawals)",
                    user_id,
                    exc,
                )
                try:
                    import sentry_sdk

                    sentry_sdk.capture_exception(
                        exc,
                        extras={
                            "user_id": user_id[:8] + "…",
                            "amount": str(amount),
                            "aml_action": "fail_closed",
                        },
                    )
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
                return AMLDecision(
                    allowed=False,
                    reason=(
                        "Withdrawal temporarily unavailable: compliance database "
                        "is unreachable. Please try again later or contact support."
                    ),
                    risk_score=1.0,
                    flags=["DB_UNAVAILABLE"],
                )
        # No session factory configured — block all DB-dependent withdrawals
        # above the KYC threshold (rules 3-5 cannot be evaluated).
        elif amount > KYC_THRESHOLD:
            logger.error(
                "AML: no DB session factory configured — blocking withdrawal "
                "of %s for user %s (cannot evaluate velocity/daily rules). "
                "Call init_aml_gate(session_factory) at startup.",
                amount,
                user_id,
            )
            return AMLDecision(
                allowed=False,
                reason=(
                    "Withdrawal temporarily unavailable: compliance checks "
                    "require database connectivity. Contact support."
                ),
                risk_score=1.0,
                flags=["NO_DB_SESSION"],
            )

        # ── Approved ──────────────────────────────────────────────────────────
        if flags:
            risk_score = min(risk_score + 0.1 * len(flags), 0.8)
            logger.warning(
                "AML: withdrawal allowed with flags %s for user %s amount %s",
                flags,
                user_id,
                amount,
            )
        else:
            logger.info(
                "AML: withdrawal approved for user %s amount %s %s",
                user_id,
                amount,
                currency,
            )

        return AMLDecision(allowed=True, reason="Approved", risk_score=risk_score, flags=flags)

    def _emit_block_event(
        self,
        user_id: str,
        amount,
        currency: str,
        decision: AMLDecision,
    ) -> None:
        """
        Write an AML_BLOCK event to the transactional outbox.

        Called whenever a withdrawal is blocked so the event is guaranteed to
        reach the compliance event bus even if Redis is temporarily unavailable.
        """
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="AML_BLOCK",
                channel="hopefx:compliance",
                payload={
                    "type": "aml_block",
                    "user_id": user_id,
                    "amount": str(amount),
                    "currency": currency,
                    "reason": decision.reason,
                    "risk_score": decision.risk_score,
                    "flags": decision.flags,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning("AML outbox write failed (non-fatal): %s", exc)

    def _check_db_rules(
        self,
        user_id: str,
        amount: Decimal,
        currency: str,
        flags: list,
        risk_score: float,
    ) -> AMLDecision | None:
        """DB-backed rules. Returns AMLDecision to block, or None to continue."""
        from database.models import WalletTransaction

        now = datetime.now(UTC)
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
                        user_id,
                        dep.amount,
                        amount,
                        RAPID_TURNAROUND_HOURS,
                    )
                    break

        return None  # no block from DB rules


# Module-level singleton (wired at startup with session_factory)
_aml_gate: AMLGate | None = None


def get_aml_gate() -> AMLGate:
    """
    Return the module-level AMLGate singleton.

    ⚠️  If init_aml_gate() has not been called, the gate has no DB session
    factory and will BLOCK all withdrawals above the KYC threshold (fail-closed).
    Always call init_aml_gate(session_factory) during application startup.
    """
    global _aml_gate
    if _aml_gate is None:
        logger.error(
            "AMLGate singleton accessed before init_aml_gate() was called. "
            "Withdrawals above KYC threshold will be blocked until a DB "
            "session factory is provided. Call init_aml_gate(session_factory) "
            "during application startup."
        )
        _aml_gate = AMLGate()  # no DB — fail-closed for DB-dependent rules
    return _aml_gate


def init_aml_gate(session_factory) -> AMLGate:
    """Wire the AML gate with a DB session factory. Call once at startup."""
    global _aml_gate
    _aml_gate = AMLGate(session_factory=session_factory)
    logger.info("AMLGate initialised with DB session factory")
    return _aml_gate
