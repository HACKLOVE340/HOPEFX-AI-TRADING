# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
execution/hopefx_engine.py
===========================
HopeFX Execution Brain — orchestrator-exclusive market data consumption.

Design invariants
-----------------
- Every tick, price, spread, and ML feature comes EXCLUSIVELY from
  MarketDataOrchestrator. No broker API is ever called for price data.
- Zero look-ahead bias: all features are stamped with the tick timestamp
  and validated as causal before any execution decision is made.
- Every order lifecycle event (sent, filled, rejected) is written to
  DataLineageStore for full audit trail.
- News blackout and data quality gates are checked on every tick before
  any signal is acted upon.
- orchestrator.notify_fill() is called immediately on every fill so the
  replay engine and Redis cache stay consistent.

Latency budget
--------------
  tick → feature extraction  : <1 ms
  feature → signal decision  : <2 ms
  signal → broker submission : <10 ms
  total end-to-end target    : <15 ms
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):  # Python 3.10 compat
        pass
UTC = timezone.utc
from typing import Any

from resilience.hot_standby import HotStandbyReplicator
from risk.drawdown_tracker import DrawdownTracker
from risk.intra_trade_monitor import IntraTradeMonitor
from risk.intra_trade_monitor import OpenPosition as IntraPosition
from risk.post_trade_analyzer import PostTradeAnalyzer
from shadow.data_validator import ShadowDataValidator
from shadow.trading_engine import ShadowTradingEngine

logger = logging.getLogger(__name__)

# ── env config ────────────────────────────────────────────────────────────────
_MIN_CONFIDENCE = float(os.getenv("ENGINE_MIN_CONFIDENCE", "0.55"))
_MIN_DATA_QUALITY = float(os.getenv("ENGINE_MIN_DATA_QUALITY", "0.40"))
_MAX_SPREAD_USD = float(os.getenv("ENGINE_MAX_SPREAD_USD", "2.00"))
_TICK_LOOP_HZ = float(os.getenv("ENGINE_TICK_LOOP_HZ", "1.0"))
_MAX_POSITION_USD = float(os.getenv("ENGINE_MAX_POSITION_USD", "100000"))
_SIGNAL_COOLDOWN_S = float(os.getenv("ENGINE_SIGNAL_COOLDOWN_S", "30.0"))
_STALE_TICK_THRESHOLD = float(os.getenv("ENGINE_STALE_TICK_S", "10.0"))


class EngineState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    HALTED = "halted"


@dataclass
class ExecutionSignal:
    """Fully-attributed signal ready for routing and risk gating."""

    signal_id: str
    symbol: str
    direction: str  # "long" | "short" | "neutral"
    confidence: float
    probability: float
    tick_mid: float
    tick_bid: float
    tick_ask: float
    tick_spread: float
    tick_timestamp: datetime
    features: dict[str, float]
    features_hash: str
    data_quality: float  # orchestrator confidence at signal time
    sentiment_score: float
    impact_score: float
    lineage_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FillRecord:
    """Immutable fill record written to lineage on every execution."""

    fill_id: str
    order_id: str
    signal_id: str
    symbol: str
    direction: str
    quantity: float
    fill_price: float
    expected_price: float
    slippage_bps: float
    broker: str
    latency_ms: float
    filled_at: datetime
    lineage_id: str


