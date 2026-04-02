# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
strategy/engine.py
==================
Event-driven ML signal engine.

Flow
----
  hopefx:tick  →  OHLCV buffer  →  AdvancedModelPredictor.predict_signal()
               →  abstain if confidence < ML_MIN_TRADE_PROB
               →  publish signal_event to hopefx:signal

ML integration
--------------
Uses ml.live_inference.AdvancedModelPredictor (advanced_oos.pkl — 122-feature
XGBoost pipeline, ~68% OOS accuracy on XAUUSD H1). Requires at least 100 bars
of OHLCV history to produce reliable features.

Falls back to EMA-crossover rule when:
  - advanced_oos.pkl is not present (run ml/run_training.py first)
  - fewer than MIN_BARS ticks have accumulated
  - the predictor raises an exception

Abstain logic
-------------
Signals are suppressed when model confidence < ML_MIN_TRADE_PROB (default 0.58).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import pandas as pd

from core.event_bus import bus, CH_TICK

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
ML_MIN_PROB: float = float(os.environ.get("ML_MIN_TRADE_PROB", "0.58"))
MIN_BARS: int = int(os.environ.get("STRATEGY_MIN_BARS", "100"))
BUFFER_SIZE: int = int(os.environ.get("STRATEGY_BUFFER_SIZE", "500"))
EMA_FAST: int = int(os.environ.get("STRATEGY_EMA_FAST", "9"))
EMA_SLOW: int = int(os.environ.get("STRATEGY_EMA_SLOW", "21"))
HEARTBEAT_INTERVAL: int = int(os.environ.get("STRATEGY_HEARTBEAT_TICKS", "100"))
# Aggregate N ticks into one synthetic OHLCV bar
TICKS_PER_BAR: int = int(os.environ.get("STRATEGY_TICKS_PER_BAR", "10"))


# ─────────────────────────────────────────────────────────────────────────────
# Tick → OHLCV aggregator
# ─────────────────────────────────────────────────────────────────────────────


class _OHLCVBuffer:
    """
    Aggregates raw ticks into synthetic OHLCV bars.

    Every TICKS_PER_BAR ticks are collapsed into one bar so the ML model
    receives a proper OHLCV DataFrame rather than raw bid/ask ticks.
    Also maintains EMA-fast/slow for the fallback rule.
    """

    def __init__(self, maxbars: int = BUFFER_SIZE) -> None:
        self._bars: deque[dict] = deque(maxlen=maxbars)
        self._pending: list = []
        self._ema_f: float | None = None
        self._ema_s: float | None = None
        self._alpha_f: float = 2 / (EMA_FAST + 1)
        self._alpha_s: float = 2 / (EMA_SLOW + 1)

    def push(self, mid: float, spread: float, timestamp: str) -> bool:
        """Add one tick. Returns True when a new bar is completed."""
        self._pending.append(mid)

        # Update EMAs on every tick
        if self._ema_f is None:
            self._ema_f = mid
            self._ema_s = mid
        else:
            self._ema_f = self._alpha_f * mid + (1 - self._alpha_f) * self._ema_f
            self._ema_s = self._alpha_s * mid + (1 - self._alpha_s) * self._ema_s

        if len(self._pending) >= TICKS_PER_BAR:
            prices = self._pending
            self._bars.append(
                {
                    "open": prices[0],
                    "high": max(prices),
                    "low": min(prices),
                    "close": prices[-1],
                    "volume": float(len(prices)),
                    "timestamp": timestamp,
                }
            )
            self._pending = []
            return True
        return False

    def ready(self) -> bool:
        """True when enough bars have accumulated for ML inference."""
        return len(self._bars) >= MIN_BARS

    def to_dataframe(self) -> pd.DataFrame:
        """Return bar buffer as a DataFrame for AdvancedModelPredictor."""
        df = pd.DataFrame(list(self._bars))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        return df[["open", "high", "low", "close", "volume"]]

    @property
    def ema_cross(self) -> float:
        """EMA-fast minus EMA-slow (positive = bullish)."""
        if self._ema_f is None or self._ema_s is None:
            return 0.0
        return self._ema_f - self._ema_s

    @property
    def bar_count(self) -> int:
        return len(self._bars)


# ─────────────────────────────────────────────────────────────────────────────
# ML predictor wrapper
# ─────────────────────────────────────────────────────────────────────────────


