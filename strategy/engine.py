# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
strategy/engine.py
==================
Event-driven ML signal engine.

Flow
----
  hopefx:tick  →  feature extraction  →  ML predict / abstain  →  hopefx:signal

Design
------
- Subscribes to hopefx:tick via the EventBus.
- Maintains a rolling tick buffer to compute features (mid-price returns,
  spread, EMA-fast/slow, ATR proxy).
- Calls the project's advanced ML predictor (ml.get_advanced_predictor).
  Falls back to a simple EMA-crossover rule when the ML model is unavailable.
- Abstains (no signal) when model confidence < ML_MIN_TRADE_PROB.
- Publishes a signal_event dict to hopefx:signal on every non-abstain tick.
- Publishes a heartbeat to hopefx:signal every HEARTBEAT_INTERVAL ticks
  so downstream modules know the engine is alive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

import numpy as np

from core.event_bus import bus, CH_TICK, CH_SIGNAL

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
ML_MIN_PROB:        float = float(os.environ.get("ML_MIN_TRADE_PROB", "0.58"))
BUFFER_SIZE:        int   = int(os.environ.get("STRATEGY_BUFFER_SIZE", "200"))
EMA_FAST:           int   = int(os.environ.get("STRATEGY_EMA_FAST", "9"))
EMA_SLOW:           int   = int(os.environ.get("STRATEGY_EMA_SLOW", "21"))
HEARTBEAT_INTERVAL: int   = int(os.environ.get("STRATEGY_HEARTBEAT_TICKS", "100"))


# ─────────────────────────────────────────────────────────────────────────────
# Feature extractor
# ─────────────────────────────────────────────────────────────────────────────

