# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/pre_trade_gate.py

Pre-trade risk gate — the single mandatory checkpoint between signal generation
and order submission.

Design invariants (non-negotiable):
1. Any exception inside the gate BLOCKS the trade.  There is no "allow anyway"
   fallback.  If the risk manager is broken, we do not trade.
2. Every block is logged at WARNING with a structured reason code.
3. Sentry is notified on unexpected exceptions (not on normal blocks).
4. The gate is synchronous and re-entrant-safe (no shared mutable state).
5. All checks are additive — a trade must pass ALL checks to proceed.

Usage:
    from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

    gate = PreTradeGate(risk_manager)
    try:
        gate.check(order)          # raises TradeBlockedError if any check fails
    except TradeBlockedError as e:
        logger.warning("Order blocked: %s", e)
        return  # do NOT submit order
"""

from __future__ import annotations

import logging
import os
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from risk.manager import RiskManager

logger = logging.getLogger(__name__)

# Optional Sentry — non-fatal if absent
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False

# ── Risk-per-trade hard cap (env-configurable) ────────────────────────────────
# Maximum fraction of equity that can be lost on a single trade (full SL hit).
# Default: 1%.  Set MAX_RISK_PCT_PER_TRADE=0.005 for 0.5%, etc.
_MAX_RISK_PCT_PER_TRADE: float = float(os.getenv("MAX_RISK_PCT_PER_TRADE", "0.01"))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TradeBlockedError(Exception):
    """
    Raised by PreTradeGate.check() when a trade must not proceed.

    Attributes:
        reason_code: Machine-readable code (e.g. "KILL_SWITCH_ACTIVE").
        detail: Human-readable explanation.
        checks_failed: List of individual check names that failed.
    """

    def __init__(
        self,
        reason_code: str,
        detail: str,
        checks_failed: list[str] | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.detail = detail
        self.checks_failed = checks_failed or []
        super().__init__(f"[{reason_code}] {detail}")


class RiskManagerError(RuntimeError):
    """
    Raised when the risk manager itself throws an unexpected exception.
    The trade is blocked and this exception propagates to the caller.
    """


# ---------------------------------------------------------------------------
# Order representation (minimal — gate is broker-agnostic)
# ---------------------------------------------------------------------------


@dataclass
class GateOrder:
    """
    Minimal order representation consumed by the pre-trade gate.
    Callers convert their broker-specific order to this before calling check().
    """

    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: float
    price: float | None = None  # None = market order
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"GateOrder.side must be 'BUY' or 'SELL', got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError(f"GateOrder.quantity must be > 0, got {self.quantity}")


# ---------------------------------------------------------------------------
# Gate result (for audit logging — gate.check() still raises on failure)
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """Returned by gate.check() only when ALL checks pass."""

    order: GateOrder
    checks_passed: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cvar: float | None = None
    drawdown_pct: float | None = None


# ---------------------------------------------------------------------------
# Pre-trade gate
# ---------------------------------------------------------------------------


class PreTradeGate:
    """
    Mandatory pre-trade risk gate.

    All checks run in sequence.  The first failure raises TradeBlockedError
    immediately — subsequent checks are skipped (fail-fast).

    If the risk manager raises an unexpected exception during any check,
    RiskManagerError is raised (which also blocks the trade).
    """

    def __init__(self, risk_manager: RiskManager) -> None:
        self._rm = risk_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, order: GateOrder) -> GateResult:
        """
        Run all pre-trade checks against *order*.

        Returns:
            GateResult — only if ALL checks pass.

        Raises:
            TradeBlockedError — if any check fails (normal risk block).
            RiskManagerError — if the risk manager itself throws unexpectedly.
            ValueError — if order fields are invalid (caller bug).
        """
        checks_passed: list[str] = []
        cvar: float | None = None
        drawdown_pct: float | None = None

        # ── 1. Kill-switch ────────────────────────────────────────────────────
        self._run_check(
            name="kill_switch",
            fn=self._check_kill_switch,
            checks_passed=checks_passed,
        )

        # ── 2. Trading-halted flag ────────────────────────────────────────────
        self._run_check(
            name="trading_halted",
            fn=self._check_trading_halted,
            checks_passed=checks_passed,
        )

        # ── 3. Daily loss limit ───────────────────────────────────────────────
        self._run_check(
            name="daily_loss_limit",
            fn=self._check_daily_loss,
            checks_passed=checks_passed,
        )

        # ── 4. Max drawdown ───────────────────────────────────────────────────
        drawdown_pct = self._run_check_with_value(
            name="max_drawdown",
            fn=self._check_drawdown,
            checks_passed=checks_passed,
        )

        # ── 5. CVaR pre-trade gate ────────────────────────────────────────────
        cvar = self._run_check_with_value(
            name="cvar_pre_trade",
            fn=self._check_cvar,
            checks_passed=checks_passed,
        )

        # ── 6. Position size ──────────────────────────────────────────────────
        self._run_check(
            name="position_size",
            fn=lambda: self._check_position_size(order),
            checks_passed=checks_passed,
        )

        # ── 7. Max open positions ─────────────────────────────────────────────
        self._run_check(
            name="max_open_positions",
            fn=self._check_open_positions,
            checks_passed=checks_passed,
        )

        # ── 8. Validate trade (symbol/side/size) ──────────────────────────────
        self._run_check(
            name="validate_trade",
            fn=lambda: self._check_validate_trade(order),
            checks_passed=checks_passed,
        )

        # ── 9. Hard <1% risk-per-trade cap ────────────────────────────────────
        # Blocks the order if the notional risk (entry → SL) exceeds
        # _MAX_RISK_PCT_PER_TRADE of account equity.  This is a second-layer
        # check — TradeExecutor._clamp_size_to_risk_cap() should have already
        # reduced the size, but the gate enforces the hard limit independently.
        self._run_check(
            name="risk_per_trade_cap",
            fn=lambda: self._check_risk_per_trade(order),
            checks_passed=checks_passed,
        )

        # ── 10. Loss-streak circuit breaker ───────────────────────────────────
        # Blocks new entries when the executor has flagged a streak halt.
        # The executor sets risk_manager._streak_halted=True; the gate reads it.
        self._run_check(
            name="loss_streak",
            fn=self._check_loss_streak,
            checks_passed=checks_passed,
        )

        logger.info(
            "PRE-TRADE GATE PASSED | symbol=%s side=%s qty=%.4f strategy=%s checks=%s cvar=%s dd=%.4f",
            order.symbol,
            order.side,
            order.quantity,
            order.strategy_id,
            checks_passed,
            f"{cvar:.4f}" if cvar is not None else "n/a",
            drawdown_pct or 0.0,
        )

        return GateResult(
            order=order,
            checks_passed=checks_passed,
            cvar=cvar,
            drawdown_pct=drawdown_pct,
        )

    # ------------------------------------------------------------------
    # Internal check runners
    # ------------------------------------------------------------------

    def _run_check(
        self,
        name: str,
        fn,
        checks_passed: list[str],
    ) -> None:
        """
        Execute a check function.  On TradeBlockedError, re-raise.
        On any other exception, wrap in RiskManagerError and raise
        (which also blocks the trade — no fallback).
        """
        try:
            fn()
            checks_passed.append(name)
        except TradeBlockedError:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            msg = f"Risk manager raised unexpected exception in check '{name}': {type(exc).__name__}: {exc}"
            logger.error("%s\n%s", msg, tb)
            if _SENTRY:
                try:
                    sentry_sdk.capture_exception(exc)
                except Exception as _sentry_exc:
                    logger.debug("Sentry capture failed (non-fatal): %s", _sentry_exc)
            # BLOCK the trade — a broken risk check is not a pass
            raise RiskManagerError(msg) from exc

    def _run_check_with_value(
        self,
        name: str,
        fn,
        checks_passed: list[str],
    ) -> float | None:
        """Like _run_check but fn() returns an Optional[float] metric."""
        try:
            value = fn()
            checks_passed.append(name)
            return value
        except TradeBlockedError:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            msg = f"Risk manager raised unexpected exception in check '{name}': {type(exc).__name__}: {exc}"
            logger.error("%s\n%s", msg, tb)
            if _SENTRY:
                try:
                    sentry_sdk.capture_exception(exc)
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
            raise RiskManagerError(msg) from exc

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_kill_switch(self) -> None:
        """Block if the system-wide kill switch is active."""
        # KillSwitch may be wired via the risk manager or standalone
        ks = getattr(self._rm, "_kill_switch", None)
        if ks is not None and ks.is_active():
            reason = getattr(ks, "_reason", "kill switch active")
            logger.warning("PRE-TRADE BLOCKED [KILL_SWITCH_ACTIVE] reason=%s", reason)
            raise TradeBlockedError(
                reason_code="KILL_SWITCH_ACTIVE",
                detail=f"System kill switch is active: {reason}",
                checks_failed=["kill_switch"],
            )

    def _check_trading_halted(self) -> None:
        """Block if the risk manager has halted trading."""
        halted = getattr(self._rm, "_trading_halted", False)
        if halted:
            halt_reason = getattr(self._rm, "_halt_reason", "unknown")
            halt_until = getattr(self._rm, "_halt_until", None)
            detail = f"Trading halted: {halt_reason}"
            if halt_until:
                detail += f" (until {halt_until.isoformat()})"
            logger.warning("PRE-TRADE BLOCKED [TRADING_HALTED] %s", detail)
            raise TradeBlockedError(
                reason_code="TRADING_HALTED",
                detail=detail,
                checks_failed=["trading_halted"],
            )

    def _check_daily_loss(self) -> None:
        """Block if daily loss limit is breached."""
        rm = self._rm
        daily_pnl = getattr(rm, "daily_pnl", 0.0)
        daily_start = getattr(rm, "daily_starting_equity", 0.0)
        config = getattr(rm, "config", None)
        if config is None or daily_start <= 0:
            return  # cannot check — pass (but log)

        daily_loss_pct = abs(daily_pnl) / daily_start if daily_pnl < 0 else 0.0
        limit = getattr(config, "daily_loss_limit_pct", 0.05)

        if daily_loss_pct >= limit:
            detail = f"Daily loss {daily_loss_pct:.2%} >= limit {limit:.2%} (pnl={daily_pnl:.2f})"
            logger.warning("PRE-TRADE BLOCKED [DAILY_LOSS_LIMIT] %s", detail)
            raise TradeBlockedError(
                reason_code="DAILY_LOSS_LIMIT",
                detail=detail,
                checks_failed=["daily_loss_limit"],
            )

    def _check_drawdown(self) -> float:
        """Block if max drawdown is breached. Returns current drawdown."""
        rm = self._rm
        current_dd = getattr(rm, "current_drawdown", 0.0)
        config = getattr(rm, "config", None)
        limit = getattr(config, "max_drawdown_pct", 0.10) if config else 0.10

        if current_dd >= limit:
            detail = f"Drawdown {current_dd:.2%} >= limit {limit:.2%}"
            logger.warning("PRE-TRADE BLOCKED [MAX_DRAWDOWN] %s", detail)
            raise TradeBlockedError(
                reason_code="MAX_DRAWDOWN",
                detail=detail,
                checks_failed=["max_drawdown"],
            )
        return current_dd

    def _check_cvar(self) -> float | None:
        """
        Block if CVaR pre-trade gate fails.
        Returns current CVaR value (or None if insufficient history).
        """
        rm = self._rm
        if not hasattr(rm, "check_cvar_pre_trade"):
            return None  # risk manager doesn't implement CVaR — pass

        allowed, reason = rm.check_cvar_pre_trade()
        if not allowed:
            logger.warning("PRE-TRADE BLOCKED [CVAR_LIMIT] %s", reason)
            raise TradeBlockedError(
                reason_code="CVAR_LIMIT",
                detail=reason,
                checks_failed=["cvar_pre_trade"],
            )

        # Extract CVaR value for audit log
        if hasattr(rm, "_compute_cvar") and len(getattr(rm, "_returns_history", [])) >= 10:
            try:
                return rm._compute_cvar()
            except Exception:  # nosec B110 — optional CVaR computation
                return None
        return None

    def _check_position_size(self, order: GateOrder) -> None:
        """Block if order quantity exceeds position size limits."""
        rm = self._rm
        config = getattr(rm, "config", None)
        if config is None:
            return

        def _rf(attr: str) -> float:
            val = getattr(rm, attr, None)
            if isinstance(val, int | float):
                return float(val)
            return 0.0

        balance = _rf("current_balance") or _rf("initial_balance")
        if balance <= 0:
            return  # cannot check — pass

        # Notional value check
        price = order.price or 0.0
        if price > 0:
            notional = order.quantity * price
            max_notional = balance * getattr(config, "max_position_size_pct", 0.02)
            if notional > max_notional:
                detail = (
                    f"Notional {notional:.2f} > max allowed {max_notional:.2f} "
                    f"({getattr(config, 'max_position_size_pct', 0.02):.2%} of balance {balance:.2f})"
                )
                logger.warning("PRE-TRADE BLOCKED [POSITION_SIZE] %s", detail)
                raise TradeBlockedError(
                    reason_code="POSITION_SIZE",
                    detail=detail,
                    checks_failed=["position_size"],
                )

    def _check_open_positions(self) -> None:
        """Block if max open positions limit is reached."""
        rm = self._rm
        config = getattr(rm, "config", None)
        open_positions = getattr(rm, "open_positions", [])
        max_pos = getattr(config, "max_open_positions", 5) if config else 5

        if len(open_positions) >= max_pos:
            detail = f"Open positions {len(open_positions)} >= limit {max_pos}"
            logger.warning("PRE-TRADE BLOCKED [MAX_OPEN_POSITIONS] %s", detail)
            raise TradeBlockedError(
                reason_code="MAX_OPEN_POSITIONS",
                detail=detail,
                checks_failed=["max_open_positions"],
            )

    def _check_validate_trade(self, order: GateOrder) -> None:
        """Delegate to risk manager's validate_trade() if available."""
        rm = self._rm
        if not hasattr(rm, "validate_trade"):
            return

        ok, reason = rm.validate_trade(
            symbol=order.symbol,
            size=order.quantity,
            side=order.side,
        )
        if not ok:
            logger.warning("PRE-TRADE BLOCKED [VALIDATE_TRADE] %s", reason)
            raise TradeBlockedError(
                reason_code="VALIDATE_TRADE",
                detail=reason,
                checks_failed=["validate_trade"],
            )

    def _check_risk_per_trade(self, order: GateOrder) -> None:
        """
        Block if the trade's notional risk exceeds _MAX_RISK_PCT_PER_TRADE.

        Risk is defined as: quantity × |entry_price - stop_loss|.
        When stop_loss is absent, risk is approximated as quantity × entry_price
        (full notional), which is conservative.

        This is a hard gate — the trade is blocked, not resized.  The caller
        (TradeExecutor) is responsible for sizing down before reaching the gate.
        """
        rm = self._rm

        def _real_float(attr: str) -> float:
            """Return float only if the attribute is a real numeric value."""
            val = getattr(rm, attr, None)
            if val is None:
                return 0.0
            if isinstance(val, int | float):
                return float(val)
            return 0.0

        balance = _real_float("current_equity") or _real_float("current_balance") or _real_float("initial_balance")

        if not balance or balance <= 0:
            return  # cannot check — pass (balance unavailable)

        max_loss_dollars = balance * _MAX_RISK_PCT_PER_TRADE

        entry_price = order.price or 0.0
        stop_loss = order.stop_loss

        if entry_price > 0 and stop_loss is not None:
            risk_per_unit = abs(entry_price - stop_loss)
            notional_risk = order.quantity * risk_per_unit
        elif entry_price > 0:
            # No SL — treat full notional as risk (conservative)
            notional_risk = order.quantity * entry_price
        else:
            return  # no price info — pass (cannot compute)

        if notional_risk > max_loss_dollars:
            detail = (
                f"Notional risk ${notional_risk:.2f} exceeds "
                f"{_MAX_RISK_PCT_PER_TRADE:.1%} cap (${max_loss_dollars:.2f}) "
                f"on equity ${balance:.2f}. "
                f"Reduce size or widen stop."
            )
            logger.warning("PRE-TRADE BLOCKED [RISK_PER_TRADE_CAP] %s", detail)
            raise TradeBlockedError(
                reason_code="RISK_PER_TRADE_CAP",
                detail=detail,
                checks_failed=["risk_per_trade_cap"],
            )

    def _check_loss_streak(self) -> None:
        """
        Block new entries when a loss-streak cooldown is active.

        TradeExecutor sets risk_manager._streak_halted = True when
        STREAK_HALT_LOSSES consecutive losses are detected.  This gate
        reads that flag so the block is enforced even if orders arrive
        through a different code path (e.g. API direct order).
        """
        rm = self._rm
        streak_halted = getattr(rm, "_streak_halted", False)
        if not isinstance(streak_halted, bool):
            streak_halted = False
        if streak_halted:
            streak_losses = getattr(rm, "_streak_loss_count", "?")
            detail = (
                f"Loss-streak circuit breaker active "
                f"({streak_losses} consecutive losses). "
                "Wait for cooldown to expire before placing new entries."
            )
            logger.warning("PRE-TRADE BLOCKED [LOSS_STREAK] %s", detail)
            raise TradeBlockedError(
                reason_code="LOSS_STREAK",
                detail=detail,
                checks_failed=["loss_streak"],
            )
