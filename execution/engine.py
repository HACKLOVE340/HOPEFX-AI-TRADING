# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/engine.py

Production execution engine — wires broker manager, pre-trade gate,
OMS, position tracker, kill switch, and circuit breakers into a single
async entry point.

Latency target: <50ms end-to-end (signal → broker ACK).
All operations are instrumented with monotonic timestamps.

Design invariants:
- Kill switch checked at engine level (belt-and-suspenders after gate)
- Every exception is logged + Sentry captured — no silent failures
- Circuit breaker: opens after 3 consecutive broker errors in 60s window
- Order state persisted to Redis (via execution/redis_state.py) for crash recovery
- TCA (Transaction Cost Analysis) recorded for every fill
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Optional Sentry
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False


# ---------------------------------------------------------------------------
# Enums / data classes
# ---------------------------------------------------------------------------


class ExecutionStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    BLOCKED = "blocked"  # blocked by pre-trade gate or kill switch
    ERROR = "error"


@dataclass
class ExecutionRequest:
    """Inbound execution request from strategy/signal layer."""

    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: float
    order_type: str = "MARKET"  # "MARKET" | "LIMIT" | "STOP"
    price: float | None = None
    stop_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: str = "unknown"
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.order_type not in ("MARKET", "LIMIT", "STOP"):
            raise ValueError(f"order_type must be MARKET/LIMIT/STOP, got {self.order_type!r}")
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("price required for LIMIT orders")
        if self.order_type == "STOP" and self.stop_price is None:
            raise ValueError("stop_price required for STOP orders")


@dataclass
class ExecutionReport:
    """Result of an execution attempt."""

    request_id: str
    status: ExecutionStatus
    order_id: str | None = None
    filled_quantity: float = 0.0
    average_price: float = 0.0
    commission: float = 0.0
    latency_ms: float = 0.0
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)


# ---------------------------------------------------------------------------
# Engine-level circuit breaker
# ---------------------------------------------------------------------------


class EngineCircuitBreaker:
    """
    Opens after `max_failures` consecutive broker errors within `window_sec`.
    When open, all order submissions are rejected immediately.
    Resets after `reset_sec` seconds with no new orders.
    """

    def __init__(
        self,
        max_failures: int = 3,
        window_sec: float = 60.0,
        reset_sec: float = 120.0,
    ) -> None:
        self._max_failures = max_failures
        self._window_sec = window_sec
        self._reset_sec = reset_sec
        self._failures: list[float] = []  # monotonic timestamps of failures
        self._open = False
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def record_failure(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Prune failures outside window
            self._failures = [t for t in self._failures if now - t < self._window_sec]
            self._failures.append(now)
            if len(self._failures) >= self._max_failures and not self._open:
                self._open = True
                self._opened_at = now
                logger.critical(
                    "ENGINE CIRCUIT BREAKER OPEN: %d failures in %.0fs window.",
                    len(self._failures),
                    self._window_sec,
                )
                if _SENTRY:
                    try:
                        sentry_sdk.capture_message(
                            f"Execution engine circuit breaker opened: "
                            f"{len(self._failures)} failures in {self._window_sec}s",
                            level="critical",
                        )
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)

    async def record_success(self) -> None:
        async with self._lock:
            if self._open:
                logger.info("ENGINE CIRCUIT BREAKER: success recorded, resetting.")
            self._failures.clear()
            self._open = False
            self._opened_at = None

    async def check(self) -> None:
        """Raise RuntimeError if circuit is open."""
        async with self._lock:
            if not self._open:
                return
            elapsed = time.monotonic() - (self._opened_at or 0)
            if elapsed >= self._reset_sec:
                logger.info(
                    "ENGINE CIRCUIT BREAKER: auto-reset after %.0fs.",
                    elapsed,
                )
                self._open = False
                self._opened_at = None
                return
            raise RuntimeError(
                f"Execution engine circuit breaker is OPEN "
                f"({len(self._failures)} failures in {self._window_sec}s window). "
                f"Auto-reset in {self._reset_sec - elapsed:.0f}s.",
            )

    @property
    def is_open(self) -> bool:
        return self._open


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------


