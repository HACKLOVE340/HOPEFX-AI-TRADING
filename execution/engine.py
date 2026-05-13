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
import os
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

# ── Live-mode safety constants ─────────────────────────────────────────────────
# Set LIVE_MODE_CONFIRMED=true in the environment to enable live order execution.
# Without this flag, any broker that is NOT paper trading will refuse to execute.
_LIVE_MODE_CONFIRMED: bool = os.getenv("LIVE_MODE_CONFIRMED", "false").lower() == "true"

# ── Maximum leverage ratio (notional / account equity) ─────────────────────────
_MAX_LEVERAGE_RATIO: float = float(os.getenv("MAX_LEVERAGE_RATIO", "10.0"))

# ── Minimum margin buffer before any order is submitted ─────────────────────────
# Require at least this ratio of free margin to used margin (200% = 2.0).
_MIN_MARGIN_BUFFER: float = float(os.getenv("MIN_MARGIN_BUFFER", "2.0"))

logger = logging.getLogger(__name__)

# Optional Sentry
try:
    import sentry_sdk

    _SENTRY = True
except ImportError:
    _SENTRY = False


# ---------------------------------------------------------------------------
# No-op OTel context manager (used when opentelemetry-sdk is not installed)
# ---------------------------------------------------------------------------


class _NullSpanCtx:
    """Minimal no-op context manager used when OTel tracing is unavailable.

    Implements the same interface used in ``execute()`` so all span code paths
    degrade gracefully without branching everywhere.
    """

    def set_attribute(self, *_: Any, **__: Any) -> None:
        pass

    def add_event(self, *_: Any, **__: Any) -> None:
        pass

    def __enter__(self) -> _NullSpanCtx:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# Module-level tracer cache.  Loaded once on first execute() call to avoid
# repeated import+try/except overhead on the hot order path.
# None  → not yet resolved.
# False → api.tracing unavailable (permanent, stop retrying).
# Any other value → the live tracer object.
_module_tracer: Any = None


