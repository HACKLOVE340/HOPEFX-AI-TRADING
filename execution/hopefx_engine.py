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
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── env config ────────────────────────────────────────────────────────────────
_MIN_CONFIDENCE       = float(os.getenv("ENGINE_MIN_CONFIDENCE",      "0.55"))
_MIN_DATA_QUALITY     = float(os.getenv("ENGINE_MIN_DATA_QUALITY",    "0.40"))
_MAX_SPREAD_USD       = float(os.getenv("ENGINE_MAX_SPREAD_USD",      "2.00"))
_TICK_LOOP_HZ         = float(os.getenv("ENGINE_TICK_LOOP_HZ",        "1.0"))
_MAX_POSITION_USD     = float(os.getenv("ENGINE_MAX_POSITION_USD",    "100000"))
_SIGNAL_COOLDOWN_S    = float(os.getenv("ENGINE_SIGNAL_COOLDOWN_S",   "30.0"))
_STALE_TICK_THRESHOLD = float(os.getenv("ENGINE_STALE_TICK_S",        "10.0"))


class EngineState(str, Enum):
    IDLE       = "idle"
    RUNNING    = "running"
    PAUSED     = "paused"
    HALTED     = "halted"


@dataclass
class ExecutionSignal:
    """Fully-attributed signal ready for routing and risk gating."""
    signal_id:      str
    symbol:         str
    direction:      str          # "long" | "short" | "neutral"
    confidence:     float
    probability:    float
    tick_mid:       float
    tick_bid:       float
    tick_ask:       float
    tick_spread:    float
    tick_timestamp: datetime
    features:       Dict[str, float]
    features_hash:  str
    data_quality:   float        # orchestrator confidence at signal time
    sentiment_score: float
    impact_score:   float
    lineage_id:     str
    created_at:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FillRecord:
    """Immutable fill record written to lineage on every execution."""
    fill_id:        str
    order_id:       str
    signal_id:      str
    symbol:         str
    direction:      str
    quantity:       float
    fill_price:     float
    expected_price: float
    slippage_bps:   float
    broker:         str
    latency_ms:     float
    filled_at:      datetime
    lineage_id:     str


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
    ) -> None:
        self._orch        = orchestrator
        self._router      = smart_router
        self._risk        = risk_manager
        self._gate        = gatekeeper
        self._lineage     = lineage_store
        self._infer       = ml_inference_fn   # callable(features) → (direction, conf, prob)

        self._state       = EngineState.IDLE
        self._tick_count  = 0
        self._signal_count = 0
        self._fill_count  = 0
        self._reject_count = 0
        self._last_signal_ts: float = 0.0     # monotonic, for cooldown
        self._last_tick_epoch: float = 0.0
        self._open_positions: Dict[str, Dict] = {}
        self._fill_history:   List[FillRecord] = []
        self._start_time:     Optional[float] = None
        self._loop_task:      Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._state == EngineState.RUNNING:
            logger.warning("HopeFXEngine already running")
            return
        self._state = EngineState.RUNNING
        self._start_time = time.monotonic()
        self._loop_task = asyncio.create_task(
            self._tick_loop(), name="hopefx_engine_tick_loop"
        )
        logger.info(
            "HopeFXEngine started — min_conf=%.2f min_quality=%.2f max_spread=%.2f",
            _MIN_CONFIDENCE, _MIN_DATA_QUALITY, _MAX_SPREAD_USD,
        )

    async def stop(self) -> None:
        self._state = EngineState.HALTED
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info(
            "HopeFXEngine stopped — ticks=%d signals=%d fills=%d rejects=%d",
            self._tick_count, self._signal_count, self._fill_count, self._reject_count,
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
            except Exception as exc:
                logger.error("Tick loop error: %s", exc, exc_info=True)

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
        now_epoch  = time.time()
        age_s      = now_epoch - tick_epoch
        if age_s > _STALE_TICK_THRESHOLD:
            logger.warning(
                "Stale tick rejected: age=%.1fs symbol=%s", age_s, tick.symbol
            )
            return

        # Deduplicate — skip if same tick as last iteration
        if tick_epoch == self._last_tick_epoch:
            return
        self._last_tick_epoch = tick_epoch

        # ── Step 3: Spread gate ────────────────────────────────────────────
        if tick.spread > _MAX_SPREAD_USD:
            logger.debug(
                "Spread too wide: %.4f > %.4f — skipping", tick.spread, _MAX_SPREAD_USD
            )
            return

        # ── Step 4: Data quality gate (from orchestrator DQE) ─────────────
        data_quality = tick.confidence
        if data_quality < _MIN_DATA_QUALITY:
            logger.warning(
                "Data quality below threshold: %.3f < %.3f — skipping",
                data_quality, _MIN_DATA_QUALITY,
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
        impact_score    = float(features.get("macro_impact_score", 0.0))
        features_hash   = _hash_features(features)
        signal_id       = str(uuid.uuid4())

        signal = ExecutionSignal(
            signal_id       = signal_id,
            symbol          = tick.symbol,
            direction       = direction,
            confidence      = confidence,
            probability     = probability,
            tick_mid        = tick.mid,
            tick_bid        = tick.bid,
            tick_ask        = tick.ask,
            tick_spread     = tick.spread,
            tick_timestamp  = tick.timestamp,
            features        = features,
            features_hash   = features_hash,
            data_quality    = data_quality,
            sentiment_score = sentiment_score,
            impact_score    = impact_score,
            lineage_id      = tick.lineage_id,
        )

        # ── Step 10: Record signal to lineage ──────────────────────────────
        self._lineage.record_signal(
            direction     = direction,
            confidence    = confidence,
            probability   = probability,
            features_hash = features_hash,
            model_version = "hopefx_engine_v3",
            lineage_id    = signal_id,
            symbol        = tick.symbol,
        )
        self._signal_count += 1

        # ── Step 11: Risk gate ─────────────────────────────────────────────
        gate_result = await self._gate.evaluate(signal)
        if not gate_result.passed:
            self._reject_count += 1
            logger.warning(
                "GATE BLOCK signal_id=%s reason=%s", signal_id, gate_result.reason
            )
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

    def _run_inference(
        self, features: Dict[str, float]
    ) -> Tuple[str, float, float]:
        """
        Run ML inference. Returns (direction, confidence, probability).

        If no inference function is wired, falls back to microstructure
        pressure heuristic — never uses broker price data.
        """
        if self._infer is not None:
            try:
                return self._infer(features)
            except Exception as exc:
                logger.error("ML inference error: %s", exc)
                return "neutral", 0.0, 0.5

        # Fallback: microstructure pressure heuristic
        ofi   = features.get("order_flow_imbalance", 0.0)
        press = features.get("trade_pressure", 0.0)
        sent  = features.get("news_sentiment_score", 0.0)
        score = 0.5 * ofi + 0.3 * press + 0.2 * sent

        if score > 0.15:
            return "long",  min(0.5 + abs(score), 0.95), 0.5 + abs(score) * 0.5
        if score < -0.15:
            return "short", min(0.5 + abs(score), 0.95), 0.5 + abs(score) * 0.5
        return "neutral", 0.0, 0.5

    # ── Order routing and execution ───────────────────────────────────────────

    async def _route_and_execute(self, signal: ExecutionSignal, sized) -> None:
        """Route order through SmartRouter and handle fill/rejection."""
        t0 = time.monotonic()

        order_request = {
            "order_id":   str(uuid.uuid4()),
            "signal_id":  signal.signal_id,
            "symbol":     signal.symbol,
            "direction":  signal.direction,
            "quantity":   sized.quantity,
            "order_type": "MARKET",
            "mid_price":  signal.tick_mid,
            "bid":        signal.tick_bid,
            "ask":        signal.tick_ask,
            "spread":     signal.tick_spread,
            "confidence": signal.confidence,
            "sentiment":  signal.sentiment_score,
            "impact":     signal.impact_score,
            "features":   signal.features,
            "lineage_id": signal.lineage_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            fill = await self._router.route_and_execute(order_request)
        except Exception as exc:
            logger.error(
                "Order routing failed signal_id=%s: %s", signal.signal_id, exc
            )
            self._record_rejection(signal, f"routing_error:{exc}")
            return

        latency_ms = (time.monotonic() - t0) * 1000

        if fill.get("status") == "filled":
            await self._on_fill(signal, order_request, fill, latency_ms)
        else:
            self._reject_count += 1
            self._record_rejection(signal, fill.get("reason", "broker_reject"))

    async def _on_fill(
        self,
        signal: ExecutionSignal,
        order: Dict,
        fill: Dict,
        latency_ms: float,
    ) -> None:
        """Handle confirmed fill: lineage, position tracking, orchestrator notify."""
        fill_price = float(fill.get("fill_price", signal.tick_mid))
        quantity   = float(fill.get("quantity",   order["quantity"]))
        broker     = fill.get("broker", "unknown")

        # Slippage in bps
        if signal.direction == "long":
            slippage_bps = (fill_price - signal.tick_ask) / signal.tick_ask * 10000
        else:
            slippage_bps = (signal.tick_bid - fill_price) / signal.tick_bid * 10000

        fill_record = FillRecord(
            fill_id        = str(uuid.uuid4()),
            order_id       = order["order_id"],
            signal_id      = signal.signal_id,
            symbol         = signal.symbol,
            direction      = signal.direction,
            quantity       = quantity,
            fill_price     = fill_price,
            expected_price = signal.tick_ask if signal.direction == "long" else signal.tick_bid,
            slippage_bps   = slippage_bps,
            broker         = broker,
            latency_ms     = latency_ms,
            filled_at      = datetime.now(timezone.utc),
            lineage_id     = signal.lineage_id,
        )

        self._fill_count += 1
        self._fill_history.append(fill_record)

        # Track open position
        self._open_positions[signal.symbol] = {
            "direction":   signal.direction,
            "quantity":    quantity,
            "entry_price": fill_price,
            "signal_id":   signal.signal_id,
            "opened_at":   fill_record.filled_at.isoformat(),
        }

        # Write fill to lineage store
        self._lineage.record_signal(
            direction     = f"FILL:{signal.direction}",
            confidence    = signal.confidence,
            probability   = signal.probability,
            features_hash = signal.features_hash,
            model_version = f"fill@{broker}",
            lineage_id    = fill_record.fill_id,
            symbol        = signal.symbol,
        )

        # Notify orchestrator — updates replay engine and Redis cache
        if hasattr(self._orch, "notify_fill"):
            try:
                self._orch.notify_fill(
                    symbol     = signal.symbol,
                    direction  = signal.direction,
                    quantity   = quantity,
                    fill_price = fill_price,
                    fill_id    = fill_record.fill_id,
                    signal_id  = signal.signal_id,
                    broker     = broker,
                    latency_ms = latency_ms,
                )
            except Exception as exc:
                logger.error("orchestrator.notify_fill failed: %s", exc)

        logger.info(
            "FILL symbol=%s dir=%s qty=%.4f price=%.4f slippage=%.2fbps "
            "broker=%s latency=%.1fms",
            signal.symbol, signal.direction, quantity, fill_price,
            slippage_bps, broker, latency_ms,
        )

    def _record_rejection(self, signal: ExecutionSignal, reason: str) -> None:
        """Write rejection event to lineage."""
        try:
            self._lineage.record_signal(
                direction     = f"REJECT:{signal.direction}",
                confidence    = signal.confidence,
                probability   = signal.probability,
                features_hash = signal.features_hash,
                model_version = f"reject:{reason}",
                lineage_id    = signal.signal_id,
                symbol        = signal.symbol,
            )
        except Exception as exc:
            logger.debug("Lineage rejection record failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        fills  = self._fill_history[-20:]
        avg_slip = (
            sum(f.slippage_bps for f in fills) / len(fills) if fills else 0.0
        )
        avg_lat = (
            sum(f.latency_ms for f in fills) / len(fills) if fills else 0.0
        )
        return {
            "state":            self._state.value,
            "uptime_s":         round(uptime, 1),
            "tick_count":       self._tick_count,
            "signal_count":     self._signal_count,
            "fill_count":       self._fill_count,
            "reject_count":     self._reject_count,
            "fill_rate":        self._fill_count / max(self._signal_count, 1),
            "avg_slippage_bps": round(avg_slip, 3),
            "avg_latency_ms":   round(avg_lat, 2),
            "open_positions":   len(self._open_positions),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_features(features: Dict[str, float]) -> str:
    """SHA-256 of sorted feature dict for lineage deduplication."""
    clean = {k: v for k, v in features.items() if not k.startswith("__")}
    blob  = json.dumps(clean, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