class _MLPredictor:
    """
    Wraps AdvancedModelPredictor (advanced_oos.pkl) for live inference.

    Accepts an OHLCV DataFrame and returns (direction, confidence).
    Falls back to EMA-crossover when the model is unavailable or the
    buffer has fewer than MIN_BARS bars.
    """

    def __init__(self) -> None:
        self._predictor: Any | None = None
        self._available: bool = False
        self._load()

    def _load(self) -> None:
        try:
            from ml.live_inference import get_advanced_predictor

            self._predictor = get_advanced_predictor()
            self._available = self._predictor is not None and self._predictor.is_available
            if self._available:
                logger.info(
                    "StrategyEngine: AdvancedModelPredictor loaded (version=%s).",
                    self._predictor.version,
                )
            else:
                logger.warning(
                    "StrategyEngine: advanced_oos.pkl not found — "
                    "run `python ml/run_training.py` to train. EMA fallback active."
                )
        except Exception as exc:
            logger.warning(
                "StrategyEngine: ML predictor unavailable (%s) — EMA fallback active.",
                exc,
            )
            self._available = False

    def predict(self, ohlcv_df: pd.DataFrame, ema_cross: float, symbol: str) -> tuple[str, float]:
        """
        Return (direction, confidence).

        direction : 'BUY' | 'SELL' | 'HOLD'
        confidence: float in [0, 1]

        The ML model (advanced_oos.pkl) was trained on daily bars.  When the
        buffer contains intraday bars (tick-aggregated), they are resampled to
        daily before inference so the model's feature windows and calibration
        thresholds remain valid.  The EMA fallback always uses the raw intraday
        buffer so it remains responsive to short-term price action.
        """
        if self._available and len(ohlcv_df) >= MIN_BARS:
            try:
                # Resample intraday bars to daily for the ML model
                model_df = ohlcv_df
                try:
                    from ml.daily_aggregator import ensure_daily, needs_resampling

                    if needs_resampling(ohlcv_df):
                        resampled = ensure_daily(ohlcv_df, min_bars=MIN_BARS)
                        if resampled is not None:
                            model_df = resampled
                            logger.debug(
                                "StrategyEngine: resampled %d intraday → %d daily bars",
                                len(ohlcv_df),
                                len(model_df),
                            )
                        else:
                            # Not enough daily bars yet — use EMA fallback
                            logger.debug("StrategyEngine: insufficient daily bars after resampling — EMA fallback")
                            model_df = None
                except Exception as _re:
                    logger.debug("StrategyEngine: resampling skipped: %s", _re)

                if model_df is not None:
                    result = self._predictor.predict_signal(
                        model_df,
                        symbol=symbol.replace("/", ""),
                        threshold_long=ML_MIN_PROB,
                        threshold_short=1.0 - ML_MIN_PROB,
                    )
                    raw_dir = result.get("direction", "neutral").lower()
                    confidence = float(result.get("confidence", 0.0))

                    if raw_dir == "long":
                        return "BUY", confidence
                    if raw_dir == "short":
                        return "SELL", confidence
                    return "HOLD", confidence

            except Exception as exc:
                logger.warning("StrategyEngine: ML predict error (%s) — EMA fallback.", exc)

        # EMA-crossover fallback
        if ema_cross > 0:
            return "BUY", 0.60
        if ema_cross < 0:
            return "SELL", 0.60
        return "HOLD", 0.50


# ─────────────────────────────────────────────────────────────────────────────
# Strategy engine
# ─────────────────────────────────────────────────────────────────────────────


class StrategyEngine:
    """
    Subscribes to tick events, runs ML inference on bar close,
    publishes signal events.

    Usage
    -----
    engine = StrategyEngine()
    await engine.start()   # runs until cancelled
    """

    def __init__(self) -> None:
        self._buffer = _OHLCVBuffer()
        self._predictor = _MLPredictor()
        self._tick_count: int = 0
        self._bar_count: int = 0
        self._signal_count: int = 0
        self._abstain_count: int = 0
        self._running: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to EventBus and begin consuming ticks."""
        self._running = True
        logger.info(
            "StrategyEngine starting — min_bars=%d ticks_per_bar=%d min_prob=%.2f",
            MIN_BARS,
            TICKS_PER_BAR,
            ML_MIN_PROB,
        )
        await self._consume()

    async def stop(self) -> None:
        self._running = False
        logger.info(
            "StrategyEngine stopped. ticks=%d bars=%d signals=%d abstains=%d",
            self._tick_count,
            self._bar_count,
            self._signal_count,
            self._abstain_count,
        )

    # ── tick consumer ─────────────────────────────────────────────────────────

    async def _consume(self) -> None:
        async for msg in bus.subscribe(CH_TICK):
            if not self._running:
                break
            try:
                await self._on_tick(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("StrategyEngine tick error: %s", exc)

    async def _on_tick(self, tick: dict) -> None:
        """Process one tick: update OHLCV buffer, predict on bar close."""
        mid = float(tick.get("mid", 0))
        spread = float(tick.get("spread", 0))
        symbol = tick.get("symbol", "XAU/USD")
        timestamp = tick.get("timestamp", datetime.now(UTC).isoformat())

        if mid <= 0:
            return

        self._tick_count += 1

        # Heartbeat every N ticks
        if self._tick_count % HEARTBEAT_INTERVAL == 0:
            await bus.publish_signal(
                {
                    "type": "heartbeat",
                    "source": "strategy_engine",
                    "tick_count": self._tick_count,
                    "bar_count": self._buffer.bar_count,
                    "ml_ready": self._buffer.ready(),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        # Push tick; only act on bar close
        bar_closed = self._buffer.push(mid, spread, timestamp)
        if not bar_closed:
            return

        self._bar_count += 1

        # Warm-up: need MIN_BARS before ML inference
        if not self._buffer.ready():
            logger.debug(
                "StrategyEngine: warming up — %d/%d bars",
                self._buffer.bar_count,
                MIN_BARS,
            )
            return

        ohlcv_df = self._buffer.to_dataframe()
        ema_cross = self._buffer.ema_cross
        direction, confidence = self._predictor.predict(ohlcv_df, ema_cross, symbol)

        # Abstain when below threshold or neutral
        if direction == "HOLD" or confidence < ML_MIN_PROB:
            self._abstain_count += 1
            return

        self._signal_count += 1
        signal = {
            "type": "signal_event",
            "symbol": symbol,
            "direction": direction,
            "confidence": round(confidence, 4),
            "mid": mid,
            "spread": spread,
            "bar_count": self._bar_count,
            "tick_seq": tick.get("seq", self._tick_count),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "SIGNAL  %s %s  conf=%.4f  mid=%.5f  bars=%d",
            direction,
            symbol,
            confidence,
            mid,
            self._bar_count,
        )
        await bus.publish_signal(signal)

    # ── metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        return {
            "tick_count": self._tick_count,
            "bar_count": self._bar_count,
            "signal_count": self._signal_count,
            "abstain_count": self._abstain_count,
            "ml_ready": self._buffer.ready(),
            "ml_available": self._predictor._available,
        }