class _FeatureBuffer:
    """
    Rolling buffer of mid-prices used to compute inference features.

    Features produced
    -----------------
    - ret_1, ret_5, ret_10   : log-returns over 1, 5, 10 ticks
    - spread                 : current bid-ask spread
    - ema_fast, ema_slow     : exponential moving averages
    - ema_cross              : ema_fast - ema_slow (sign = trend direction)
    - atr_proxy              : mean absolute return over last 14 ticks
    """

    def __init__(self, maxlen: int = BUFFER_SIZE) -> None:
        self._mids:    Deque[float] = deque(maxlen=maxlen)
        self._spreads: Deque[float] = deque(maxlen=maxlen)
        self._ema_f:   Optional[float] = None
        self._ema_s:   Optional[float] = None
        self._alpha_f: float = 2 / (EMA_FAST + 1)
        self._alpha_s: float = 2 / (EMA_SLOW + 1)

    def push(self, mid: float, spread: float) -> None:
        self._mids.append(mid)
        self._spreads.append(spread)
        # Update EMAs
        if self._ema_f is None:
            self._ema_f = mid
            self._ema_s = mid
        else:
            self._ema_f = self._alpha_f * mid + (1 - self._alpha_f) * self._ema_f
            self._ema_s = self._alpha_s * mid + (1 - self._alpha_s) * self._ema_s

    def ready(self) -> bool:
        """True when enough ticks have accumulated for reliable features."""
        return len(self._mids) >= max(EMA_SLOW + 1, 14)

    def features(self) -> Optional[Dict[str, float]]:
        """Return feature dict or None when buffer is not ready."""
        if not self.ready():
            return None

        mids = np.array(self._mids)
        log_rets = np.diff(np.log(mids + 1e-10))

        def _ret(n: int) -> float:
            return float(log_rets[-n:].sum()) if len(log_rets) >= n else 0.0

        atr = float(np.mean(np.abs(log_rets[-14:]))) if len(log_rets) >= 14 else 0.0

        return {
            "ret_1":     _ret(1),
            "ret_5":     _ret(5),
            "ret_10":    _ret(10),
            "spread":    float(self._spreads[-1]),
            "ema_fast":  round(self._ema_f, 5),
            "ema_slow":  round(self._ema_s, 5),
            "ema_cross": round(self._ema_f - self._ema_s, 5),
            "atr_proxy": round(atr, 8),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ML predictor wrapper
# ─────────────────────────────────────────────────────────────────────────────

class _MLPredictor:
    """
    Thin wrapper around the project's advanced ML predictor.

    Falls back to EMA-crossover rule when the model is unavailable.
    """

    def __init__(self) -> None:
        self._predictor = None
        self._available = False
        self._load()

    def _load(self) -> None:
        try:
            from ml import get_advanced_predictor
            self._predictor = get_advanced_predictor()
            self._available = self._predictor is not None
            if self._available:
                logger.info("StrategyEngine: ML predictor loaded.")
            else:
                logger.warning("StrategyEngine: ML predictor returned None — using EMA fallback.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("StrategyEngine: ML predictor unavailable (%s) — using EMA fallback.", exc)
            self._available = False

    def predict(self, features: Dict[str, float]) -> tuple[str, float]:
        """
        Return (direction, confidence).

        direction : 'BUY' | 'SELL' | 'HOLD'
        confidence: float in [0, 1]
        """
        if self._available:
            try:
                result = self._predictor.predict(features)
                # Normalise output — predictor may return dict or tuple
                if isinstance(result, dict):
                    direction  = result.get("direction", "HOLD").upper()
                    confidence = float(result.get("confidence", result.get("probability", 0.5)))
                elif isinstance(result, (list, tuple)) and len(result) >= 2:
                    direction  = str(result[0]).upper()
                    confidence = float(result[1])
                else:
                    direction, confidence = "HOLD", 0.5
                return direction, confidence
            except Exception as exc:  # noqa: BLE001
                logger.warning("ML predict error: %s — falling back to EMA rule.", exc)

        # EMA-crossover fallback
        cross = features.get("ema_cross", 0.0)
        if cross > 0:
            return "BUY", 0.60
        elif cross < 0:
            return "SELL", 0.60
        return "HOLD", 0.50


# ─────────────────────────────────────────────────────────────────────────────
# Strategy engine
# ─────────────────────────────────────────────────────────────────────────────

class StrategyEngine:
    """
    Subscribes to tick events, runs ML inference, publishes signal events.

    Usage
    -----
    engine = StrategyEngine()
    await engine.start()   # runs until cancelled
    """

    def __init__(self) -> None:
        self._buffer    = _FeatureBuffer()
        self._predictor = _MLPredictor()
        self._tick_count: int = 0
        self._signal_count: int = 0
        self._abstain_count: int = 0
        self._running: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to EventBus and begin consuming ticks."""
        self._running = True
        logger.info("StrategyEngine starting — min_prob=%.2f", ML_MIN_PROB)
        await self._consume()

    async def stop(self) -> None:
        self._running = False
        logger.info(
            "StrategyEngine stopped. ticks=%d signals=%d abstains=%d",
            self._tick_count, self._signal_count, self._abstain_count,
        )

    # ── tick consumer ─────────────────────────────────────────────────────────

    async def _consume(self) -> None:
        """Async loop: read ticks from EventBus, produce signals."""
        async for msg in bus.subscribe(CH_TICK):
            if not self._running:
                break
            try:
                await self._on_tick(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("StrategyEngine tick error: %s", exc)

    async def _on_tick(self, tick: dict) -> None:
        """Process one tick: update buffer, predict, maybe publish signal."""
        mid    = float(tick.get("mid", 0))
        spread = float(tick.get("spread", 0))
        symbol = tick.get("symbol", "XAU/USD")

        if mid <= 0:
            return

        self._tick_count += 1
        self._buffer.push(mid, spread)

        # Heartbeat every N ticks so downstream knows engine is alive
        if self._tick_count % HEARTBEAT_INTERVAL == 0:
            await bus.publish_signal({
                "type":       "heartbeat",
                "source":     "strategy_engine",
                "tick_count": self._tick_count,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            })

        features = self._buffer.features()
        if features is None:
            # Buffer not warm yet — abstain silently
            return

        direction, confidence = self._predictor.predict(features)

        # Abstain when confidence is below the minimum threshold
        if direction == "HOLD" or confidence < ML_MIN_PROB:
            self._abstain_count += 1
            return

        self._signal_count += 1
        signal = {
            "type":       "signal_event",
            "symbol":     symbol,
            "direction":  direction,       # 'BUY' or 'SELL'
            "confidence": round(confidence, 4),
            "mid":        mid,
            "spread":     spread,
            "features":   {k: round(v, 6) for k, v in features.items()},
            "tick_seq":   tick.get("seq", self._tick_count),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "SIGNAL  %s %s  conf=%.4f  mid=%.5f",
            direction, symbol, confidence, mid,
        )
        await bus.publish_signal(signal)

    # ── metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        return {
            "tick_count":    self._tick_count,
            "signal_count":  self._signal_count,
            "abstain_count": self._abstain_count,
        }
