# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/trade_executor.py
===========================
Smart order router with mandatory pre-trade risk gate.

Risk controls enforced on every order
--------------------------------------
1. Pre-trade gate (8 checks)  — kill switch, halt, daily loss, drawdown,
   CVaR, position size, max open positions, validate_trade.
2. Hard <1% risk-per-trade cap — position notional capped so that a full
   stop-loss hit never exceeds MAX_RISK_PCT_PER_TRADE of account equity.
   Default: 0.01 (1%).  Override via env var MAX_RISK_PCT_PER_TRADE.
3. Drawdown circuit breaker   — if current drawdown >= DRAWDOWN_HALT_PCT
   (default 5%) trading is halted immediately and the risk manager's
   _trading_halted flag is set.
4. Loss-streak detection      — after STREAK_HALT_LOSSES (default 3)
   consecutive losses the executor pauses for STREAK_COOLDOWN_MINUTES
   (default 30) before allowing new entries.

Signal-filter wiring
---------------------
- record_outcome() is called on every position close (both via
  _execute_close and via _notify_inference_engine_fill) so the EV gate
  accumulates real trade data.

Online-learning wiring
-----------------------
- InferenceEngine.update_online() is called on every confirmed fill with
  a label derived from realised P&L.
"""

import asyncio
import logging
import os
import time
from collections.abc import Callable
from typing import Any, cast
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum

from infrastructure.metrics import Counter as MetricCounter
from infrastructure.metrics import get_metrics_registry

logger = logging.getLogger(__name__)

# ── Risk constants (env-configurable) ────────────────────────────────────────
# Hard cap: maximum fraction of equity risked on a single trade.
# A stop-loss hit at this distance from entry must not exceed this loss.
MAX_RISK_PCT_PER_TRADE: float = float(os.getenv("MAX_RISK_PCT_PER_TRADE", "0.01"))

# Drawdown circuit breaker: halt trading when drawdown reaches this level.
DRAWDOWN_HALT_PCT: float = float(os.getenv("DRAWDOWN_HALT_PCT", "0.05"))

# Loss-streak circuit breaker: halt after N consecutive losses.
STREAK_HALT_LOSSES: int = int(os.getenv("STREAK_HALT_LOSSES", "3"))

# Cooldown in minutes after a streak halt before new entries are allowed.
STREAK_COOLDOWN_MINUTES: float = float(os.getenv("STREAK_COOLDOWN_MINUTES", "30"))


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class ExecutionResult:
    """Order execution result."""

    success: bool
    order_id: str | None
    filled_quantity: float
    average_price: float
    commission: float
    status: OrderStatus
    message: str
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class TradeExecutor:
    """
    Smart trade execution with mandatory pre-trade risk gate.

    Risk controls applied on every order:
    - Pre-trade gate (8 checks)
    - Hard <1% risk-per-trade cap (MAX_RISK_PCT_PER_TRADE)
    - Drawdown circuit breaker (DRAWDOWN_HALT_PCT)
    - Loss-streak detection (STREAK_HALT_LOSSES / STREAK_COOLDOWN_MINUTES)
    """

    def __init__(self, broker: Any, risk_manager: Any, position_tracker: Any) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        self.position_tracker = position_tracker
        self.metrics = get_metrics_registry()

        self._pending_orders: dict[str, dict[str, Any]] = {}
        self._execution_callbacks: list[Callable[..., Any]] = []
        self._lock = asyncio.Lock()

        # ── Streak tracking ───────────────────────────────────────────────────
        self._consecutive_losses: int = 0
        self._streak_halted_until: float | None = None  # monotonic time

    async def execute_signal(self, signal: dict[str, Any]) -> ExecutionResult:
        """Execute a trading signal with full validation and risk controls."""
        start_time = asyncio.get_running_loop().time()

        required_fields = ["symbol", "action", "size"]
        missing = [f for f in required_fields if f not in signal]
        if missing:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Missing required fields: {missing}",
                latency_ms=0,
            )

        symbol = signal["symbol"]
        action = signal["action"]

        if action not in ("buy", "sell", "close"):
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Invalid action: {action}",
                latency_ms=0,
            )

        try:
            if action == "close":
                result = await self._execute_close(signal)
            else:
                result = await self._execute_open(signal)

            latency_ms = (asyncio.get_running_loop().time() - start_time) * 1000
            result.latency_ms = latency_ms
            self.metrics.record_order_latency(latency_ms)

            if result.success:
                _c = self.metrics.get_collector("orders_filled_total")
                if _c is not None:
                    cast(MetricCounter, _c).inc(1, {"symbol": symbol, "type": "market"})
            else:
                _c2 = self.metrics.get_collector("orders_rejected_total")
                if _c2 is not None:
                    cast(MetricCounter, _c2).inc(1, {"symbol": symbol, "reason": result.status.value})

            await self._notify_callbacks(result, signal)
            return result

        except (TimeoutError, RuntimeError, ConnectionError, ValueError) as exc:
            latency_ms = (asyncio.get_running_loop().time() - start_time) * 1000
            logger.exception("Execution error for %s", symbol)
            self.metrics.record_error("trade_executor", type(exc).__name__)
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=str(exc),
                latency_ms=latency_ms,
            )

    async def _execute_open(self, signal: dict[str, Any]) -> ExecutionResult:
        """
        Execute an opening order.

        Checks applied in order:
        1. Drawdown circuit breaker
        2. Loss-streak circuit breaker
        3. <1% risk-per-trade cap (size clamping)
        4. Mandatory pre-trade gate (8 checks)
        5. Broker order placement
        """
        symbol = signal["symbol"]
        side = signal["action"]
        size = float(signal["size"])

        # ── 1. Drawdown circuit breaker ───────────────────────────────────────
        blocked, dd_msg = self._check_drawdown_circuit_breaker()
        if blocked:
            logger.warning(
                "ORDER BLOCKED [DRAWDOWN_CIRCUIT_BREAKER] symbol=%s %s",
                symbol,
                dd_msg,
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message=f"[DRAWDOWN_CIRCUIT_BREAKER] {dd_msg}",
                latency_ms=0,
            )

        # ── 2. Loss-streak circuit breaker ────────────────────────────────────
        blocked, streak_msg = self._check_streak_circuit_breaker()
        if blocked:
            logger.warning(
                "ORDER BLOCKED [STREAK_CIRCUIT_BREAKER] symbol=%s %s",
                symbol,
                streak_msg,
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message=f"[STREAK_CIRCUIT_BREAKER] {streak_msg}",
                latency_ms=0,
            )

        # ── 3. Hard <1% risk-per-trade cap ────────────────────────────────────
        size = self._clamp_size_to_risk_cap(signal, size)
        if size <= 0:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message="[RISK_CAP] Computed position size is zero after risk capping",
                latency_ms=0,
            )
        signal = {**signal, "size": size}  # propagate clamped size

        # ── 4. Mandatory pre-trade gate ───────────────────────────────────────
        from risk.pre_trade_gate import (
            GateOrder,
            PreTradeGate,
            RiskManagerError,
            TradeBlockedError,
        )

        gate = PreTradeGate(self.risk_manager)
        gate_order = GateOrder(
            symbol=symbol,
            side=side.upper(),
            quantity=size,
            price=signal.get("price"),
            stop_loss=signal.get("stop_loss"),
            take_profit=signal.get("take_profit"),
            strategy_id=signal.get("strategy_id", "unknown"),
        )
        try:
            gate.check(gate_order)
        except TradeBlockedError as exc:
            logger.warning(
                "ORDER BLOCKED by pre-trade gate | symbol=%s side=%s qty=%.4f reason_code=%s detail=%s",
                symbol,
                side,
                size,
                exc.reason_code,
                exc.detail,
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message=f"[{exc.reason_code}] {exc.detail}",
                latency_ms=0,
            )
        except RiskManagerError as exc:
            logger.critical(
                "RISK MANAGER ERROR — order blocked as safety measure | symbol=%s side=%s qty=%.4f error=%s",
                symbol,
                side,
                size,
                exc,
            )
            try:
                import sentry_sdk

                sentry_sdk.capture_exception(exc)
            except (RuntimeError, AttributeError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message="[RISK_MANAGER_ERROR] Order blocked — check server logs",
                latency_ms=0,
            )

        # ── 5. Place order ────────────────────────────────────────────────────
        order = await self.broker.place_market_order(
            symbol=symbol,
            side=side,
            quantity=size,
        )

        if order.status.value in ("filled", "partial"):
            from execution.position_tracker import Position

            position = Position(
                id=order.id,
                symbol=symbol,
                side="long" if side == "buy" else "short",
                quantity=order.filled_quantity,
                entry_price=order.average_fill_price,
                current_price=order.average_fill_price,
                commission=order.commission,
                stop_loss=signal.get("stop_loss"),
                take_profit=signal.get("take_profit"),
            )
            await self.position_tracker.add_position(position)

        return ExecutionResult(
            success=order.status.value in ("filled", "partial"),
            order_id=order.id,
            filled_quantity=order.filled_quantity,
            average_price=order.average_fill_price,
            commission=order.commission,
            status=OrderStatus(order.status.value),
            message=f"Order {order.status.value}",
        )

    async def _execute_close(self, signal: dict[str, Any]) -> ExecutionResult:
        """
        Execute a closing order.

        On success:
        - Updates risk manager equity
        - Records outcome in SignalFilter (EV gate)
        - Updates streak counter (win resets, loss increments)
        - Checks drawdown circuit breaker post-close
        """
        position_id = signal.get("position_id")
        if not position_id:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message="No position_id specified for close",
                latency_ms=0,
            )

        position = self.position_tracker.get_position(position_id)
        if not position:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Position not found: {position_id}",
                latency_ms=0,
            )

        success = await self.broker.close_position(position_id)

        if success:
            closed_position = await self.position_tracker.close_position(
                position_id,
                position.current_price,
                commission=position.commission,
            )

            if closed_position:
                realized_pnl = closed_position.realized_pnl

                # Update risk manager equity
                self.risk_manager.update_equity(self.risk_manager.daily_starting_equity + realized_pnl)

                # ── Streak tracking (executor + risk manager) ────────────────
                self._update_streak(realized_pnl)
                # Keep risk manager streak state in sync so PreTradeGate
                # can enforce the halt even via alternative order paths.
                try:
                    if hasattr(self.risk_manager, "record_trade_outcome"):
                        self.risk_manager.record_trade_outcome(
                            realized_pnl=realized_pnl,
                            symbol=getattr(closed_position, "symbol", position_id),
                        )
                except (RuntimeError, AttributeError, TypeError) as _rm_exc:
                    logger.debug(
                        "RiskManager.record_trade_outcome failed (non-fatal): %s",
                        _rm_exc,
                    )

                # ── Post-close drawdown check ─────────────────────────────────
                self._trigger_drawdown_halt_if_needed()

                # ── SignalFilter EV update ────────────────────────────────────
                try:
                    from ml.signal_filter import get_signal_filter

                    _entry_px = getattr(closed_position, "entry_price", None) or position.current_price
                    _pnl_pct = realized_pnl / _entry_px if _entry_px > 0 else 0.0
                    _side = getattr(closed_position, "side", "buy")
                    _direction = 1 if str(_side).lower() in ("buy", "long") else -1
                    _conf = float(getattr(closed_position, "signal_confidence", 0.6))
                    _sym = getattr(closed_position, "symbol", position_id)

                    get_signal_filter().record_outcome(
                        symbol=_sym,
                        pnl_pct=_pnl_pct,
                        direction=_direction,
                        confidence=_conf,
                    )
                    logger.debug(
                        "SignalFilter close outcome: symbol=%s pnl_pct=%.5f dir=%d conf=%.3f",
                        _sym,
                        _pnl_pct,
                        _direction,
                        _conf,
                    )
                except (ImportError, RuntimeError, AttributeError) as _sf_exc:
                    logger.debug("SignalFilter close record failed (non-fatal): %s", _sf_exc)

        return ExecutionResult(
            success=success,
            order_id=position_id,
            filled_quantity=position.quantity if success else 0,
            average_price=position.current_price if success else 0,
            commission=position.commission,
            status=OrderStatus.FILLED if success else OrderStatus.ERROR,
            message="Position closed" if success else "Close failed",
        )

    # ── Risk circuit breakers ─────────────────────────────────────────────────

    def _check_drawdown_circuit_breaker(self) -> tuple[bool, str]:
        """
        Return (blocked: bool, reason: str) based on current drawdown.

        Also respects the risk manager's _trading_halted flag so a previously
        triggered halt is enforced even after a restart.
        """
        if getattr(self.risk_manager, "_trading_halted", False):
            halt_reason = getattr(self.risk_manager, "_halt_reason", "trading halted")
            return True, f"Risk manager halt active: {halt_reason}"

        current_dd = getattr(self.risk_manager, "current_drawdown", 0.0)
        if current_dd >= DRAWDOWN_HALT_PCT:
            msg = f"Drawdown {current_dd:.2%} >= circuit breaker threshold {DRAWDOWN_HALT_PCT:.2%}. Trading halted."
            self._trigger_drawdown_halt_if_needed()
            return True, msg

        return False, ""

    def _trigger_drawdown_halt_if_needed(self) -> None:
        """
        Set _trading_halted on the risk manager when drawdown breaches
        DRAWDOWN_HALT_PCT.  Idempotent — safe to call after every close.
        """
        current_dd = getattr(self.risk_manager, "current_drawdown", 0.0)
        if current_dd >= DRAWDOWN_HALT_PCT and not getattr(self.risk_manager, "_trading_halted", False):
            reason = f"Drawdown circuit breaker: {current_dd:.2%} >= {DRAWDOWN_HALT_PCT:.2%}"
            logger.warning(
                "DRAWDOWN CIRCUIT BREAKER TRIGGERED: %s — halting trading",
                reason,
            )
            try:
                self.risk_manager._trading_halted = True
                self.risk_manager._halt_reason = reason
            except (TimeoutError, RuntimeError, ConnectionError, ValueError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    def _check_streak_circuit_breaker(self) -> tuple[bool, str]:
        """
        Return (blocked: bool, reason: str) if a loss-streak cooldown is active.

        The cooldown expires automatically after STREAK_COOLDOWN_MINUTES.
        """
        if self._streak_halted_until is None:
            return False, ""

        now = time.monotonic()
        if now < self._streak_halted_until:
            remaining = self._streak_halted_until - now
            msg = (
                f"Loss streak of {STREAK_HALT_LOSSES} consecutive losses. "
                f"Cooldown active — {remaining / 60:.1f} min remaining."
            )
            return True, msg

        # Cooldown expired — reset
        logger.info(
            "Streak cooldown expired after %.0f min — resuming trading",
            STREAK_COOLDOWN_MINUTES,
        )
        self._streak_halted_until = None
        self._consecutive_losses = 0
        return False, ""

    def _update_streak(self, realized_pnl: float) -> None:
        """
        Update consecutive-loss counter and trigger cooldown when threshold hit.

        A winning trade resets the counter.  A losing trade increments it.
        When STREAK_HALT_LOSSES is reached, a cooldown timer is set.
        """
        if realized_pnl > 0:
            if self._consecutive_losses > 0:
                logger.debug(
                    "Streak reset: winning trade after %d consecutive losses",
                    self._consecutive_losses,
                )
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            logger.debug(
                "Consecutive losses: %d / %d",
                self._consecutive_losses,
                STREAK_HALT_LOSSES,
            )
            if self._consecutive_losses >= STREAK_HALT_LOSSES:
                cooldown_secs = STREAK_COOLDOWN_MINUTES * 60
                self._streak_halted_until = time.monotonic() + cooldown_secs
                logger.warning(
                    "STREAK CIRCUIT BREAKER: %d consecutive losses — halting new entries for %.0f min",
                    self._consecutive_losses,
                    STREAK_COOLDOWN_MINUTES,
                )

    def _clamp_size_to_risk_cap(self, signal: dict[str, Any], size: float) -> float:
        """
        Clamp position size so that a full stop-loss hit never exceeds
        MAX_RISK_PCT_PER_TRADE of current account equity.

        Formula (when SL is provided):
            max_loss_dollars = equity × MAX_RISK_PCT_PER_TRADE
            max_size = max_loss_dollars / (entry_price × sl_distance_pct)

        Falls back to notional cap when stop_loss is absent.
        """
        try:
            equity = (
                getattr(self.risk_manager, "current_equity", None)
                or getattr(self.risk_manager, "current_balance", None)
                or getattr(self.risk_manager, "initial_balance", 0.0)
            )
            if not equity or equity <= 0:
                return size

            entry_price = signal.get("price") or signal.get("entry_price")
            stop_loss = signal.get("stop_loss")

            if entry_price and stop_loss and entry_price > 0:
                sl_distance = abs(entry_price - stop_loss)
                sl_pct = sl_distance / entry_price
                if sl_pct > 0:
                    max_loss = equity * MAX_RISK_PCT_PER_TRADE
                    max_size = max_loss / (entry_price * sl_pct)
                    if max_size < size:
                        logger.info(
                            "Risk cap applied: size %.4f → %.4f (equity=%.2f, sl_pct=%.3f%%, max_risk=%.1f%%)",
                            size,
                            max_size,
                            equity,
                            sl_pct * 100,
                            MAX_RISK_PCT_PER_TRADE * 100,
                        )
                        return float(round(float(max_size), 8))
            # No SL — cap by notional: size × price <= equity × cap
            elif entry_price and entry_price > 0:
                max_notional = equity * MAX_RISK_PCT_PER_TRADE
                max_size_notional = max_notional / entry_price
                if max_size_notional < size:
                    logger.info(
                        "Risk cap (notional fallback): size %.4f → %.4f",
                        size,
                        max_size_notional,
                    )
                    return float(round(float(max_size_notional), 8))
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("Risk cap calculation failed (non-fatal): %s", exc)

        return size

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def register_callback(self, callback: Callable[[ExecutionResult, dict[str, Any]], None]) -> None:
        """Register an execution callback."""
        self._execution_callbacks.append(callback)

    async def _notify_callbacks(self, result: ExecutionResult, signal: dict[str, Any]) -> None:
        """Notify all registered callbacks and the InferenceEngine fill hook."""
        for callback in self._execution_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(result, signal)
                else:
                    callback(result, signal)
            except (RuntimeError, TypeError) as exc:
                logger.error("Callback error: %s", exc)

        if result.success and result.status in (
            OrderStatus.FILLED,
            OrderStatus.PARTIAL,
        ):
            await self._notify_inference_engine_fill(result, signal)

    async def _notify_inference_engine_fill(self, result: ExecutionResult, signal: dict[str, Any]) -> None:
        """
        Notify InferenceEngine of a confirmed fill for online learning.

        Only closed positions with a known P&L are used to avoid label
        leakage on open trades.
        """
        try:
            from ml.inference_engine import get_inference_engine

            engine = get_inference_engine()

            pnl: float | None = signal.get("realized_pnl")
            if pnl is None:
                position_id = signal.get("position_id") or result.order_id
                if position_id and hasattr(self.position_tracker, "get_position"):
                    pos = self.position_tracker.get_position(position_id)
                    if pos is not None:
                        pnl = getattr(pos, "realized_pnl", None)

            if pnl is None:
                return

            label = 1 if pnl > 0 else 0
            _confidence = float(signal.get("confidence", 0.0))
            _action = signal.get("action", "buy")

            import pandas as _pd

            features = _pd.DataFrame(
                [
                    {
                        "entry_price": result.average_price,
                        "filled_qty": result.filled_quantity,
                        "commission": result.commission,
                        "latency_ms": result.latency_ms,
                        "confidence": _confidence,
                        "direction_long": 1 if _action == "buy" else 0,
                    }
                ]
            )
            engine.update_online(features, label)
            logger.debug(
                "InferenceEngine fill notify: symbol=%s pnl=%.4f label=%d",
                signal.get("symbol", "?"),
                pnl,
                label,
            )

            # ── SignalFilter EV update (fill path) ────────────────────────────
            try:
                from ml.signal_filter import get_signal_filter

                _sym = signal.get("symbol", "UNKNOWN")
                _entry = result.average_price or 1.0
                _pnl_pct = pnl / _entry if _entry > 0 else 0.0
                _direction = 1 if _action == "buy" else -1
                get_signal_filter().record_outcome(
                    symbol=_sym,
                    pnl_pct=_pnl_pct,
                    direction=_direction,
                    confidence=_confidence,
                )
                logger.debug(
                    "SignalFilter outcome (fill): symbol=%s pnl_pct=%.5f dir=%d conf=%.3f",
                    _sym,
                    _pnl_pct,
                    _direction,
                    _confidence,
                )
            except (ImportError, RuntimeError, AttributeError) as _sf_exc:
                logger.debug("SignalFilter record_outcome failed (non-fatal): %s", _sf_exc)

        except (ImportError, RuntimeError, AttributeError, TypeError) as exc:
            logger.debug("InferenceEngine fill notify failed (non-fatal): %s", exc)

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def cancel_all_pending(self) -> list[str]:
        """Cancel all pending orders."""
        cancelled = []
        async with self._lock:
            for order_id in list(self._pending_orders):
                try:
                    success = await self.broker.cancel_order(order_id)
                    if success:
                        cancelled.append(order_id)
                        del self._pending_orders[order_id]
                except (TimeoutError, RuntimeError, ConnectionError) as exc:
                    logger.error("Error cancelling order %s: %s", order_id, exc)
        return cancelled

    def get_risk_status(self) -> dict[str, Any]:
        """
        Return current risk circuit-breaker state for monitoring.

        Exposed via health endpoints and dashboard widgets.
        """
        streak_cooldown_remaining: float | None = None
        if self._streak_halted_until is not None:
            remaining = self._streak_halted_until - time.monotonic()
            streak_cooldown_remaining = max(0.0, round(remaining / 60, 1))

        return {
            "consecutive_losses": self._consecutive_losses,
            "streak_halt_threshold": STREAK_HALT_LOSSES,
            "streak_halted": (self._streak_halted_until is not None and time.monotonic() < self._streak_halted_until),
            "streak_cooldown_remaining_min": streak_cooldown_remaining,
            "drawdown_halt_pct": DRAWDOWN_HALT_PCT,
            "max_risk_pct_per_trade": MAX_RISK_PCT_PER_TRADE,
            "trading_halted": getattr(self.risk_manager, "_trading_halted", False),
            "halt_reason": getattr(self.risk_manager, "_halt_reason", None),
        }
