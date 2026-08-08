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
import math
import os
import time
import uuid
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

    def __init__(
        self,
        broker: Any,
        risk_manager: Any,
        position_tracker: Any,
        state_store: Any = None,
    ) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        self.position_tracker = position_tracker
        # Write-ahead journal for order intents (S7-02). Optional: paper and
        # dev runs have no Redis, and trading must not stop for want of a
        # crash-recovery record — but the gap is worth saying out loud, because
        # without it a fill that lands during a crash is invisible forever.
        self.state_store = state_store
        # Resolved lazily on first use when not injected — see _resolve_store().
        self._store_lookup_done = state_store is not None
        if state_store is None:
            logger.info(
                "TradeExecutor: no state_store injected — will resolve the "
                "order-intent journal from the PositionManager on first order."
            )
        self.metrics = get_metrics_registry()

        self._pending_orders: dict[str, dict[str, Any]] = {}
        self._execution_callbacks: list[Callable[..., Any]] = []
        self._lock = asyncio.Lock()
        # position_ids whose close is currently in-flight — idempotency guard
        # against concurrent/duplicate close_position() calls (double close).
        self._closing_positions: set[str] = set()

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
            except (ImportError, RuntimeError, AttributeError) as _exc:
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

        # ── 4b. Order authorization (feature-flagged, fail-safe) ──────────────
        # The order has passed the mandatory pre-trade gate above — stamp the
        # risk-approval token + decision id, then verify before the broker call so
        # this path carries the same No Unauthorized Trade / No Hidden Decision
        # guarantee as the OMS and smart-router paths. MONITOR logs; ENFORCE refuses.
        # Do NOT manufacture a token. It is issued by RiskManager.size_order()
        # as proof the order passed the risk gate; minting one here made the
        # No Unauthorized Trade invariant — a truthiness check — pass on a
        # constant, so it could never detect the thing it exists to detect,
        # not even with HOPEFX_INVARIANT_MODE=enforce.
        # See docs/HARDENING_BACKLOG.md S1-05.
        _token = signal.get("risk_approval_token")
        if not _token:
            logger.critical(
                "TradeExecutor BLOCKED order | symbol=%s reason=missing risk_approval_token "
                "(order did not come from RiskManager.size_order)",
                symbol,
            )
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message="[UNAUTHORIZED] missing risk_approval_token — order did not pass the risk gate",
                latency_ms=0,
            )
        signal["decision_id"] = signal.get("decision_id") or signal.get("signal_id") or _token
        try:
            from invariants.enforcement import enforce_order_authorization

            _auth = enforce_order_authorization(signal)
            if not _auth.allowed:
                logger.critical("TradeExecutor BLOCKED order | symbol=%s reason=%s", symbol, _auth.reason)
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    filled_quantity=0,
                    average_price=0,
                    commission=0,
                    status=OrderStatus.REJECTED,
                    message=f"[UNAUTHORIZED] {_auth.reason}",
                    latency_ms=0,
                )
        except Exception as _auth_exc:  # never let the gate crash execution
            logger.error("TradeExecutor: authorization check raised %s", _auth_exc)

        # ── 5. Journal the intent, then place the order ───────────────────────
        # The window between the broker acking a fill and add_position() below
        # is a crash window. If the process dies inside it, the broker holds a
        # position nothing local ever recorded: it was never written before
        # submission, and no id linked the fill back to a local order. On
        # restart Redis has no trace, so the position is invisible to SL/TP, to
        # risk exposure and to the dashboard, and stays open until someone reads
        # a broker statement.
        #
        # Write the intent first and clear it only once the position is
        # tracked. Anything still journalled at boot is an order that may have
        # filled while we were down — the reconciliation candidate S7-03's
        # broker diff consumes. See docs/HARDENING_BACKLOG.md S7-02 / S7-05.
        client_order_id = f"hopefx-{uuid.uuid4().hex[:16]}"
        signal["client_order_id"] = client_order_id
        await self._journal_intent(client_order_id, symbol, side, size, signal)

        order = await self.broker.place_market_order(
            symbol=symbol,
            side=side,
            quantity=size,
            client_order_id=client_order_id,
        )

        if order.status.value in ("filled", "partial"):
            # The broker has ALREADY EXECUTED this order. A missing or zero
            # fill price is a reporting gap, not a reason to disown the
            # position — brokers that acknowledge a fill and deliver the price
            # in a later message (async and FIX fill reports) hit this on every
            # order. Skipping add_position() here left a live, unprotected
            # position with no stop armed, invisible to risk and the dashboard
            # and unrecoverable on restart, while the caller was told the trade
            # FAILED and sized its next signal as if flat.
            #
            # Record the position at a provisional price, flag it so nothing
            # downstream treats that price as confirmed, and alert.
            # See docs/HARDENING_BACKLOG.md S7-01.
            _price_unconfirmed = not order.average_fill_price or not (order.average_fill_price > 0)
            _entry_price = float(order.average_fill_price or 0.0)
            if _price_unconfirmed:
                _entry_price = self._provisional_fill_price(signal, symbol)
                logger.critical(
                    "TradeExecutor: order %s status=%s but average_fill_price=%s — "
                    "position OPENED at provisional price %.5f and flagged "
                    "price_unconfirmed. Reconcile against the broker before "
                    "trusting P&L for this position.",
                    order.id,
                    order.status.value,
                    order.average_fill_price,
                    _entry_price,
                )

            from execution.position_tracker import Position

            position = Position(
                id=order.id,
                symbol=symbol,
                side="long" if side == "buy" else "short",
                quantity=order.filled_quantity,
                entry_price=_entry_price,
                current_price=_entry_price,
                commission=order.commission,
                stop_loss=signal.get("stop_loss"),
                take_profit=signal.get("take_profit"),
            )
            # Marks a position whose entry price is provisional (S7-01). Set as
            # an attribute rather than a constructor arg so this works with any
            # Position implementation the tracker accepts.
            position.price_unconfirmed = _price_unconfirmed
            await self.position_tracker.add_position(position)

            # The position is now tracked, so the crash window is closed and the
            # intent is no longer a reconciliation candidate. Clearing it is
            # best-effort: a journal error must never make us disown a position
            # the broker has actually filled.
            await self._clear_intent(client_order_id, broker_order_id=order.id)

            # Tell the RiskManager a position opened. Without this the
            # _MAX_OPEN_POSITIONS gate in size_order() reads a counter that is
            # never incremented on this path (it was written only by the
            # standalone hopefx_engine.py), so it compares 0 >= 3 forever and
            # the decision engine can open unbounded concurrent positions.
            # See docs/HARDENING_BACKLOG.md S1-04.
            try:
                self.risk_manager.notify_position_opened(symbol)
            except Exception as _notify_exc:  # never fail an executed order on bookkeeping
                logger.error(
                    "TradeExecutor: notify_position_opened failed for %s: %s — open-position count is now understated",
                    symbol,
                    _notify_exc,
                )

            # A market order that only partially filled leaves an unfilled
            # remainder that is NOT resubmitted here. Surface it explicitly so
            # the shortfall is observable rather than silently dropped.
            if order.status.value == "partial":
                _remainder = size - order.filled_quantity
                logger.warning(
                    "TradeExecutor: PARTIAL fill on %s — requested=%s filled=%s "
                    "remainder=%s NOT resubmitted (order_id=%s)",
                    symbol,
                    size,
                    order.filled_quantity,
                    _remainder,
                    order.id,
                )

        return ExecutionResult(
            success=order.status.value in ("filled", "partial"),
            order_id=order.id,
            filled_quantity=order.filled_quantity,
            average_price=order.average_fill_price,
            commission=order.commission,
            status=OrderStatus(order.status.value),
            message=f"Order {order.status.value}",
        )

    def _resolve_store(self) -> Any:
        """Return the intent journal, resolving it lazily the first time.

        `init_trade_executor` passes the PositionManager's Redis store, but
        `trade_executor` cannot declare `position_manager` as a registry
        dependency: `core/component_registry.py` runs a topological sort in
        which a **failed** dependency causes the dependent to be *skipped*. A
        Redis outage would therefore stop trading altogether rather than merely
        stop journalling — much worse than the problem being solved.

        Startup order is consequently not guaranteed, so an executor built
        before the position manager must still find the store afterwards rather
        than journalling nothing for the life of the process.
        """
        if self.state_store is not None:
            return self.state_store
        if self._store_lookup_done:
            return None

        self._store_lookup_done = True
        try:
            from execution.position_manager import position_manager as _pm

            self.state_store = getattr(_pm, "_redis_store", None)
        except Exception as exc:
            logger.warning("TradeExecutor: could not resolve the order-intent store: %s", exc)
            self.state_store = None

        if self.state_store is None:
            logger.warning(
                "TradeExecutor: no state_store — order intents will NOT be "
                "journalled. A crash between broker ack and add_position leaves "
                "an untracked live position with no way to reconcile it "
                "(docs/HARDENING_BACKLOG.md S7-02)."
            )
        return self.state_store

    async def _journal_intent(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        size: float,
        signal: dict[str, Any],
    ) -> None:
        """Write-ahead record of an order we are about to submit (S7-02).

        Best-effort by design: if the journal is unavailable we log and trade
        anyway. Refusing to trade because Redis is down would convert a
        recovery-visibility gap into an outage, and the paper path has no store
        at all. The cost of the failure is recorded rather than hidden.
        """
        store = self._resolve_store()
        if store is None:
            return
        try:
            await store.save_order(
                {
                    "id": client_order_id,
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": float(size),
                    "status": "intent",
                    "stop_loss": signal.get("stop_loss"),
                    "take_profit": signal.get("take_profit"),
                    "decision_id": signal.get("decision_id"),
                    "risk_approval_token": signal.get("risk_approval_token"),
                }
            )
        except Exception as exc:
            logger.error(
                "TradeExecutor: could not journal order intent %s for %s: %s — "
                "a crash before add_position would leave this position untracked",
                client_order_id,
                symbol,
                exc,
            )

    async def _clear_intent(self, client_order_id: str, broker_order_id: str | None = None) -> None:
        """Drop the write-ahead record once the position is tracked (S7-02)."""
        store = self._resolve_store()
        if store is None:
            return
        try:
            await store.remove_order(client_order_id)
        except Exception as exc:
            logger.error(
                "TradeExecutor: could not clear order intent %s (broker order %s): %s — "
                "it will be re-examined as an orphan at the next boot",
                client_order_id,
                broker_order_id,
                exc,
            )

    def _provisional_fill_price(self, signal: dict[str, Any], symbol: str) -> float:
        """Best available price for a fill the broker confirmed without one.

        Preference order: the signal's intended entry, then the last mark the
        position tracker holds, then 0.0. The result is only ever used on a
        position flagged ``price_unconfirmed`` (S7-01), so it must be treated
        as a placeholder pending reconciliation — never as a real fill.
        """
        for key in ("entry_price", "price", "current_price"):
            raw = signal.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
                return float(raw)
        try:
            getter = getattr(self.position_tracker, "get_last_price", None)
            if callable(getter):
                last = getter(symbol)
                if isinstance(last, (int, float)) and not isinstance(last, bool) and last > 0:
                    return float(last)
        except Exception as exc:
            logger.debug("provisional fill price lookup failed for %s: %s", symbol, exc)
        return 0.0

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

        # Idempotency guard: prevent a concurrent/duplicate close of the same
        # position. The check-and-add is synchronous (no await between the
        # get_position check above and here), so in asyncio it is atomic — a
        # second caller cannot slip past before this id is marked in-flight.
        # Previously two broker.close_position() calls could race across the
        # await below and double-close the position.
        if position_id in self._closing_positions:
            return ExecutionResult(
                success=False,
                order_id=position_id,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Close already in progress: {position_id}",
                latency_ms=0,
            )
        self._closing_positions.add(position_id)
        closed_position = None
        # Default to the last cached mark; replaced with the broker's actual
        # executed close fill below when the broker reports one.
        close_fill_price = position.current_price
        try:
            success = await self.broker.close_position(position_id)
            if success:
                # Prefer the broker's real executed fill price over the cached
                # mark so realised P&L is booked at what actually filled.
                _getter = getattr(self.broker, "get_last_close_fill_price", None)
                if callable(_getter):
                    try:
                        _actual = _getter(position_id)
                        if _actual is not None and math.isfinite(_actual) and _actual > 0:
                            close_fill_price = _actual
                    except Exception as _fp_exc:
                        logger.debug("get_last_close_fill_price failed (non-fatal): %s", _fp_exc)
                closed_position = await self.position_tracker.close_position(
                    position_id,
                    close_fill_price,
                    commission=position.commission,
                )
        finally:
            self._closing_positions.discard(position_id)

        if success and closed_position:
            realized_pnl = closed_position.realized_pnl

            # Mirror of the open notification (S1-04). Without this the
            # open-position counter only ever grows, and the position cap
            # eventually blocks all trading with no positions actually open.
            try:
                self.risk_manager.notify_position_closed(getattr(closed_position, "symbol", position_id))
            except Exception as _notify_exc:
                logger.error(
                    "TradeExecutor: notify_position_closed failed for %s: %s — open-position count is now overstated",
                    position_id,
                    _notify_exc,
                )

            # Update risk manager equity. Increment from CURRENT equity, not the
            # day's starting equity — otherwise each close clobbers the realised
            # P&L of every earlier close on the same day.
            self.risk_manager.update_equity(self.risk_manager.current_balance + realized_pnl)

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
            average_price=close_fill_price if success else 0,
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
            predicted_direction = 1 if _action == "buy" else 0

            import pandas as _pd

            # The online learner derives its features from OHLCV bars; pass the
            # real signal window when available so partial_fit actually learns.
            ohlcv = signal.get("ohlcv")
            if not isinstance(ohlcv, _pd.DataFrame) or ohlcv.empty:
                ohlcv = _pd.DataFrame(
                    [
                        {
                            "entry_price": result.average_price,
                            "filled_qty": result.filled_quantity,
                            "commission": result.commission,
                            "latency_ms": result.latency_ms,
                            "confidence": _confidence,
                            "direction_long": predicted_direction,
                        }
                    ]
                )
            # Pass predicted_direction so the live-accuracy degradation monitor
            # (_check_live_accuracy_degradation) actually accumulates and fires —
            # previously it was never given a prediction and silently never ran.
            engine.update_online(ohlcv, label, predicted_direction=predicted_direction)
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