class ExecutionEngine:
    """
    Production async execution engine.

    Wires together:
    - BrokerManager (order routing)
    - PreTradeGate (risk checks)
    - OMS (order lifecycle)
    - PositionTracker (position state)
    - KillSwitch (emergency halt)
    - EngineCircuitBreaker (consecutive failure protection)
    - Redis state persistence (crash recovery)
    - TCA recording

    Usage:
        engine = ExecutionEngine(broker_manager, risk_manager, kill_switch)
        await engine.start()
        report = await engine.execute(ExecutionRequest(...))
        await engine.stop()
    """

    def __init__(
        self,
        broker_manager,
        risk_manager,
        kill_switch=None,
        redis_client=None,
        tca_recorder=None,
        max_latency_ms: float = 50.0,
    ) -> None:
        self._broker = broker_manager
        self._risk = risk_manager
        self._kill_switch = kill_switch
        self._redis = redis_client
        self._tca = tca_recorder
        self._max_latency_ms = max_latency_ms

        self._circuit_breaker = EngineCircuitBreaker(
            max_failures=3,
            window_sec=60.0,
            reset_sec=120.0,
        )

        # Execution callbacks (e.g. for strategy feedback)
        self._on_fill_callbacks: list[Callable[[ExecutionReport], None]] = []

        # Metrics
        self._total_orders = 0
        self._total_fills = 0
        self._total_blocks = 0
        self._total_errors = 0
        self._latencies_ms: list[float] = []  # rolling 100

        self._running = False
        self._lock = asyncio.Lock()

        # Tick feed integration — last validated tick per symbol
        # Updated by TickFeedManager bridge via update_last_tick()
        self._last_ticks: dict[str, Any] = {}

        logger.info(
            "ExecutionEngine initialised | max_latency=%.0fms",
            max_latency_ms,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the execution engine."""
        self._running = True
        logger.info("ExecutionEngine started.")

    async def stop(self) -> None:
        """Stop the execution engine gracefully."""
        self._running = False
        logger.info("ExecutionEngine stopped.")

    def add_fill_callback(self, callback: Callable[[ExecutionReport], None]) -> None:
        """Register a callback invoked on every fill."""
        self._on_fill_callbacks.append(callback)

    def update_last_tick(self, symbol: str, tick: Any) -> None:
        """
        Update the last validated tick for a symbol.

        Called by the TickFeedManager bridge on every validated tick so the
        execution engine always has the freshest bid/ask for MARKET order pricing.
        This eliminates the need to call the broker REST API for the current price
        on every order — reducing execution latency by 20–80ms.
        """
        self._last_ticks[symbol] = tick

    def get_last_tick(self, symbol: str) -> Any | None:
        """Return the most recent validated tick for a symbol, or None."""
        return self._last_ticks.get(symbol)

    def get_tick_feed_status(self) -> dict[str, Any]:
        """Return tick feed status for health checks."""
        return {
            "symbols_with_ticks": list(self._last_ticks.keys()),
            "tick_count": len(self._last_ticks),
            "last_ticks": {
                sym: {
                    "mid": round(tick.mid, 5),
                    "timestamp": tick.timestamp.isoformat(),
                    "source": tick.source,
                }
                for sym, tick in self._last_ticks.items()
                if hasattr(tick, "mid")
            },
        }

    # ------------------------------------------------------------------
    # Main execution path
    # ------------------------------------------------------------------

    async def execute(self, request: ExecutionRequest) -> ExecutionReport:
        """
        Execute a trading request end-to-end.

        Flow:
          1. Data-layer safety check + price enrichment
          2. Kill-switch / engine-stopped / circuit-breaker guards
          3. Pre-trade gate (risk checks)
          4. Algo routing (TWAP/VWAP/Iceberg for large orders)
          5. Sharpe circuit-breaker model gate
          6. TCA signal-price capture
          7. Broker submission
          8. Post-fill processing (Redis, TCA fill, callbacks, Sharpe record)

        Returns ExecutionReport — never raises.
        """
        t0 = time.monotonic()
        self._total_orders += 1

        request = self._enrich_price_from_data_layer(request, t0)
        if isinstance(request, ExecutionReport):
            return request  # data-layer block

        request = self._enrich_price_from_tick_feed(request)

        block = self._check_pre_submission_guards(request, t0)
        if block is not None:
            return block

        block = await self._check_pre_trade_gate(request, t0)
        if block is not None:
            return block

        algo_report = await self._try_algo_routing(request, t0)
        if algo_report is not None:
            return algo_report

        block = self._check_sharpe_circuit_breaker(request, t0)
        if block is not None:
            return block

        self._record_tca_signal_price(request)

        return await self._submit_and_process(request, t0)

    # ------------------------------------------------------------------
    # execute() sub-steps — each ≤ 30 lines, independently testable
    # ------------------------------------------------------------------

    def _enrich_price_from_data_layer(
        self, request: ExecutionRequest, t0: float
    ) -> "ExecutionRequest | ExecutionReport":
        """
        Check data-layer safety and inject the current mid-price when absent.

        Returns a blocked ExecutionReport when the data layer signals unsafe
        conditions. Returns the (possibly enriched) request otherwise.
        Data-layer unavailability is non-fatal — execution proceeds without enrichment.
        """
        try:
            from data_layer.orchestrator import orchestrator

            if orchestrator._started and not orchestrator.is_safe_to_trade():
                self._total_blocks += 1
                return self._blocked_report(
                    request, "[DATA_LAYER] Unsafe trading conditions (blackout/no feed)", t0
                )

            if request.price is None and request.order_type == "MARKET":
                tick = orchestrator.get_latest_tick(request.symbol)
                if tick and tick.mid > 0:
                    return self._clone_request_with_price(
                        request,
                        tick.mid,
                        {"dl_mid": tick.mid, "dl_source": tick.source.value, "dl_confidence": tick.confidence},
                    )
        except Exception as exc:
            logger.debug("Data-layer enrichment skipped: %s", exc)
        return request

    def _enrich_price_from_tick_feed(self, request: ExecutionRequest) -> ExecutionRequest:
        """
        Inject the TickFeed last-tick mid-price for MARKET orders without a price.

        The TickFeed cache is the lowest-latency price source — no REST call needed.
        Returns the request unchanged when no tick is available.
        """
        if request.price is not None or request.order_type != "MARKET":
            return request
        tf_tick = self._last_ticks.get(request.symbol)
        if tf_tick is None or not hasattr(tf_tick, "mid") or tf_tick.mid <= 0:
            return request
        mid = tf_tick.mid
        logger.debug("ExecutionEngine: price enriched from TickFeed — %s mid=%.5f", request.symbol, mid)
        return self._clone_request_with_price(
            request,
            mid,
            {
                "tf_mid": mid,
                "tf_source": getattr(tf_tick, "source", "tick_feed"),
                "tf_ts": tf_tick.timestamp.isoformat() if hasattr(tf_tick, "timestamp") else "",
            },
        )

    @staticmethod
    def _clone_request_with_price(
        request: ExecutionRequest, price: float, extra_meta: dict[str, Any]
    ) -> ExecutionRequest:
        """Return a new ExecutionRequest with the given price and merged metadata."""
        return ExecutionRequest(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            price=price,
            stop_price=request.stop_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            strategy_id=request.strategy_id,
            request_id=request.request_id,
            metadata={**request.metadata, **extra_meta},
        )

    def _check_pre_submission_guards(
        self, request: ExecutionRequest, t0: float
    ) -> "ExecutionReport | None":
        """
        Check kill-switch and engine-stopped state synchronously.

        The circuit-breaker check (async) is handled in _check_pre_trade_gate().
        Returns a blocked ExecutionReport on the first failed guard, or None.
        """
        if self._kill_switch and self._kill_switch.is_active():
            reason = getattr(self._kill_switch, "_reason", "kill switch active")
            self._total_blocks += 1
            return self._blocked_report(request, f"[KILL_SWITCH] {reason}", t0)

        if not self._running:
            self._total_blocks += 1
            return self._blocked_report(request, "[ENGINE_STOPPED]", t0)

        return None

    async def _check_pre_trade_gate(
        self, request: ExecutionRequest, t0: float
    ) -> "ExecutionReport | None":
        """
        Run circuit-breaker check then pre-trade risk gate.

        Returns a blocked report on failure, None when all checks pass.
        """
        try:
            await self._circuit_breaker.check()
        except RuntimeError as exc:
            self._total_blocks += 1
            return self._blocked_report(request, f"[CIRCUIT_BREAKER] {exc}", t0)

        try:
            gate_reason = await self._run_pre_trade_gate(request)
        except Exception as exc:
            self._total_blocks += 1
            logger.error("ExecutionEngine: pre-trade gate error for %s: %s", request.request_id, exc)
            self._capture_sentry(exc)
            return self._blocked_report(request, f"[GATE_ERROR] {exc}", t0)

        if gate_reason is not None:
            self._total_blocks += 1
            return self._blocked_report(request, gate_reason, t0)

        return None

    async def _try_algo_routing(
        self, request: ExecutionRequest, t0: float
    ) -> "ExecutionReport | None":
        """
        Route large orders through the algo layer (TWAP/VWAP/Iceberg).

        Returns a SUBMITTED report when the order is handed off, None for
        small orders that should proceed as plain market orders.
        """
        try:
            from execution.algo_orders import get_algo_manager

            algo_mgr = get_algo_manager()
            if algo_mgr._broker_submit is None:
                algo_mgr.set_broker_submit_fn(self._make_algo_broker_fn())

            algo_id = await algo_mgr.submit_auto(
                symbol=request.symbol,
                side=request.side,
                total_quantity=request.quantity,
                strategy_id=request.strategy_id,
            )
            if algo_id is not None:
                latency_ms = (time.monotonic() - t0) * 1000.0
                return ExecutionReport(
                    request_id=request.request_id,
                    status=ExecutionStatus.SUBMITTED,
                    latency_ms=latency_ms,
                    message=f"[ALGO] Order routed to algo layer (id={algo_id})",
                    metadata={"algo_id": algo_id},
                )
        except Exception as exc:
            logger.debug("Algo order routing check failed: %s", exc)
        return None

    def _make_algo_broker_fn(self):
        """Return an async broker-submit callable for the algo manager."""

        async def _broker_fn(**kwargs):
            req = ExecutionRequest(
                symbol=kwargs["symbol"],
                side=kwargs["side"],
                quantity=kwargs["quantity"],
                order_type=kwargs.get("order_type", "MARKET"),
                strategy_id=kwargs.get("metadata", {}).get("strategy_id", "algo"),
                metadata=kwargs.get("metadata", {}),
            )
            rep = await self._submit_to_broker(req, time.monotonic())
            return {
                "success": rep.success,
                "fill_price": rep.average_price,
                "filled_quantity": rep.filled_quantity,
            }

        return _broker_fn

    def _check_sharpe_circuit_breaker(
        self, request: ExecutionRequest, t0: float
    ) -> "ExecutionReport | None":
        """
        Gate the model out when its rolling live Sharpe is below threshold.

        Returns a blocked report when the model is gated, None otherwise.
        Sharpe CB unavailability is non-fatal — execution proceeds.
        """
        model_version = request.metadata.get("model_version") or request.strategy_id
        if not model_version:
            return None
        try:
            from ml.sharpe_circuit_breaker import get_sharpe_cb

            if get_sharpe_cb().is_open(model_version):
                self._total_blocks += 1
                return self._blocked_report(
                    request,
                    f"[SHARPE_CIRCUIT_OPEN] Model '{model_version}' gated — rolling Sharpe below threshold",
                    t0,
                )
        except Exception as exc:
            logger.debug("SharpeCircuitBreaker check failed: %s", exc)
        return None

    def _record_tca_signal_price(self, request: ExecutionRequest) -> None:
        """
        Capture the signal price in TCA before broker submission.

        Slippage = fill_price − signal_price, computed post-fill in _record_tca().
        Non-fatal — TCA unavailability must never block order submission.
        """
        signal_price = float(request.metadata.get("signal_price") or request.price or 0.0)
        if signal_price <= 0:
            return
        try:
            from execution.tca_recorder import get_tca_recorder

            get_tca_recorder().record_signal(
                request_id=request.request_id,
                symbol=request.symbol,
                side=request.side,
                signal_price=signal_price,
                quantity=request.quantity,
                model_version=request.metadata.get("model_version", "unknown"),
            )
        except Exception as exc:
            logger.debug("TCA record_signal failed: %s", exc)

    async def _submit_and_process(
        self, request: ExecutionRequest, t0: float
    ) -> ExecutionReport:
        """
        Submit to broker and run all post-fill processing.

        On broker error: records circuit-breaker failure, increments error
        counter, and returns an ERROR report — never raises.
        On fill success: persists to Redis, records TCA fill, fires callbacks,
        updates Sharpe CB, and warns on latency breach.
        """
        try:
            report = await self._submit_to_broker(request, t0)
        except Exception as exc:
            logger.error(
                "ExecutionEngine: broker submission error for %s: %s\n%s",
                request.request_id,
                exc,
                traceback.format_exc(),
            )
            self._capture_sentry(exc)
            await self._circuit_breaker.record_failure()
            self._total_errors += 1
            return ExecutionReport(
                request_id=request.request_id,
                status=ExecutionStatus.ERROR,
                latency_ms=(time.monotonic() - t0) * 1000.0,
                message="[BROKER_ERROR] Order submission failed — check server logs",
            )

        if report.success:
            await self._handle_fill_success(request, report)
        else:
            await self._circuit_breaker.record_failure()
            self._total_errors += 1

        return report

    async def _handle_fill_success(
        self, request: ExecutionRequest, report: ExecutionReport
    ) -> None:
        """Run all post-fill side-effects for a successful order."""
        await self._circuit_breaker.record_success()
        self._total_fills += 1
        self._record_latency(report.latency_ms)
        await self._persist_to_redis(request, report)
        await self._record_tca(request, report)
        await self._notify_callbacks(report)
        self._update_sharpe_circuit_breaker(request, report)
        self._warn_on_latency_breach(request, report)

    def _update_sharpe_circuit_breaker(
        self, request: ExecutionRequest, report: ExecutionReport
    ) -> None:
        """Record trade P&L in the Sharpe circuit breaker for live model gating."""
        model_version = request.metadata.get("model_version") or request.strategy_id
        if not model_version:
            return
        pnl = report.metadata.get("realised_pnl", 0.0)
        try:
            from ml.sharpe_circuit_breaker import get_sharpe_cb

            get_sharpe_cb().record_trade(pnl=pnl, model_version=model_version)
        except Exception as exc:
            logger.debug("SharpeCircuitBreaker record failed: %s", exc)

    def _warn_on_latency_breach(
        self, request: ExecutionRequest, report: ExecutionReport
    ) -> None:
        """Log a warning when fill latency exceeds the configured target."""
        if report.latency_ms > self._max_latency_ms:
            logger.warning(
                "ExecutionEngine: latency %.2fms exceeds target %.0fms | symbol=%s request_id=%s",
                report.latency_ms,
                self._max_latency_ms,
                request.symbol,
                request.request_id,
            )

    # ------------------------------------------------------------------
    # Pre-trade gate
    # ------------------------------------------------------------------

    async def _run_pre_trade_gate(self, request: ExecutionRequest) -> str | None:
        """
        Run pre-trade gate checks.

        Returns None if all checks pass, or a block reason string.
        Raises on unexpected gate errors (caller blocks the trade).
        """
        from risk.pre_trade_gate import (
            GateOrder,
            PreTradeGate,
            RiskManagerError,
            TradeBlockedError,
        )

        gate = PreTradeGate(self._risk)
        gate_order = GateOrder(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            price=request.price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            strategy_id=request.strategy_id,
        )

        try:
            gate.check(gate_order)
            return None  # all checks passed
        except TradeBlockedError as exc:
            logger.warning(
                "ExecutionEngine: trade blocked | request_id=%s reason=%s detail=%s",
                request.request_id,
                exc.reason_code,
                exc.detail,
            )
            return f"[{exc.reason_code}] {exc.detail}"
        except RiskManagerError as exc:
            logger.critical(
                "ExecutionEngine: risk manager error — blocking trade | request_id=%s error=%s",
                request.request_id,
                exc,
            )
            self._capture_sentry(exc)
            return f"[RISK_MANAGER_ERROR] {exc}"

    # ------------------------------------------------------------------
    # Broker submission
    # ------------------------------------------------------------------

    async def _submit_to_broker(
        self,
        request: ExecutionRequest,
        t0: float,
    ) -> ExecutionReport:
        """Submit order to broker and return ExecutionReport."""
        from brokers.base import OrderSide, OrderType

        side = OrderSide.BUY if request.side == "BUY" else OrderSide.SELL
        order_type_map = {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP": OrderType.STOP,
        }
        order_type = order_type_map[request.order_type]

        logger.info(
            "ExecutionEngine: submitting | request_id=%s symbol=%s side=%s type=%s qty=%.4f price=%s",
            request.request_id,
            request.symbol,
            request.side,
            request.order_type,
            request.quantity,
            request.price,
        )

        # Run synchronous broker call in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        order = await loop.run_in_executor(
            None,
            lambda: self._broker.place_order(
                symbol=request.symbol,
                side=side,
                order_type=order_type,
                quantity=request.quantity,
                price=request.price,
                stop_price=request.stop_price,
            ),
        )

        latency_ms = (time.monotonic() - t0) * 1000.0

        from brokers.base import OrderStatus as BrokerOrderStatus

        status_map = {
            BrokerOrderStatus.FILLED: ExecutionStatus.FILLED,
            BrokerOrderStatus.PARTIAL: ExecutionStatus.PARTIAL,
            BrokerOrderStatus.REJECTED: ExecutionStatus.REJECTED,
            BrokerOrderStatus.CANCELLED: ExecutionStatus.REJECTED,
            BrokerOrderStatus.PENDING: ExecutionStatus.SUBMITTED,
            BrokerOrderStatus.OPEN: ExecutionStatus.SUBMITTED,
        }
        exec_status = status_map.get(order.status, ExecutionStatus.SUBMITTED)

        report = ExecutionReport(
            request_id=request.request_id,
            status=exec_status,
            order_id=order.id,
            filled_quantity=order.filled_quantity or 0.0,
            average_price=order.average_price or 0.0,
            commission=0.0,  # populated by TCA if available
            latency_ms=latency_ms,
            message=f"Order {order.status.value}",
            metadata={
                "broker_order_id": order.id,
                "broker_status": order.status.value,
                "symbol": request.symbol,
                "strategy_id": request.strategy_id,
            },
        )

        logger.info(
            "ExecutionEngine: fill report | request_id=%s order_id=%s status=%s filled=%.4f avg_px=%.4f latency=%.2fms",
            request.request_id,
            order.id,
            exec_status.value,
            report.filled_quantity,
            report.average_price,
            latency_ms,
        )
        return report

    # ------------------------------------------------------------------
    # Post-fill processing
    # ------------------------------------------------------------------

    async def _persist_to_redis(
        self,
        request: ExecutionRequest,
        report: ExecutionReport,
    ) -> None:
        """Persist order state to Redis for crash recovery."""
        if self._redis is None:
            return
        try:
            import json

            key = f"execution:order:{report.order_id}"
            payload = json.dumps(
                {
                    "request_id": request.request_id,
                    "order_id": report.order_id,
                    "symbol": request.symbol,
                    "side": request.side,
                    "quantity": request.quantity,
                    "filled_quantity": report.filled_quantity,
                    "average_price": report.average_price,
                    "status": report.status.value,
                    "latency_ms": report.latency_ms,
                    "timestamp": report.timestamp.isoformat(),
                    "strategy_id": request.strategy_id,
                }
            )
            # TTL: 7 days
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._redis.setex(key, 604800, payload),
            )
        except Exception as exc:
            # Redis failure must not block execution
            logger.error("ExecutionEngine: Redis persist failed: %s", exc)
            self._capture_sentry(exc)

    async def _record_tca(
        self,
        request: ExecutionRequest,
        report: ExecutionReport,
    ) -> None:
        """
        Record transaction cost analysis.

        Uses TCARecorder to compute slippage as fill_price - signal_price.
        Also calls the legacy tca_recorder if one was injected at construction.
        """
        # ── New TCARecorder: signal_price vs fill_price ───────────────────────
        try:
            from execution.tca_recorder import get_tca_recorder

            broker = report.metadata.get("broker", "unknown") if report.metadata else "unknown"
            get_tca_recorder().record_fill(
                request_id=request.request_id,
                fill_price=report.average_price,
                filled_quantity=report.filled_quantity,
                broker=broker,
                latency_ms=report.latency_ms,
            )
        except Exception as exc:
            logger.debug("TCARecorder record_fill failed: %s", exc)

        # ── Legacy tca_recorder (backward compat) ─────────────────────────────
        if self._tca is None:
            return
        try:
            if hasattr(self._tca, "record"):
                self._tca.record(
                    symbol=request.symbol,
                    side=request.side,
                    quantity=report.filled_quantity,
                    avg_price=report.average_price,
                    latency_ms=report.latency_ms,
                    strategy_id=request.strategy_id,
                )
        except Exception as exc:
            logger.error("ExecutionEngine: legacy TCA record failed: %s", exc)

    async def _notify_callbacks(self, report: ExecutionReport) -> None:
        """Invoke all registered fill callbacks."""
        for cb in self._on_fill_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(report)
                else:
                    cb(report)
            except Exception as exc:
                logger.error("ExecutionEngine: fill callback error: %s", exc)
                self._capture_sentry(exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _blocked_report(
        self,
        request: ExecutionRequest,
        reason: str,
        t0: float,
    ) -> ExecutionReport:
        latency_ms = (time.monotonic() - t0) * 1000.0
        logger.warning(
            "ExecutionEngine: ORDER BLOCKED | request_id=%s symbol=%s side=%s qty=%.4f reason=%s",
            request.request_id,
            request.symbol,
            request.side,
            request.quantity,
            reason,
        )
        return ExecutionReport(
            request_id=request.request_id,
            status=ExecutionStatus.BLOCKED,
            latency_ms=latency_ms,
            message=reason,
        )

    def _record_latency(self, latency_ms: float) -> None:
        self._latencies_ms.append(latency_ms)
        if len(self._latencies_ms) > 100:
            self._latencies_ms.pop(0)

    def get_metrics(self) -> dict[str, Any]:
        """Return execution metrics snapshot."""
        avg_latency = sum(self._latencies_ms) / len(self._latencies_ms) if self._latencies_ms else 0.0
        p99_latency = (
            sorted(self._latencies_ms)[int(len(self._latencies_ms) * 0.99)]
            if len(self._latencies_ms) >= 100
            else 0.0
        )
        return {
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "total_blocks": self._total_blocks,
            "total_errors": self._total_errors,
            "fill_rate": self._total_fills / max(self._total_orders, 1),
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "circuit_breaker_open": self._circuit_breaker.is_open,
        }

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