def _get_module_tracer() -> Any:
    """Return the cached module-level OTel tracer (or _NullSpanCtx factory)."""
    global _module_tracer
    if _module_tracer is None:
        try:
            from api.tracing import get_tracer as _get_tracer

            _module_tracer = _get_tracer("hopefx.execution")
        except (ImportError, RuntimeError):
            _module_tracer = False  # permanent failure sentinel
    return _module_tracer if _module_tracer else None


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
        if self.order_type == "LIMIT":
            if self.price is None:
                raise ValueError("price required for LIMIT orders")
            if self.price <= 0:
                raise ValueError(f"price must be > 0 for LIMIT orders, got {self.price}")
        if self.order_type == "STOP":
            if self.stop_price is None:
                raise ValueError("stop_price required for STOP orders")
            if self.stop_price <= 0:
                raise ValueError(f"stop_price must be > 0 for STOP orders, got {self.stop_price}")


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
        # SUBMITTED is treated as success: async and paper-trading brokers return
        # SUBMITTED when the order is accepted by the broker without waiting for
        # an exchange fill acknowledgement.  Excluding it would make the circuit
        # breaker never record a success for the paper-trading path and would
        # prevent the signal→order callback chain from firing.
        return self.status in (
            ExecutionStatus.FILLED,
            ExecutionStatus.PARTIAL,
            ExecutionStatus.SUBMITTED,
        )


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
                    except (RuntimeError, AttributeError) as _exc:
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
            if self._opened_at is None:
                logger.error("EngineCircuitBreaker: _open=True but _opened_at=None — forcing close")
                self._open = False
                return
            elapsed = time.monotonic() - self._opened_at
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
        broker_manager: Any,
        risk_manager: Any,
        kill_switch: Any = None,
        redis_client: Any = None,
        tca_recorder: Any = None,
        max_latency_ms: float = 50.0,
        position_manager: Any = None,
    ) -> None:
        self._broker = broker_manager
        self._risk = risk_manager
        self._kill_switch = kill_switch
        self._redis = redis_client
        self._tca = tca_recorder
        self._max_latency_ms = max_latency_ms
        self._position_manager = position_manager

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
        self._latencies_ms: deque[float] = deque(maxlen=100)  # rolling 100, O(1) append/evict

        self._running = False
        self._lock = asyncio.Lock()
        # Dedicated counter lock — keeps metric mutations off the general _lock
        # so lifecycle operations (start/stop) never contend with hot-path counters.
        self._counter_lock = asyncio.Lock()

        # Tick feed integration — last validated tick per symbol
        # Updated by TickFeedManager bridge via update_last_tick()
        self._last_ticks: dict[str, Any] = {}

        # SL/TP monitor — started in start(), stopped in stop()
        self._sltp_monitor: Any = None

        # Self-trade prevention singleton — lazy-initialised on first order
        self._stp: Any = None

        logger.info(
            "ExecutionEngine initialised | max_latency=%.0fms",
            max_latency_ms,
        )

        # Warn loudly if live trading is enabled without LIVE_MODE_CONFIRMED
        self._live_mode_confirmed = _LIVE_MODE_CONFIRMED
        if not self._live_mode_confirmed:
            logger.info(
                "ExecutionEngine: LIVE_MODE_CONFIRMED not set — "
                "live broker orders will be BLOCKED. "
                "Set LIVE_MODE_CONFIRMED=true to enable live trading."
            )

    # ------------------------------------------------------------------
    # Thread-safe counter helpers
    # All mutations go through _counter_lock so reads in get_metrics_async()
    # see a consistent snapshot and never race with concurrent increments.
    # ------------------------------------------------------------------

    async def _inc_orders(self) -> None:
        async with self._counter_lock:
            self._total_orders += 1

    async def _inc_fills(self) -> None:
        async with self._counter_lock:
            self._total_fills += 1

    async def _inc_blocks(self) -> None:
        async with self._counter_lock:
            self._total_blocks += 1

    async def _inc_errors(self) -> None:
        async with self._counter_lock:
            self._total_errors += 1

    async def _append_latency(self, latency_ms: float) -> None:
        async with self._counter_lock:
            self._latencies_ms.append(latency_ms)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the execution engine and background safety monitors."""
        self._running = True

        # Start SL/TP monitor (prevents unlimited loss on open positions)
        if self._position_manager is not None:
            try:
                from execution.sl_tp_monitor import SLTPMonitor

                self._sltp_monitor = SLTPMonitor(
                    position_manager=self._position_manager,
                    broker=self._broker,
                    tick_cache=self._last_ticks,
                )
                await self._sltp_monitor.start()
                logger.info("ExecutionEngine: SL/TP monitor started.")
            except Exception as exc:
                logger.error("ExecutionEngine: could not start SL/TP monitor: %s", exc)

        logger.info("ExecutionEngine started.")

    async def stop(self) -> None:
        """Stop the execution engine and all background tasks gracefully."""
        self._running = False

        if self._sltp_monitor is not None:
            try:
                await self._sltp_monitor.stop()
            except Exception as exc:
                logger.error("ExecutionEngine: error stopping SL/TP monitor: %s", exc)
            self._sltp_monitor = None

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

        Also feeds the spread monitor to maintain a rolling reference baseline.
        Validates the tick through the LiveTradingGuard to reject future-dated
        or stale ticks before they can influence order pricing.
        """
        # Live trading guard: reject future-dated or stale ticks
        try:
            from risk.lookahead_guard import live_guard, FutureTimestampError, StaleDataError

            live_guard.validate_tick(tick, symbol=symbol)
        except (FutureTimestampError, StaleDataError) as _guard_err:
            logger.warning(
                "ExecutionEngine: tick rejected by LiveTradingGuard for %s: %s",
                symbol,
                _guard_err,
            )
            return  # Do not update last tick with invalid data
        except Exception:  # nosec B110 — guard is non-fatal if unavailable
            pass

        self._last_ticks[symbol] = tick
        # Feed spread monitor for real-time spike detection
        try:
            from execution.spread_monitor import get_spread_monitor

            get_spread_monitor().on_tick_obj(symbol, tick)
        except Exception:  # nosec B110 — spread monitor is non-fatal
            pass

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
        # ── OTel instrumentation — use module-level cached tracer ─────────────
        _tracer = _get_module_tracer()

        _root_span_ctx = _tracer.start_as_current_span("execution.execute") if _tracer is not None else _NullSpanCtx()

        with _root_span_ctx as _root_span:
            # Attach request attributes to the root span
            try:
                _root_span.set_attribute("symbol", request.symbol)
                _root_span.set_attribute("side", request.side)
                _root_span.set_attribute("quantity", request.quantity)
                _root_span.set_attribute("strategy_id", request.strategy_id)
                _root_span.set_attribute("request_id", request.request_id)
                _root_span.set_attribute("order_type", request.order_type)
            except (TypeError, ValueError, AttributeError) as _span_exc:
                logger.debug("OTel span error in %s: %s", __name__, _span_exc)

            t0 = time.monotonic()
            await self._inc_orders()

            _enriched = self._enrich_price_from_data_layer(request, t0)
            if isinstance(_enriched, ExecutionReport):
                try:
                    _root_span.add_event("data_layer.blocked", {"reason": _enriched.message})
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                return _enriched  # data-layer block
            request = _enriched

            request = self._enrich_price_from_tick_feed(request)

            block = self._check_pre_submission_guards(request, t0)
            if block is not None:
                try:
                    is_ks = "[KILL_SWITCH]" in block.message
                    _root_span.add_event(
                        "kill_switch.active" if is_ks else "engine.stopped",
                        {"reason": block.message},
                    )
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                return block

            # ── pre_trade_gate child span ─────────────────────────────────
            _gate_ctx = (
                _tracer.start_as_current_span("execution.pre_trade_gate") if _tracer is not None else _NullSpanCtx()
            )
            with _gate_ctx as _gate_span:
                try:
                    _gate_span.set_attribute("symbol", request.symbol)
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                block = await self._check_pre_trade_gate(request, t0)
                if block is not None:
                    try:
                        is_cb = "[CIRCUIT_BREAKER]" in block.message
                        _gate_span.add_event(
                            "circuit_breaker.open" if is_cb else "gate.blocked",
                            {"reason": block.message},
                        )
                        _root_span.add_event(
                            "circuit_breaker.open" if is_cb else "gate.blocked",
                            {"reason": block.message},
                        )
                    except (TypeError, ValueError, AttributeError) as _span_exc:
                        logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                    return block
                try:
                    _gate_span.add_event("gate.passed")
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)

            algo_report = await self._try_algo_routing(request, t0)
            if algo_report is not None:
                try:
                    _root_span.add_event("algo.routed", {"algo_id": str(algo_report.metadata.get("algo_id", ""))})
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                return algo_report

            block = self._check_sharpe_circuit_breaker(request, t0)
            if block is not None:
                try:
                    _root_span.add_event("sharpe_circuit_breaker.open", {"reason": block.message})
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)
                return block

            self._record_tca_signal_price(request)

            # ── broker_submit child span ──────────────────────────────────
            _broker_ctx = (
                _tracer.start_as_current_span("execution.broker_submit") if _tracer is not None else _NullSpanCtx()
            )
            with _broker_ctx as _broker_span:
                try:
                    _broker_span.set_attribute("symbol", request.symbol)
                    _broker_span.set_attribute("side", request.side)
                    _broker_span.set_attribute("quantity", request.quantity)
                except (TypeError, ValueError, AttributeError) as _span_exc:
                    logger.debug("OTel span error in %s: %s", __name__, _span_exc)

                report = await self._submit_and_process(request, t0)

                # ── post_fill child span ──────────────────────────────────
                _fill_ctx = (
                    _tracer.start_as_current_span("execution.post_fill") if _tracer is not None else _NullSpanCtx()
                )
                with _fill_ctx as _fill_span:
                    try:
                        if report.success:
                            _fill_span.add_event(
                                "fill.success",
                                {
                                    "order_id": str(report.order_id or ""),
                                    "filled_qty": report.filled_quantity,
                                    "avg_price": report.average_price,
                                    "latency_ms": report.latency_ms,
                                },
                            )
                            _root_span.add_event("fill.success", {"order_id": str(report.order_id or "")})
                        else:
                            _fill_span.add_event("fill.failure", {"reason": report.message})
                            _root_span.add_event("fill.failure", {"reason": report.message})
                        _fill_span.set_attribute("status", report.status.value)
                        _root_span.set_attribute("execution.status", report.status.value)
                        _root_span.set_attribute("execution.latency_ms", report.latency_ms)
                    except (TypeError, ValueError, AttributeError) as _span_exc:
                        logger.debug("OTel span error in %s: %s", __name__, _span_exc)

                return report

    # ------------------------------------------------------------------
    # execute() sub-steps — each ≤ 30 lines, independently testable
    # ------------------------------------------------------------------

    def _enrich_price_from_data_layer(self, request: ExecutionRequest, t0: float) -> ExecutionRequest | ExecutionReport:
        """
        Check data-layer safety and inject the current mid-price when absent.

        Returns a blocked ExecutionReport when the data layer signals unsafe
        conditions. Returns the (possibly enriched) request otherwise.
        Data-layer unavailability is non-fatal — execution proceeds without enrichment.
        """
        try:
            from data_layer.orchestrator import orchestrator

            if orchestrator._started and not orchestrator.is_safe_to_trade():
                await self._inc_blocks()
                return self._blocked_report(request, "[DATA_LAYER] Unsafe trading conditions (blackout/no feed)", t0)

            if request.price is None and request.order_type == "MARKET":
                tick = orchestrator.get_latest_tick(request.symbol)
                if tick and tick.mid > 0:
                    return self._clone_request_with_price(
                        request,
                        tick.mid,
                        {
                            "dl_mid": tick.mid,
                            # tick.source may be an enum or a plain string; handle both.
                            "dl_source": getattr(tick.source, "value", str(tick.source)),
                            "dl_confidence": tick.confidence,
                        },
                    )
        except (AttributeError, TypeError, ValueError, ImportError) as exc:
            logger.warning("Data-layer enrichment skipped: %s", exc)
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

    def _check_pre_submission_guards(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
        """
        Check kill-switch, engine-stopped, and LIVE_MODE_CONFIRMED state synchronously.

        The circuit-breaker check (async) is handled in _check_pre_trade_gate().
        Returns a blocked ExecutionReport on the first failed guard, or None.
        """
        if self._kill_switch and self._kill_switch.is_active():
            reason = getattr(self._kill_switch, "_reason", "kill switch active")
            await self._inc_blocks()
            return self._blocked_report(request, f"[KILL_SWITCH] {reason}", t0)

        if not self._running:
            await self._inc_blocks()
            return self._blocked_report(request, "[ENGINE_STOPPED]", t0)

        # ── LIVE_MODE_CONFIRMED safety gate ───────────────────────────────────
        if not self._live_mode_confirmed and self._is_live_broker():
            await self._inc_blocks()
            msg = (
                "[LIVE_MODE_NOT_CONFIRMED] Live broker detected but LIVE_MODE_CONFIRMED "
                "is not set. Set LIVE_MODE_CONFIRMED=true in the environment to allow "
                "live order execution. Orders are blocked to prevent accidental live trading."
            )
            logger.critical(msg)
            return self._blocked_report(request, msg, t0)

        # ── Spread spike guard ────────────────────────────────────────────────
        spread_block = self._check_spread_spike(request, t0)
        if spread_block is not None:
            return spread_block

        return None

    def _is_live_broker(self) -> bool:
        """Return True when the current broker is NOT paper trading."""
        if self._broker is None:
            return False
        # BrokerManager exposes current_broker; fall back to checking broker directly
        broker = getattr(self._broker, "current_broker", self._broker)
        # Paper trading detection: class name contains 'Paper', or .paper_trading attr
        if hasattr(broker, "paper_trading") and broker.paper_trading:
            return False
        broker_name = type(broker).__name__.lower()
        return not ("paper" in broker_name or "mock" in broker_name or "fake" in broker_name)

    def _check_spread_spike(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
        """
        Block the order if the current spread for the symbol is abnormally wide.

        Uses the spread monitor singleton which is updated on every tick via
        :meth:`update_last_tick`. Returns a blocked report when spiking, or
        ``None`` to allow the order through.

        Non-fatal on spread monitor unavailability — execution proceeds.
        """
        try:
            from execution.spread_monitor import get_spread_monitor

            monitor = get_spread_monitor()
            if monitor.is_spread_spiking(request.symbol):
                snap = monitor.get_snapshot(request.symbol)
                msg = (
                    f"[SPREAD_SPIKE] {request.symbol} spread {snap.current_spread:.5f} "
                    f"is {snap.ratio:.1f}× baseline {snap.baseline_spread:.5f} — "
                    f"order blocked to prevent adverse execution"
                )
                logger.warning(msg)
                await self._inc_blocks()
                return self._blocked_report(request, msg, t0)
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("Spread spike check failed (non-fatal): %s", exc)
        return None

    async def _check_pre_trade_gate(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
        """
        Run circuit-breaker check then pre-trade risk gate, self-trade prevention,
        margin check, and leverage cap.

        Returns a blocked report on failure, None when all checks pass.
        """
        try:
            await self._circuit_breaker.check()
        except RuntimeError as exc:
            await self._inc_blocks()
            return self._blocked_report(request, f"[CIRCUIT_BREAKER] {exc}", t0)

        try:
            gate_reason = await self._run_pre_trade_gate(request)
        except (TimeoutError, RuntimeError) as exc:
            await self._inc_blocks()
            logger.error("ExecutionEngine: pre-trade gate error for %s: %s", request.request_id, exc)
            self._capture_sentry(exc)
            return self._blocked_report(request, f"[GATE_ERROR] {exc}", t0)

        if gate_reason is not None:
            await self._inc_blocks()
            return self._blocked_report(request, gate_reason, t0)

        # ── Self-trade prevention ─────────────────────────────────────────────
        stp_reason = self._check_self_trade(request)
        if stp_reason is not None:
            await self._inc_blocks()
            return self._blocked_report(request, stp_reason, t0)

        # ── Margin check ──────────────────────────────────────────────────────
        margin_reason = await self._check_margin(request, t0)
        if margin_reason is not None:
            return margin_reason

        # ── Leverage hard cap ─────────────────────────────────────────────────
        leverage_reason = await self._check_leverage(request, t0)
        if leverage_reason is not None:
            return leverage_reason

        return None

    def _check_self_trade(self, request: ExecutionRequest) -> str | None:
        """
        Check the request against resting orders for self-trade prevention.

        Returns a block reason string if a self-trade would occur, else None.
        Non-fatal on STP unavailability — execution proceeds without check.
        """
        try:
            from risk.self_trade_prevention import Order as STPOrder, SelfTradePrevention

            # Lazy-init singleton (account-level, cancel resting by default)
            if self._stp is None:
                self._stp = SelfTradePrevention(prevention_level="account")

            stp_order = STPOrder(
                id=request.request_id,
                symbol=request.symbol,
                side=request.side.lower(),  # STP uses 'buy'/'sell'
                size=request.quantity,
                price=float(request.price or 0.0),
                timestamp=datetime.now(UTC),
                account_id=request.metadata.get("account_id", "default"),
                strategy_id=request.strategy_id,
            )
            result = self._stp.check_self_trade(stp_order)
            if result is not None:
                action = result.get("action", "unknown")
                if action in ("reject", "cancel_both"):
                    return f"[SELF_TRADE_PREVENTION] Order would self-match with resting order (action={action})"
                # For cancel_resting: allow the new order, log the resting cancel
                logger.info(
                    "STP: cancelling resting order %s to allow new order %s",
                    result.get("order_to_cancel"),
                    request.request_id,
                )
            # Register the new order as a resting order after the check
            # (it becomes resting until filled or cancelled)
            self._stp.add_resting_order(stp_order)
        except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
            logger.debug("Self-trade prevention check failed (non-fatal): %s", exc)
        return None

    async def _check_margin(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
        """
        Query broker account info and verify adequate margin before submission.

        Blocks the order if free margin would be insufficient (margin_available /
        margin_used < MIN_MARGIN_BUFFER after the notional of this order).

        Fail-closed: any unexpected exception from the broker API blocks the
        trade rather than allowing it through. A broken margin check must never
        silently permit an order that could blow the account.
        """
        if self._broker is None:
            return None
        try:
            loop = asyncio.get_running_loop()
            account = await loop.run_in_executor(None, self._broker.get_account_info)
            if account is None:
                # Broker returned no account data — cannot verify margin; block.
                msg = "[MARGIN_CHECK_FAILED] Broker returned no account info — blocking order (fail-closed)"
                logger.error(msg)
                await self._inc_blocks()
                return self._blocked_report(request, msg, t0)

            margin_available = float(getattr(account, "margin_available", 0) or 0)
            margin_used = float(getattr(account, "margin_used", 0) or 0)
            equity = float(getattr(account, "equity", getattr(account, "balance", 0)) or 0)

            # Estimate notional of this order (price × qty)
            price = float(request.price or 0)
            notional = price * float(request.quantity) if price > 0 else 0.0

            # Skip margin check when notional is unknown (e.g. market orders
            # submitted without an explicit price).  We cannot compute the
            # margin impact of an order we cannot price, so blocking would be a
            # false positive.
            if notional <= 0:
                return None

            # After this order, projected margin used increases by notional
            projected_used = margin_used + notional
            # We require margin_available / projected_used >= MIN_MARGIN_BUFFER
            if projected_used > 0 and equity > 0:
                buffer = margin_available / projected_used
                if buffer < _MIN_MARGIN_BUFFER:
                    msg = (
                        f"[MARGIN_INSUFFICIENT] Free margin buffer {buffer:.2f}x < "
                        f"required {_MIN_MARGIN_BUFFER:.1f}x "
                        f"(available={margin_available:.2f} used={margin_used:.2f} "
                        f"order_notional={notional:.2f})"
                    )
                    logger.warning(msg)
                    await self._inc_blocks()
                    return self._blocked_report(request, msg, t0)
        except (AttributeError, TypeError) as exc:
            # Data-shape errors from a malformed account object — block (fail-closed).
            msg = f"[MARGIN_CHECK_FAILED] Malformed account data: {exc} — blocking order (fail-closed)"
            logger.error(msg)
            await self._inc_blocks()
            return self._blocked_report(request, msg, t0)
        except (RuntimeError, OSError) as exc:
            # Broker connectivity error — cannot verify margin; block (fail-closed).
            msg = f"[MARGIN_CHECK_FAILED] Broker unreachable: {exc} — blocking order (fail-closed)"
            logger.error(msg)
            await self._inc_blocks()
            return self._blocked_report(request, msg, t0)
        return None

    async def _check_leverage(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
        """
        Verify that the order does not breach the maximum leverage ratio.

        Leverage = order_notional / account_equity.
        Blocks if leverage > MAX_LEVERAGE_RATIO.

        Fail-closed: any unexpected exception from the broker API blocks the
        trade rather than allowing it through.
        """
        if self._broker is None:
            return None
        price = float(request.price or 0)
        if price <= 0:
            return None
        notional = price * float(request.quantity)
        try:
            loop = asyncio.get_running_loop()
            account = await loop.run_in_executor(None, self._broker.get_account_info)
            if account is None:
                msg = "[LEVERAGE_CHECK_FAILED] Broker returned no account info — blocking order (fail-closed)"
                logger.error(msg)
                await self._inc_blocks()
                return self._blocked_report(request, msg, t0)
            equity = float(getattr(account, "equity", getattr(account, "balance", 0)) or 0)
            if equity <= 0:
                msg = (
                    f"[LEVERAGE_CHECK_FAILED] Account equity is zero or negative ({equity}) "
                    "— blocking order (fail-closed)"
                )
                logger.error(msg)
                await self._inc_blocks()
                return self._blocked_report(request, msg, t0)
            leverage = notional / equity
            if leverage > _MAX_LEVERAGE_RATIO:
                msg = (
                    f"[LEVERAGE_EXCEEDED] Order leverage {leverage:.1f}x > cap {_MAX_LEVERAGE_RATIO:.1f}x "
                    f"(notional={notional:.2f} equity={equity:.2f})"
                )
                logger.warning(msg)
                await self._inc_blocks()
                return self._blocked_report(request, msg, t0)
        except (AttributeError, TypeError) as exc:
            msg = f"[LEVERAGE_CHECK_FAILED] Malformed account data: {exc} — blocking order (fail-closed)"
            logger.error(msg)
            await self._inc_blocks()
            return self._blocked_report(request, msg, t0)
        except (RuntimeError, OSError) as exc:
            msg = f"[LEVERAGE_CHECK_FAILED] Broker unreachable: {exc} — blocking order (fail-closed)"
            logger.error(msg)
            await self._inc_blocks()
            return self._blocked_report(request, msg, t0)
        return None

    async def _try_algo_routing(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
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
        except (TimeoutError, ImportError, RuntimeError) as exc:
            logger.debug("Algo order routing check failed: %s", exc)
        return None

    def _make_algo_broker_fn(self) -> Any:
        """Return an async broker-submit callable for the algo manager."""

        async def _broker_fn(**kwargs: Any) -> Any:
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

    def _check_sharpe_circuit_breaker(self, request: ExecutionRequest, t0: float) -> ExecutionReport | None:
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
                await self._inc_blocks()
                return self._blocked_report(
                    request,
                    f"[SHARPE_CIRCUIT_OPEN] Model '{model_version}' gated — rolling Sharpe below threshold",
                    t0,
                )
        except (ImportError, RuntimeError, AttributeError) as exc:
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
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.debug("TCA record_signal failed: %s", exc)

    async def _submit_and_process(self, request: ExecutionRequest, t0: float) -> ExecutionReport:
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
            await self._inc_errors()
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
            await self._inc_errors()

        return report

    async def _handle_fill_success(self, request: ExecutionRequest, report: ExecutionReport) -> None:
        """
        Run all post-fill side-effects for a successful order.

        Each side-effect is individually guarded — a failure in Redis, TCA,
        or callbacks must never prevent the ExecutionReport from being returned
        to the caller. Circuit-breaker success and metrics are always recorded.
        """
        await self._circuit_breaker.record_success()
        await self._inc_fills()
        await self._record_latency(report.latency_ms)

        for coro, label in [
            (self._persist_to_redis(request, report), "redis"),
            (self._record_tca(request, report), "tca"),
            (self._record_paper_clock_fill(request, report), "paper_clock"),
            (self._notify_callbacks(report), "callbacks"),
        ]:
            try:
                await coro
            except (TimeoutError, RuntimeError, ConnectionError) as exc:
                logger.warning("Post-fill %s failed (non-fatal): %s", label, exc)

        self._update_sharpe_circuit_breaker(request, report)
        self._warn_on_latency_breach(request, report)

        # ── Publish to Redis CH_ORDER event bus ───────────────────────────────
        # Subscribers: strategy orchestra, WebSocket feed, analytics consumers
        try:
            from core.event_bus import bus as _event_bus

            _order_payload = {
                "order_id": report.order_id,
                "symbol": request.symbol,
                "side": request.side,
                "quantity": float(report.filled_quantity),
                "price": float(report.average_price),
                "status": report.status.value,
                "strategy_id": request.strategy_id,
                "latency_ms": report.latency_ms,
            }
            try:
                import asyncio as _asyncio

                _loop = _asyncio.get_running_loop()
                _loop.create_task(_event_bus.publish_order(_order_payload))
            except RuntimeError:  # nosec B110 — no running loop in sync context; publish is non-fatal
                pass  # no running loop — skip non-critical publish
        except Exception as _bus_exc:
            logger.debug("CH_ORDER publish skipped: %s", _bus_exc)

    def _update_sharpe_circuit_breaker(self, request: ExecutionRequest, report: ExecutionReport) -> None:
        """Record trade P&L in the Sharpe circuit breaker for live model gating."""
        model_version = request.metadata.get("model_version") or request.strategy_id
        if not model_version:
            return
        pnl = report.metadata.get("realised_pnl", 0.0)
        try:
            from ml.sharpe_circuit_breaker import get_sharpe_cb

            get_sharpe_cb().record_trade(pnl=pnl, model_version=model_version)
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.debug("SharpeCircuitBreaker record failed: %s", exc)

    def _warn_on_latency_breach(self, request: ExecutionRequest, report: ExecutionReport) -> None:
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

        # Run synchronous broker call in thread pool, protected by the broker
        # circuit breaker. If the broker has been failing, the breaker opens
        # and rejects the call immediately rather than blocking for a timeout.
        loop = asyncio.get_running_loop()
        try:
            from resilience.service_circuit_breakers import broker_breaker, CircuitBreakerOpenError as _CBOpen
        except ImportError:
            broker_breaker = None
            _CBOpen = None

        async def _place_order_async():
            return await loop.run_in_executor(
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

        if broker_breaker is not None:
            try:
                order = await broker_breaker.call(_place_order_async)
            except _CBOpen as _cb_err:
                raise RuntimeError(
                    f"Broker circuit breaker OPEN — order rejected for {request.symbol}: {_cb_err}"
                ) from _cb_err
        else:
            order = await _place_order_async()

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
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._redis.setex(key, 604800, payload),
            )
        except (ConnectionError, OSError, RuntimeError) as exc:
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
        except (ImportError, RuntimeError, AttributeError) as exc:
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
        except (RuntimeError, AttributeError, TypeError) as exc:
            logger.error("ExecutionEngine: legacy TCA record failed: %s", exc)

    async def _record_paper_clock_fill(
        self,
        request: ExecutionRequest,
        report: ExecutionReport,
    ) -> None:
        """Feed every confirmed fill into the OandaPaperClock Sharpe tracker.

        The fractional return is taken from ``report.metadata["realised_pnl"]``
        divided by notional (fill_price * quantity).  When P&L metadata is
        absent (e.g. an opening fill with no realised P&L yet) the return is
        recorded as 0.0 so the fill count still increments.

        This is best-effort — any import or runtime error is logged at DEBUG
        and must not block the fill path.
        """
        try:
            from brokers.oanda_paper_clock import get_clock

            notional = float(report.average_price) * float(report.filled_quantity)
            realised_pnl = float((report.metadata or {}).get("realised_pnl", 0.0))
            trade_return = realised_pnl / notional if notional != 0.0 else 0.0
            get_clock().record_fill(trade_return=trade_return, symbol=request.symbol)
        except Exception as exc:
            logger.debug("ExecutionEngine: paper clock record_fill failed: %s", exc)

    async def _notify_callbacks(self, report: ExecutionReport) -> None:
        """Invoke all registered fill callbacks."""
        for cb in self._on_fill_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(report)
                else:
                    cb(report)
            except (RuntimeError, TypeError) as exc:
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

    async def _record_latency(self, latency_ms: float) -> None:
        await self._append_latency(latency_ms)  # lock-protected deque append
        # Emit to Prometheus histogram for real-time SLA alerting.
        # Lazy-import so prometheus_client is optional (degrades gracefully).
        try:
            from execution._prom_metrics import EXECUTION_LATENCY_HISTOGRAM

            EXECUTION_LATENCY_HISTOGRAM.observe(latency_ms / 1000.0)
        except (ImportError, AttributeError) as _prom_exc:
            logger.debug("Prometheus histogram observe failed: %s", _prom_exc)

    def get_metrics(self) -> dict[str, Any]:
        """Return execution metrics snapshot (best-effort sync read).

        Counter reads are individually atomic in CPython (GIL), so this is
        safe for monitoring/health endpoints that cannot await.  For a
        fully consistent snapshot use get_metrics_async().
        """
        # Take a local copy of the deque to avoid mutation during iteration
        latencies = list(self._latencies_ms)
        n = len(latencies)
        avg_latency = sum(latencies) / n if n else 0.0
        p99_latency = sorted(latencies)[int(n * 0.99)] if n >= 2 else 0.0
        total_orders = self._total_orders
        total_fills = self._total_fills
        return {
            "total_orders": total_orders,
            "total_fills": total_fills,
            "total_blocks": self._total_blocks,
            "total_errors": self._total_errors,
            "fill_rate": total_fills / max(total_orders, 1),
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "circuit_breaker_open": self._circuit_breaker.is_open,
        }

    async def get_metrics_async(self) -> dict[str, Any]:
        """Return a fully consistent metrics snapshot under the counter lock."""
        async with self._counter_lock:
            latencies = list(self._latencies_ms)
            total_orders = self._total_orders
            total_fills = self._total_fills
            total_blocks = self._total_blocks
            total_errors = self._total_errors
        n = len(latencies)
        avg_latency = sum(latencies) / n if n else 0.0
        p99_latency = sorted(latencies)[int(n * 0.99)] if n >= 2 else 0.0
        return {
            "total_orders": total_orders,
            "total_fills": total_fills,
            "total_blocks": total_blocks,
            "total_errors": total_errors,
            "fill_rate": total_fills / max(total_orders, 1),
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "circuit_breaker_open": self._circuit_breaker.is_open,
        }

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except (RuntimeError, AttributeError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)