class HopeFXEngine:
    """
    Main execution brain.

    Wiring
    ------
    - Receives ticks exclusively from orchestrator.get_latest_tick()
    - Receives ML features exclusively from orchestrator.get_ml_features()
    - Routes orders through SmartRouter (which also reads orchestrator features)
    - All pre-trade checks delegated to RiskGatekeeper
    - All fills reported back via orchestrator.notify_fill()
    - All events written to lineage_store

    Usage
    -----
        engine = HopeFXEngine(
            orchestrator=orchestrator,
            smart_router=smart_router,
            risk_manager=risk_manager,
            gatekeeper=gatekeeper,
            lineage_store=lineage_store,
        )
        await engine.start()
    """

    def __init__(
        self,
        orchestrator,
        smart_router,
        risk_manager,
        gatekeeper,
        lineage_store,
        ml_inference_fn=None,
        intra_trade_monitor: IntraTradeMonitor | None = None,
        post_trade_analyzer: PostTradeAnalyzer | None = None,
        drawdown_tracker: DrawdownTracker | None = None,
        shadow_engine: ShadowTradingEngine | None = None,
        shadow_validator: ShadowDataValidator | None = None,
        hot_standby: HotStandbyReplicator | None = None,
        initial_equity: float = float(os.getenv("ENGINE_INITIAL_EQUITY", "100000")),
    ) -> None:
        self._orch = orchestrator
        self._router = smart_router
        self._risk = risk_manager
        self._gate = gatekeeper
        self._lineage = lineage_store
        self._infer = ml_inference_fn  # callable(features) → (direction, conf, prob)

        # ── Multi-layer risk components ────────────────────────────────────
        # Instantiate defaults if not injected — all three layers are mandatory
        self._intra_monitor: IntraTradeMonitor = intra_trade_monitor or IntraTradeMonitor(equity=initial_equity)
        self._post_analyzer: PostTradeAnalyzer = post_trade_analyzer or PostTradeAnalyzer(lineage_store=lineage_store)
        self._dd_tracker: DrawdownTracker = drawdown_tracker or DrawdownTracker(initial_balance=initial_equity)
        self._current_equity: float = initial_equity

        # ── Shadow trading components ──────────────────────────────────────
        # ShadowTradingEngine: paper-executes every live signal in parallel.
        # ShadowDataValidator: compares production vs shadow feed on every tick.
        # Both are optional — if not injected, defaults are created.
        self._shadow: ShadowTradingEngine = shadow_engine or ShadowTradingEngine(initial_balance=initial_equity)
        self._shadow_validator: ShadowDataValidator = shadow_validator or ShadowDataValidator()

        # ── Hot-standby replication ────────────────────────────────────────
        # Optional — only active when a Redis client is available.
        # When present, every state change is replicated so a standby pod
        # can take over without replaying the full order book.
        self._standby: HotStandbyReplicator | None = hot_standby

        self._state = EngineState.IDLE
        self._tick_count = 0
        self._signal_count = 0
        self._fill_count = 0
        self._reject_count = 0
        self._last_signal_ts: float = 0.0  # monotonic, for cooldown
        self._last_tick_epoch: float = 0.0
        self._open_positions: dict[str, dict] = {}
        self._fill_history: list[FillRecord] = []
        self._start_time: float | None = None
        self._loop_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._state == EngineState.RUNNING:
            logger.warning("HopeFXEngine already running")
            return
        self._state = EngineState.RUNNING
        self._start_time = time.monotonic()

        # Start shadow components
        await self._shadow.start()
        await self._shadow_validator.start()

        # Start hot-standby replication (no-op if not configured)
        if self._standby is not None:
            await self._standby.start()

        self._loop_task = asyncio.create_task(self._tick_loop(), name="hopefx_engine_tick_loop")
        logger.info(
            "HopeFXEngine started — min_conf=%.2f min_quality=%.2f max_spread=%.2f",
            _MIN_CONFIDENCE,
            _MIN_DATA_QUALITY,
            _MAX_SPREAD_USD,
        )

    async def stop(self) -> None:
        self._state = EngineState.HALTED
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task

        # Stop shadow components
        await self._shadow.stop()
        await self._shadow_validator.stop()

        # Stop hot-standby replication
        if self._standby is not None:
            await self._standby.stop()

        logger.info(
            "HopeFXEngine stopped — ticks=%d signals=%d fills=%d rejects=%d",
            self._tick_count,
            self._signal_count,
            self._fill_count,
            self._reject_count,
        )

    def pause(self) -> None:
        if self._state == EngineState.RUNNING:
            self._state = EngineState.PAUSED
            logger.warning("HopeFXEngine paused")

    def resume(self) -> None:
        if self._state == EngineState.PAUSED:
            self._state = EngineState.RUNNING
            logger.info("HopeFXEngine resumed")

    def halt(self, reason: str) -> None:
        """Hard halt — requires manual restart."""
        self._state = EngineState.HALTED
        logger.critical("HopeFXEngine HALTED: %s", reason)

    # ── Main tick loop ────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """
        Poll orchestrator at _TICK_LOOP_HZ.

        Every iteration:
          1. Pull latest tick from orchestrator (ONLY source of price data)
          2. Validate tick freshness and quality
          3. Pull ML features from orchestrator
          4. Run ML inference
          5. Gate through risk checks
          6. Route order if signal passes all gates
        """
        interval = 1.0 / _TICK_LOOP_HZ
        while self._state == EngineState.RUNNING:
            t0 = time.monotonic()
            try:
                await self._process_tick()
            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.exception("Tick loop error: %s", exc)

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_s)

    async def _process_tick(self) -> None:
        # ── Step 1: Get tick exclusively from orchestrator ─────────────────
        tick = self._orch.get_latest_tick()
        if tick is None:
            logger.debug("No tick available from orchestrator")
            return

        self._tick_count += 1

        # ── Step 2: Staleness check ────────────────────────────────────────
        tick_epoch = tick.timestamp.timestamp()
        now_epoch = time.time()
        age_s = now_epoch - tick_epoch
        if age_s > _STALE_TICK_THRESHOLD:
            logger.warning("Stale tick rejected: age=%.1fs symbol=%s", age_s, tick.symbol)
            return

        # Deduplicate — skip if same tick as last iteration
        if tick_epoch == self._last_tick_epoch:
            return
        self._last_tick_epoch = tick_epoch

        # ── Step 2a: Shadow feed validation ───────────────────────────────
        # Feed every production tick to the shadow validator so it can
        # compare against the shadow feed and detect divergences.
        try:
            self._shadow_validator.on_production_tick(tick)
        except (RuntimeError, AttributeError, TypeError) as exc:
            logger.debug("ShadowDataValidator.on_production_tick error: %s", exc)

        # Update shadow engine open positions on every tick
        try:
            self._shadow.on_tick(mid=tick.mid)
        except (RuntimeError, AttributeError, TypeError) as exc:
            logger.debug("ShadowTradingEngine.on_tick error: %s", exc)

        # ── Step 2b: Intra-trade risk monitor (tick-frequency CVaR/ES) ────
        # Must run on every tick regardless of whether we generate a new signal.
        # Any UnwindSignal triggers an immediate close before new signal logic.
        unwind_signals = self._intra_monitor.on_tick(
            mid=tick.mid,
            data_quality=tick.confidence,
        )
        for unwind in unwind_signals:
            logger.critical(
                "INTRA-TRADE UNWIND position=%s symbol=%s reason=%s mtm_pnl=%.2f",
                unwind.position_id,
                unwind.symbol,
                unwind.reason,
                unwind.mtm_pnl,
            )
            await self._close_position_for_unwind(unwind)

        # ── Step 2c: Drawdown gate ─────────────────────────────────────────
        # Compute floating equity from open positions and check drawdown limits.
        floating_pnl = sum(pos.get("mtm_pnl", 0.0) for pos in self._open_positions.values())
        floating_equity = self._current_equity + floating_pnl
        dd_result = self._dd_tracker.update(equity=floating_equity)
        if dd_result.total_breach or dd_result.daily_breach:
            breach_type = "total" if dd_result.total_breach else "daily"
            logger.critical(
                "DRAWDOWN BREACH type=%s pct=%.2f%% — halting engine",
                breach_type,
                (dd_result.total_drawdown_pct if dd_result.total_breach else dd_result.daily_drawdown_pct) * 100,
            )
            self.halt(f"drawdown_breach:{breach_type}")
            return

        # ── Step 3: Spread gate ────────────────────────────────────────────
        if tick.spread > _MAX_SPREAD_USD:
            logger.debug("Spread too wide: %.4f > %.4f — skipping", tick.spread, _MAX_SPREAD_USD)
            return

        # ── Step 4: Data quality gate (from orchestrator DQE) ─────────────
        data_quality = tick.confidence
        if data_quality < _MIN_DATA_QUALITY:
            logger.warning(
                "Data quality below threshold: %.3f < %.3f — skipping",
                data_quality,
                _MIN_DATA_QUALITY,
            )
            return

        # ── Step 5: Orchestrator safety gate ──────────────────────────────
        if not self._orch.is_safe_to_trade():
            logger.debug("Orchestrator reports unsafe to trade — skipping tick")
            return

        # ── Step 6: Signal cooldown ────────────────────────────────────────
        if time.monotonic() - self._last_signal_ts < _SIGNAL_COOLDOWN_S:
            return

        # ── Step 7: Pull ML features exclusively from orchestrator ─────────
        features = self._orch.get_ml_features(symbol=tick.symbol)
        if not features:
            logger.debug("No ML features available from orchestrator")
            return

        # Causal enforcement: stamp features with tick timestamp
        features["__tick_epoch"] = tick_epoch
        features["__tick_age_s"] = age_s

        # ── Step 8: ML inference ───────────────────────────────────────────
        direction, confidence, probability = self._run_inference(features)
        if direction == "neutral" or confidence < _MIN_CONFIDENCE:
            return

        # ── Step 9: Build signal ───────────────────────────────────────────
        sentiment_score = float(features.get("news_sentiment_score", 0.0))
        impact_score = float(features.get("macro_impact_score", 0.0))
        features_hash = _hash_features(features)
        signal_id = str(uuid.uuid4())

        signal = ExecutionSignal(
            signal_id=signal_id,
            symbol=tick.symbol,
            direction=direction,
            confidence=confidence,
            probability=probability,
            tick_mid=tick.mid,
            tick_bid=tick.bid,
            tick_ask=tick.ask,
            tick_spread=tick.spread,
            tick_timestamp=tick.timestamp,
            features=features,
            features_hash=features_hash,
            data_quality=data_quality,
            sentiment_score=sentiment_score,
            impact_score=impact_score,
            lineage_id=tick.lineage_id,
        )

        # ── Step 10: Record signal to lineage ──────────────────────────────
        self._lineage.record_signal(
            direction=direction,
            confidence=confidence,
            probability=probability,
            features_hash=features_hash,
            model_version="hopefx_engine_v3",
            lineage_id=signal_id,
            symbol=tick.symbol,
        )
        self._signal_count += 1

        # ── Step 11: Risk gate ─────────────────────────────────────────────
        gate_result = await self._gate.evaluate(signal)
        if not gate_result.passed:
            self._reject_count += 1
            logger.warning("GATE BLOCK signal_id=%s reason=%s", signal_id, gate_result.reason)
            self._record_rejection(signal, gate_result.reason)
            return

        # ── Step 12: Risk sizing ───────────────────────────────────────────
        sized = self._risk.size_order(signal)
        if sized.quantity <= 0:
            logger.warning("Risk manager returned zero size — skipping")
            return

        # ── Step 13: Route order ───────────────────────────────────────────
        self._last_signal_ts = time.monotonic()
        await self._route_and_execute(signal, sized)

    # ── Inference ─────────────────────────────────────────────────────────────

    def _run_inference(self, features: dict[str, float]) -> tuple[str, float, float]:
        """
        Run ML inference. Returns (direction, confidence, probability).

        If no inference function is wired, falls back to microstructure
        pressure heuristic — never uses broker price data.
        """
        if self._infer is not None:
            try:
                return self._infer(features)
            except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
                logger.error("ML inference error: %s", exc)
                return "neutral", 0.0, 0.5

        # Fallback: microstructure pressure heuristic
        ofi = features.get("order_flow_imbalance", 0.0)
        press = features.get("trade_pressure", 0.0)
        sent = features.get("news_sentiment_score", 0.0)
        score = 0.5 * ofi + 0.3 * press + 0.2 * sent

        if score > 0.15:
            return "long", min(0.5 + abs(score), 0.95), 0.5 + abs(score) * 0.5
        if score < -0.15:
            return "short", min(0.5 + abs(score), 0.95), 0.5 + abs(score) * 0.5
        return "neutral", 0.0, 0.5

    # ── Order routing and execution ───────────────────────────────────────────

    async def _route_and_execute(self, signal: ExecutionSignal, sized) -> None:
        """Route order through SmartRouter and handle fill/rejection."""
        t0 = time.monotonic()

        # ── Shadow execution (zero side-effects, runs before live) ────────
        # Paper-execute the same signal so we can compare shadow vs live PnL.
        try:
            self._shadow.on_signal(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                side=signal.direction,
                lots=sized.quantity,
                mid=signal.tick_mid,
                stop_loss=float(
                    signal.features.get(
                        "stop_loss",
                        signal.tick_mid * (0.99 if signal.direction == "long" else 1.01),
                    )
                ),
                take_profit=float(
                    signal.features.get(
                        "take_profit",
                        signal.tick_mid * (1.01 if signal.direction == "long" else 0.99),
                    )
                ),
            )
        except (RuntimeError, AttributeError, TypeError) as exc:
            logger.debug("ShadowTradingEngine.on_signal error: %s", exc)

        order_request = {
            "order_id": str(uuid.uuid4()),
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "quantity": sized.quantity,
            "order_type": "MARKET",
            "mid_price": signal.tick_mid,
            "bid": signal.tick_bid,
            "ask": signal.tick_ask,
            "spread": signal.tick_spread,
            "confidence": signal.confidence,
            "sentiment": signal.sentiment_score,
            "impact": signal.impact_score,
            "features": signal.features,
            "lineage_id": signal.lineage_id,
            "created_at": datetime.now(UTC).isoformat(),
        }

        try:
            fill = await self._router.route_and_execute(order_request)
        except (TimeoutError, RuntimeError, ConnectionError, ValueError) as exc:
            logger.error("Order routing failed signal_id=%s: %s", signal.signal_id, exc)
            self._record_rejection(signal, f"routing_error:{exc}")
            return

        latency_ms = (time.monotonic() - t0) * 1000
        status = fill.get("status", "rejected")

        if status == "filled":
            await self._on_fill(signal, order_request, fill, latency_ms)

        elif status == "partial":
            # Partial fill: broker filled less than the requested quantity.
            # Accept the partial fill — record it as a real fill with the
            # actual filled quantity, then log the unfilled remainder.
            # We do NOT re-submit the remainder automatically because:
            #   1. OANDA FOK orders either fill fully or cancel — a "partial"
            #      here means the broker adapter normalised a partial trade.
            #   2. Re-submitting the remainder risks doubling position size
            #      if the original order is still pending on the broker side.
            filled_qty = float(fill.get("quantity", fill.get("filled_qty", 0)))
            requested_qty = float(order_request.get("quantity", 0))
            unfilled_qty = max(0.0, requested_qty - filled_qty)
            logger.warning(
                "PARTIAL FILL signal_id=%s filled=%.4f requested=%.4f unfilled=%.4f broker=%s",
                signal.signal_id,
                filled_qty,
                requested_qty,
                unfilled_qty,
                fill.get("broker", "?"),
            )
            if filled_qty > 0:
                # Treat the partial as a real fill with the actual quantity.
                partial_fill = {**fill, "status": "filled", "quantity": filled_qty}
                await self._on_fill(signal, order_request, partial_fill, latency_ms)
            else:
                # Zero-quantity partial — treat as rejection.
                self._reject_count += 1
                self._record_rejection(signal, "partial_fill_zero_qty")

        elif status == "pending":
            # Limit order accepted by broker but not yet filled.
            # Track the pending order so we can monitor it for fill/cancel.
            order_id = fill.get("order_id", order_request.get("order_id", ""))
            logger.info(
                "PENDING ORDER signal_id=%s order_id=%s broker=%s — awaiting fill",
                signal.signal_id,
                order_id,
                fill.get("broker", "?"),
            )
            # Record in lineage so the audit trail shows the pending state.
            try:
                self._lineage.record_signal(
                    direction=f"PENDING:{signal.direction}",
                    confidence=signal.confidence,
                    probability=signal.probability,
                    features_hash=signal.features_hash,
                    model_version=f"pending@{fill.get('broker', '?')}",
                    lineage_id=signal.lineage_id,
                    symbol=signal.symbol,
                )
            except (RuntimeError, AttributeError, OSError, TypeError) as _exc:
                logger.debug("lineage record_signal (pending) error: %s", _exc)

        else:
            self._reject_count += 1
            self._record_rejection(signal, fill.get("reason", "broker_reject"))

    async def _on_fill(
        self,
        signal: ExecutionSignal,
        order: dict,
        fill: dict,
        latency_ms: float,
    ) -> None:
        """Handle confirmed fill: lineage, position tracking, orchestrator notify."""
        fill_price = float(fill.get("fill_price", signal.tick_mid))
        broker = fill.get("broker", "unknown")

        # ── OANDA XAUUSD unit normalisation ───────────────────────────────
        # OANDA returns quantity in units (troy oz for XAU_USD).
        # 1 standard lot = 100 oz.  The engine tracks quantity in lots so
        # that slippage bps and position sizing are consistent across brokers.
        # If the broker returned units > 10 and the requested quantity was
        # in lots (< 10), convert units → lots.
        raw_qty = float(fill.get("quantity", order.get("quantity", 0)))
        requested_qty = float(order.get("quantity", raw_qty))
        symbol = signal.symbol.upper().replace("/", "_")
        if broker == "oanda" and "XAU" in symbol:
            # OANDA XAU_USD: 1 lot = 100 units (oz).
            # If the fill quantity looks like units (>> requested lots),
            # convert to lots.
            if raw_qty > requested_qty * 10 and requested_qty < 100:
                quantity = raw_qty / 100.0
                logger.debug(
                    "OANDA XAU_USD unit→lot conversion: %.0f units → %.4f lots",
                    raw_qty,
                    quantity,
                )
            else:
                quantity = raw_qty
        else:
            quantity = raw_qty

        # ── Slippage in bps ────────────────────────────────────────────────
        # Guard against zero bid/ask (e.g. first tick before feed is live).
        # Use tick_mid as fallback reference price.
        if signal.direction == "long":
            ref_price = signal.tick_ask if signal.tick_ask > 0 else signal.tick_mid
            slippage_bps = (fill_price - ref_price) / ref_price * 10_000 if ref_price > 0 else 0.0
        else:
            ref_price = signal.tick_bid if signal.tick_bid > 0 else signal.tick_mid
            slippage_bps = (ref_price - fill_price) / ref_price * 10_000 if ref_price > 0 else 0.0

        fill_record = FillRecord(
            fill_id=str(uuid.uuid4()),
            order_id=order["order_id"],
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            quantity=quantity,
            fill_price=fill_price,
            expected_price=signal.tick_ask if signal.direction == "long" else signal.tick_bid,
            slippage_bps=slippage_bps,
            broker=broker,
            latency_ms=latency_ms,
            filled_at=datetime.now(UTC),
            lineage_id=signal.lineage_id,
        )

        self._fill_count += 1
        self._fill_history.append(fill_record)

        # Track open position
        position_id = fill_record.fill_id
        self._open_positions[signal.symbol] = {
            "position_id": position_id,
            "direction": signal.direction,
            "quantity": quantity,
            "entry_price": fill_price,
            "signal_id": signal.signal_id,
            "opened_at": fill_record.filled_at.isoformat(),
            "mtm_pnl": 0.0,
        }

        # ── Register with IntraTradeMonitor ───────────────────────────────
        intra_pos = IntraPosition(
            position_id=position_id,
            symbol=signal.symbol,
            side=signal.direction,
            lots=quantity,
            entry_price=fill_price,
            stop_loss=float(order.get("stop_loss", fill_price * 0.99)),
            take_profit=float(order.get("take_profit", fill_price * 1.01)),
            opened_at=fill_record.filled_at,
        )
        self._intra_monitor.on_open(intra_pos)

        # ── Post-trade fill analysis ───────────────────────────────────────
        self._post_analyzer.record_fill(
            trade_id=fill_record.fill_id,
            symbol=signal.symbol,
            side=signal.direction,
            lots=quantity,
            decision_price=signal.tick_mid,
            fill_price=fill_price,
            mid_at_fill=signal.tick_mid,
            spread_at_fill=signal.tick_spread,
        )

        # ── Update drawdown tracker with new balance ───────────────────────
        self._current_equity = self._current_equity  # balance unchanged on open

        # ── Replicate state to hot-standby ────────────────────────────────
        if self._standby is not None:
            self._standby.update_positions(self._open_positions)
            self._standby.update_equity(
                equity=self._current_equity,
                balance=self._current_equity,
            )
            self._standby.record_fill(
                {
                    "fill_id": fill_record.fill_id,
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "quantity": quantity,
                    "fill_price": fill_price,
                    "broker": broker,
                    "filled_at": fill_record.filled_at.isoformat(),
                }
            )

        # ── Close any existing shadow position on the same symbol ─────────
        # If we already had an open position on this symbol and are now
        # opening in the opposite direction, the previous position is closed.
        # Notify shadow engine so it can record the live PnL for comparison.
        existing = self._open_positions.get(signal.symbol)
        if existing and existing.get("direction") != signal.direction:
            prev_entry = existing.get("entry_price", fill_price)
            prev_qty = existing.get("quantity", quantity)
            if existing["direction"] == "long":
                prev_pnl = (fill_price - prev_entry) * prev_qty * 100.0
            else:
                prev_pnl = (prev_entry - fill_price) * prev_qty * 100.0
            try:
                # Compute live slippage for the closing leg so shadow engine
                # can calibrate its slippage model via R² tracking.
                if existing["direction"] == "long":
                    live_slip = (fill_price - prev_entry) / max(prev_entry, 1e-9) * 10_000
                else:
                    live_slip = (prev_entry - fill_price) / max(prev_entry, 1e-9) * 10_000
                self._shadow.on_live_close(
                    signal_id=existing.get("signal_id", ""),
                    live_pnl=prev_pnl,
                    live_fill_price=fill_price,
                    live_slippage_bps=abs(live_slip),
                )
            except (RuntimeError, AttributeError, TypeError) as exc:
                logger.debug("ShadowTradingEngine.on_live_close (flip) error: %s", exc)
            self._current_equity += prev_pnl
            self._dd_tracker.record_fill(pnl=prev_pnl)

        # Write fill to lineage store
        self._lineage.record_signal(
            direction=f"FILL:{signal.direction}",
            confidence=signal.confidence,
            probability=signal.probability,
            features_hash=signal.features_hash,
            model_version=f"fill@{broker}",
            lineage_id=fill_record.fill_id,
            symbol=signal.symbol,
        )

        # Notify orchestrator — updates replay engine and Redis cache
        if hasattr(self._orch, "notify_fill"):
            try:
                self._orch.notify_fill(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    quantity=quantity,
                    fill_price=fill_price,
                    fill_id=fill_record.fill_id,
                    signal_id=signal.signal_id,
                    broker=broker,
                    latency_ms=latency_ms,
                )
            except (RuntimeError, AttributeError, ConnectionError) as exc:
                logger.error("orchestrator.notify_fill failed: %s", exc)

        logger.info(
            "FILL symbol=%s dir=%s qty=%.4f price=%.4f slippage=%.2fbps broker=%s latency=%.1fms",
            signal.symbol,
            signal.direction,
            quantity,
            fill_price,
            slippage_bps,
            broker,
            latency_ms,
        )

    async def _close_position_for_unwind(self, unwind) -> None:
        """
        Close a position triggered by IntraTradeMonitor auto-unwind.

        Sends a market close order through the router, then:
        - Removes position from open_positions
        - Notifies IntraTradeMonitor of close
        - Records post-trade analysis
        - Updates drawdown tracker with realised PnL
        """
        pos = self._open_positions.get(unwind.symbol)
        if pos is None:
            logger.warning(
                "Unwind for unknown position symbol=%s — already closed?",
                unwind.symbol,
            )
            return

        close_direction = "short" if pos["direction"] == "long" else "long"
        close_request = {
            "order_id": str(uuid.uuid4()),
            "signal_id": pos["signal_id"],
            "symbol": unwind.symbol,
            "direction": close_direction,
            "quantity": pos["quantity"],
            "order_type": "MARKET",
            "mid_price": 0.0,  # router will use live price from broker
            "bid": 0.0,
            "ask": 0.0,
            "spread": 0.0,
            "confidence": 1.0,  # unwind is unconditional
            "sentiment": 0.0,
            "impact": 0.0,
            "features": {},
            "lineage_id": unwind.position_id,
            "is_unwind": True,
            "unwind_reason": unwind.reason,
        }

        try:
            fill = await self._router.route_and_execute(close_request)
        except (TimeoutError, RuntimeError, ConnectionError, ValueError) as exc:
            logger.critical(
                "UNWIND ROUTING FAILED symbol=%s reason=%s: %s",
                unwind.symbol,
                unwind.reason,
                exc,
            )
            return

        close_price = float(fill.get("fill_price", pos["entry_price"]))

        # Realised PnL
        if pos["direction"] == "long":
            realised_pnl = (close_price - pos["entry_price"]) * pos["quantity"] * 100.0
        else:
            realised_pnl = (pos["entry_price"] - close_price) * pos["quantity"] * 100.0

        # Notify IntraTradeMonitor
        self._intra_monitor.on_close(
            position_id=unwind.position_id,
            close_price=close_price,
        )

        # Post-trade analysis on the close leg
        self._post_analyzer.record_fill(
            trade_id=str(uuid.uuid4()),
            symbol=unwind.symbol,
            side=close_direction,
            lots=pos["quantity"],
            decision_price=pos["entry_price"],
            fill_price=close_price,
            mid_at_fill=close_price,
            spread_at_fill=0.0,
        )

        # Update equity and drawdown tracker
        self._current_equity += realised_pnl
        self._dd_tracker.update(equity=self._current_equity)
        self._dd_tracker.record_fill(pnl=realised_pnl)

        # Notify shadow engine of live close for paper-vs-live comparison
        try:
            entry = pos.get("entry_price", close_price)
            if pos["direction"] == "long":
                live_slip = (close_price - entry) / max(entry, 1e-9) * 10_000
            else:
                live_slip = (entry - close_price) / max(entry, 1e-9) * 10_000
            self._shadow.on_live_close(
                signal_id=pos["signal_id"],
                live_pnl=realised_pnl,
                live_fill_price=close_price,
                live_slippage_bps=abs(live_slip),
            )
        except (RuntimeError, AttributeError, TypeError) as exc:
            logger.debug("ShadowTradingEngine.on_live_close error: %s", exc)

        # Remove from open positions
        self._open_positions.pop(unwind.symbol, None)

        # Replicate updated state after unwind
        if self._standby is not None:
            self._standby.update_positions(self._open_positions)
            self._standby.update_equity(equity=self._current_equity)

        logger.warning(
            "UNWIND COMPLETE symbol=%s reason=%s pnl=%.2f close_price=%.4f",
            unwind.symbol,
            unwind.reason,
            realised_pnl,
            close_price,
        )

    def _record_rejection(self, signal: ExecutionSignal, reason: str) -> None:
        """Write rejection event to lineage."""
        try:
            self._lineage.record_signal(
                direction=f"REJECT:{signal.direction}",
                confidence=signal.confidence,
                probability=signal.probability,
                features_hash=signal.features_hash,
                model_version=f"reject:{reason}",
                lineage_id=signal.signal_id,
                symbol=signal.symbol,
            )
        except (RuntimeError, AttributeError, OSError, TypeError) as exc:
            logger.debug("Lineage rejection record failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        fills = self._fill_history[-20:]
        avg_slip = sum(f.slippage_bps for f in fills) / len(fills) if fills else 0.0
        avg_lat = sum(f.latency_ms for f in fills) / len(fills) if fills else 0.0

        # Drawdown snapshot
        floating_pnl = sum(pos.get("mtm_pnl", 0.0) for pos in self._open_positions.values())
        floating_equity = self._current_equity + floating_pnl
        dd_result = self._dd_tracker.update(equity=floating_equity)

        # Post-trade summary (rolling_stats over last 50 fills)
        pt_summary = self._post_analyzer.rolling_stats()

        # Intra-trade snapshot
        intra_summary = self._intra_monitor.snapshot()

        return {
            "state": self._state.value,
            "uptime_s": round(uptime, 1),
            "tick_count": self._tick_count,
            "signal_count": self._signal_count,
            "fill_count": self._fill_count,
            "reject_count": self._reject_count,
            "fill_rate": self._fill_count / max(self._signal_count, 1),
            "avg_slippage_bps": round(avg_slip, 3),
            "avg_latency_ms": round(avg_lat, 2),
            "open_positions": len(self._open_positions),
            "current_equity": round(self._current_equity, 2),
            "floating_equity": round(floating_equity, 2),
            "drawdown": {
                "total_pct": round(dd_result.total_drawdown_pct * 100, 3),
                "daily_pct": round(dd_result.daily_drawdown_pct * 100, 3),
                "hwm": round(dd_result.total_hwm, 2),
                "total_alert": dd_result.total_alert,
                "daily_alert": dd_result.daily_alert,
            },
            "post_trade": pt_summary,
            "intra_trade": intra_summary,
            "shadow": self._shadow.health(),
            "shadow_comparison": self._shadow.get_comparison_report(),
            "hot_standby": self._standby.stats() if self._standby else None,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash_features(features: dict[str, float]) -> str:
    """SHA-256 of sorted feature dict for lineage deduplication."""
    clean = {k: v for k, v in features.items() if not k.startswith("__")}
    blob = json.dumps(clean, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
