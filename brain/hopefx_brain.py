# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brain/hopefx_brain.py
=====================
HOPEFXBrain — centralized intelligence hub.

This is the single class that encapsulates all high-level reasoning:

  1. Multi-timeframe fusion (H1 + H4 + D1 regime context)
  2. ML predictor integration (advanced_oos.pkl via ml.advanced_predictor)
  3. Regime detection (trending / ranging / volatile / unknown)
  4. Dynamic strategy switching (regime → strategy routing)
  5. Agentic reasoning loop (tick → regime → signal → risk gate → order)
  6. Confidence-weighted signal aggregation across strategies
  7. Emergency stop / kill-switch integration

Architecture
------------
                    ┌─────────────────────────────────┐
  price tick ──────►│         HOPEFXBrain              │
                    │                                  │
                    │  1. update_regime(ohlcv)         │
                    │  2. ml_predictor.predict()       │
                    │  3. strategy_router.route()      │
                    │  4. aggregate_signals()          │
                    │  5. risk_gate.check()            │
                    │  6. emit_order / abstain         │
                    └─────────────────────────────────┘

Usage
-----
    from brain.hopefx_brain import HOPEFXBrain

    brain = HOPEFXBrain()
    brain.inject(
        risk_manager=rm,
        broker=broker,
        strategy_manager=sm,
    )

    # On each new bar:
    decision = brain.process_bar(ohlcv_df, symbol="XAU_USD")
    # decision = {
    #   "action": "long" | "short" | "hold",
    #   "confidence": 0.72,
    #   "regime": "trending_up",
    #   "strategy": "smc_ict",
    #   "ml_probability": 0.68,
    #   "reason": "...",
    # }
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

try:
    import numpy as np

    _NP = True
except ImportError:
    _NP = False


# ── Regime ────────────────────────────────────────────────────────────────────


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


# ── Strategy routing table ────────────────────────────────────────────────────
# Maps regime → preferred strategy names (in priority order).
# The brain picks the first available strategy from the list.

_REGIME_STRATEGY_MAP: dict[Regime, list[str]] = {
    Regime.TRENDING_UP: ["smc_ict", "ema_crossover", "ma_crossover", "breakout"],
    Regime.TRENDING_DOWN: [
        "smc_ict",
        "ema_crossover",
        "ma_crossover",
        "mean_reversion",
    ],
    Regime.RANGING: ["mean_reversion", "bollinger_bands", "stochastic", "rsi_strategy"],
    Regime.VOLATILE: ["breakout", "smc_ict", "bollinger_bands"],
    Regime.UNKNOWN: ["smc_ict", "ema_crossover"],
}

# Minimum ML confidence to act on a signal (overridable via env)
_MIN_CONFIDENCE: float = float(os.getenv("BRAIN_MIN_CONFIDENCE", "0.30"))
# Minimum ML probability to generate a long signal
_THRESHOLD_LONG: float = float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58"))
# Maximum ML probability to generate a short signal
_THRESHOLD_SHORT: float = float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42"))
# Weight of ML signal vs strategy signal in final aggregation
_ML_WEIGHT: float = float(os.getenv("BRAIN_ML_WEIGHT", "0.60"))
_STRATEGY_WEIGHT: float = 1.0 - _ML_WEIGHT


# ── Decision dataclass ────────────────────────────────────────────────────────


@dataclass
class BrainDecision:
    """Output of HOPEFXBrain.process_bar()."""

    action: str  # "long" | "short" | "hold"
    confidence: float  # 0.0 – 1.0
    regime: str  # Regime.value
    strategy: str  # strategy name used
    ml_probability: float  # raw ML probability
    ml_confidence: float  # |prob - 0.5| * 2
    ml_abstain: bool  # True if ML abstained
    strategy_signal: str  # raw strategy signal
    strategy_confidence: float  # strategy confidence
    reason: str  # human-readable explanation
    symbol: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "regime": self.regime,
            "strategy": self.strategy,
            "ml_probability": round(self.ml_probability, 4),
            "ml_confidence": round(self.ml_confidence, 4),
            "ml_abstain": self.ml_abstain,
            "strategy_signal": self.strategy_signal,
            "strategy_confidence": round(self.strategy_confidence, 4),
            "reason": self.reason,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "latency_ms": round(self.latency_ms, 2),
        }


# ── HOPEFXBrain ───────────────────────────────────────────────────────────────


class HOPEFXBrain:
    """
    Centralized intelligence hub.

    Thread-safe. All state is protected by a single lock.
    Designed to be called from the main trading loop on each new bar.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._lock = threading.Lock()

        # Injected components (set via inject())
        self._risk_manager = None
        self._broker = None
        self._strategy_manager = None
        self._ml_predictor = None  # lazy-loaded (XGBoost, primary signal)
        self._lstm_layer = None  # lazy-loaded (LSTM, optional secondary signal)

        # Regime state per symbol
        self._regimes: dict[str, Regime] = {}
        self._regime_history: deque = deque(maxlen=200)

        # Decision history
        self._decisions: deque = deque(maxlen=500)

        # MTF context cache: symbol → {d_regime, h4_regime, ...}
        self._mtf_cache: dict[str, dict[str, Any]] = {}
        self._mtf_last_update: dict[str, float] = {}
        _MTF_CACHE_TTL = float(os.getenv("BRAIN_MTF_CACHE_TTL", "300"))  # 5 min
        self._mtf_cache_ttl = _MTF_CACHE_TTL

        # Kill switch
        self._killed: bool = False
        self._kill_reason: str = ""

        # Stats
        self._bar_count: int = 0
        self._signal_count: int = 0
        self._hold_count: int = 0

        logger.info(
            "HOPEFXBrain initialised — ml_weight=%.2f strategy_weight=%.2f min_confidence=%.2f",
            _ML_WEIGHT,
            _STRATEGY_WEIGHT,
            _MIN_CONFIDENCE,
        )

    # ── Dependency injection ──────────────────────────────────────────────────

    def inject(
        self,
        risk_manager=None,
        broker=None,
        strategy_manager=None,
        ml_predictor=None,
        lstm_layer=None,
    ) -> None:
        """
        Inject live components. Call once after construction.

        Parameters
        ----------
        lstm_layer : LSTMSignalLayer | None
            Optional LSTM signal layer. When provided (and
            LSTM_SIGNAL_WEIGHT > 0), its probability is blended with the
            XGBoost probability before direction is determined.
            Pass None to keep the layer disabled (default).
        """
        with self._lock:
            if risk_manager is not None:
                self._risk_manager = risk_manager
            if broker is not None:
                self._broker = broker
            if strategy_manager is not None:
                self._strategy_manager = strategy_manager
            if ml_predictor is not None:
                self._ml_predictor = ml_predictor
            if lstm_layer is not None:
                self._lstm_layer = lstm_layer
        logger.info(
            "HOPEFXBrain.inject: risk=%s broker=%s strategies=%s ml=%s lstm=%s",
            risk_manager is not None,
            broker is not None,
            strategy_manager is not None,
            ml_predictor is not None,
            lstm_layer is not None,
        )

    def _get_predictor(self):
        """Lazy-load the ML predictor singleton."""
        if self._ml_predictor is not None:
            return self._ml_predictor
        try:
            from ml.advanced_predictor import get_predictor

            self._ml_predictor = get_predictor()
            return self._ml_predictor
        except Exception as exc:
            logger.debug("ML predictor load failed: %s", exc)
            return None

    def _get_lstm_layer(self):
        """
        Lazy-load the LSTM signal layer singleton.

        Returns None when:
        - LSTM_SIGNAL_ENABLED feature flag is off (default)
        - LSTM_SIGNAL_WEIGHT == 0.0 (default)
        - Model file does not exist at LSTM_MODEL_PATH
        """
        if self._lstm_layer is not None:
            return self._lstm_layer
        try:
            from config.feature_flags import flags

            if not getattr(flags, "LSTM_SIGNAL_ENABLED", False):
                return None
            from ml.lstm_signal_layer import get_lstm_signal_layer, LSTM_SIGNAL_WEIGHT

            if LSTM_SIGNAL_WEIGHT <= 0.0:
                return None
            self._lstm_layer = get_lstm_signal_layer()
            return self._lstm_layer
        except Exception as exc:
            logger.debug("LSTM signal layer load failed: %s", exc)
            return None

    # ── Kill switch ───────────────────────────────────────────────────────────

    def kill(self, reason: str = "manual") -> None:
        """Activate kill switch — all subsequent process_bar() calls return hold."""
        with self._lock:
            self._killed = True
            self._kill_reason = reason
        logger.critical("HOPEFXBrain KILL SWITCH activated: %s", reason)

    def revive(self) -> None:
        """Deactivate kill switch."""
        with self._lock:
            self._killed = False
            self._kill_reason = ""
        logger.info("HOPEFXBrain kill switch deactivated")

    @property
    def is_killed(self) -> bool:
        return self._killed

    # ── Regime detection ──────────────────────────────────────────────────────

    def detect_regime(
        self,
        ohlcv,  # pd.DataFrame with open/high/low/close/volume
        symbol: str = "XAUUSD",
    ) -> Regime:
        """
        Detect market regime from OHLCV data.

        Uses:
        - Normalized linear regression slope (trend direction + strength)
        - ATR-relative volatility (volatile vs calm)
        - Price range vs ATR ratio (trending vs ranging)

        Returns Regime enum value.
        """
        try:
            if not _NP:
                return Regime.UNKNOWN

            closes = ohlcv["close"].values.astype(float)
            highs = ohlcv["high"].values.astype(float)
            lows = ohlcv["low"].values.astype(float)

            if len(closes) < 20:  # noqa: PLR2004
                return Regime.UNKNOWN

            # ── ATR (14-bar) ──────────────────────────────────────────────────
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(np.maximum(tr1, tr2), tr3)
            atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))  # noqa: PLR2004

            current_price = float(closes[-1])
            if current_price <= 0:
                return Regime.UNKNOWN

            volatility_pct = (atr / current_price) * 100

            # ── Trend (20-bar linear regression slope) ────────────────────────
            window = closes[-20:]
            x = np.arange(len(window), dtype=float)
            slope, _ = np.polyfit(x, window, 1)
            norm_slope = slope / current_price  # normalised to price

            # ── Price range vs ATR ────────────────────────────────────────────
            price_range = float(np.max(highs[-20:]) - np.min(lows[-20:]))
            range_atr_ratio = price_range / atr if atr > 0 else 0

            # ── Classification ────────────────────────────────────────────────
            if volatility_pct > 2.0:  # noqa: PLR2004
                regime = Regime.VOLATILE
            elif abs(norm_slope) > 0.0008 and range_atr_ratio > 3.0:  # noqa: PLR2004
                regime = Regime.TRENDING_UP if norm_slope > 0 else Regime.TRENDING_DOWN
            else:
                regime = Regime.RANGING

            # Track regime changes
            old = self._regimes.get(symbol)
            if old != regime:
                self._regime_history.append(
                    {
                        "symbol": symbol,
                        "from": old.value if old else None,
                        "to": regime.value,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                logger.info(
                    "Regime change [%s]: %s → %s  (slope=%.5f vol=%.2f%%)",
                    symbol,
                    old.value if old else "?",
                    regime.value,
                    norm_slope,
                    volatility_pct,
                )

            with self._lock:
                self._regimes[symbol] = regime

            return regime

        except Exception as exc:
            logger.warning("Regime detection failed for %s: %s", symbol, exc)
            return Regime.UNKNOWN

    # ── MTF fusion ────────────────────────────────────────────────────────────

    def update_mtf_context(
        self,
        symbol: str,
        d1_ohlcv=None,
        h4_ohlcv=None,
    ) -> dict[str, Any]:
        """
        Update multi-timeframe context for a symbol.

        Detects regime on D1 and H4 frames and caches the result.
        Called less frequently than process_bar() (e.g. once per H4 close).

        Returns dict with d1_regime, h4_regime, mtf_alignment.
        """
        now = time.monotonic()
        last = self._mtf_last_update.get(symbol, 0)
        if now - last < self._mtf_cache_ttl and symbol in self._mtf_cache:
            return self._mtf_cache[symbol]

        ctx: dict[str, Any] = {
            "d1_regime": Regime.UNKNOWN.value,
            "h4_regime": Regime.UNKNOWN.value,
            "mtf_alignment": "unknown",
        }

        if d1_ohlcv is not None and len(d1_ohlcv) >= 20:  # noqa: PLR2004
            d1_regime = self.detect_regime(d1_ohlcv, symbol=f"{symbol}_D1")
            ctx["d1_regime"] = d1_regime.value

        if h4_ohlcv is not None and len(h4_ohlcv) >= 20:  # noqa: PLR2004
            h4_regime = self.detect_regime(h4_ohlcv, symbol=f"{symbol}_H4")
            ctx["h4_regime"] = h4_regime.value

        # Alignment: both frames agree on direction
        d1 = ctx["d1_regime"]
        h4 = ctx["h4_regime"]
        if d1 == h4 and d1 not in (Regime.UNKNOWN.value, Regime.RANGING.value):
            ctx["mtf_alignment"] = "aligned_" + d1
        elif d1 == Regime.RANGING.value or h4 == Regime.RANGING.value:
            ctx["mtf_alignment"] = "mixed_ranging"
        else:
            ctx["mtf_alignment"] = "divergent"

        with self._lock:
            self._mtf_cache[symbol] = ctx
            self._mtf_last_update[symbol] = now

        return ctx

    # ── Strategy routing ──────────────────────────────────────────────────────

    def _route_strategy(self, regime: Regime) -> str:
        """
        Select the best available strategy for the current regime.

        Checks strategy_manager for available strategies; falls back to
        the first name in the routing table if manager is not injected.
        """
        candidates = _REGIME_STRATEGY_MAP.get(regime, ["smc_ict"])

        if self._strategy_manager is not None:
            try:
                available = set(getattr(self._strategy_manager, "list_strategies", list)())
                for name in candidates:
                    if name in available:
                        return name
            except Exception as exc:
                logger.debug("Strategy manager query failed: %s", exc)

        return candidates[0] if candidates else "smc_ict"

    def _get_strategy_signal(
        self,
        strategy_name: str,
        ohlcv,
        symbol: str,
    ) -> tuple[str, float]:
        """
        Get signal from the named strategy.

        Returns (direction, confidence) where direction is "long"|"short"|"neutral".
        """
        if self._strategy_manager is None:
            return "neutral", 0.0

        try:
            strategy = getattr(self._strategy_manager, "get_strategy", lambda n: None)(strategy_name)
            if strategy is None:
                return "neutral", 0.0

            # Most strategies expose generate_signal(ohlcv) → dict
            sig = strategy.generate_signal(ohlcv)
            if sig is None:
                return "neutral", 0.0

            direction = str(sig.get("direction", sig.get("signal", "neutral"))).lower()
            if direction in ("buy", "1", "long"):
                direction = "long"
            elif direction in ("sell", "-1", "short"):
                direction = "short"
            else:
                direction = "neutral"

            confidence = float(sig.get("confidence", sig.get("strength", 0.5)))
            return direction, confidence

        except Exception as exc:
            logger.debug("Strategy signal failed [%s]: %s", strategy_name, exc)
            return "neutral", 0.0

    # ── Signal aggregation ────────────────────────────────────────────────────

    def _aggregate_signals(
        self,
        ml_direction: str,
        ml_confidence: float,
        strategy_direction: str,
        strategy_confidence: float,
    ) -> tuple[str, float, str]:
        """
        Weighted aggregation of ML and strategy signals.

        Returns (final_direction, final_confidence, reason).

        Logic:
        - If both agree → high confidence in that direction
        - If ML abstains → use strategy signal at reduced confidence
        - If strategy is neutral → use ML signal at reduced confidence
        - If they disagree → hold (conflicting signals)
        """
        if ml_direction == "neutral" and strategy_direction == "neutral":
            return "hold", 0.0, "both_neutral"

        if ml_direction == "neutral":
            # ML abstained — use strategy at reduced weight
            if strategy_confidence >= _MIN_CONFIDENCE:
                return strategy_direction, strategy_confidence * 0.7, "strategy_only"
            return "hold", 0.0, "strategy_low_confidence"

        if strategy_direction == "neutral":
            # Strategy neutral — use ML at reduced weight
            if ml_confidence >= _MIN_CONFIDENCE:
                return ml_direction, ml_confidence * 0.8, "ml_only"
            return "hold", 0.0, "ml_low_confidence"

        # Both have opinions
        if ml_direction == strategy_direction:
            # Agreement — boost confidence
            combined = min(
                1.0,
                (_ML_WEIGHT * ml_confidence + _STRATEGY_WEIGHT * strategy_confidence) * 1.1,
            )
            return ml_direction, combined, "ml_strategy_agree"

        # Disagreement — hold
        return "hold", 0.0, f"conflict_ml={ml_direction}_str={strategy_direction}"

    # ── Main processing loop ──────────────────────────────────────────────────

    def process_bar(
        self,
        ohlcv,  # pd.DataFrame H1 OHLCV
        symbol: str = "XAUUSD",
        macro_df=None,  # optional macro features
        d1_ohlcv=None,  # optional D1 OHLCV for MTF
        h4_ohlcv=None,  # optional H4 OHLCV for MTF
    ) -> BrainDecision:
        """
        Full intelligence pipeline for one bar.

        1. Kill-switch check
        2. Regime detection (H1)
        3. MTF context update (D1 + H4, cached)
        4. ML predictor inference
        5. Strategy routing + signal
        6. Signal aggregation
        7. Risk gate check
        8. Return BrainDecision

        This method is synchronous and thread-safe.
        """
        t0 = time.perf_counter()
        self._bar_count += 1

        # ── Kill switch ───────────────────────────────────────────────────────
        if self._killed:
            return BrainDecision(
                action="hold",
                confidence=0.0,
                regime=Regime.UNKNOWN.value,
                strategy="none",
                ml_probability=0.5,
                ml_confidence=0.0,
                ml_abstain=True,
                strategy_signal="neutral",
                strategy_confidence=0.0,
                reason=f"kill_switch:{self._kill_reason}",
                symbol=symbol,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Risk-manager halt check ───────────────────────────────────────────
        if self._risk_manager is not None and getattr(self._risk_manager, "_trading_halted", False):
            return BrainDecision(
                action="hold",
                confidence=0.0,
                regime=Regime.UNKNOWN.value,
                strategy="none",
                ml_probability=0.5,
                ml_confidence=0.0,
                ml_abstain=True,
                strategy_signal="neutral",
                strategy_confidence=0.0,
                reason="risk_halted",
                symbol=symbol,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Regime detection ──────────────────────────────────────────────────
        regime = self.detect_regime(ohlcv, symbol=symbol)

        # ── MTF context (cached, non-blocking) ───────────────────────────────
        mtf = self.update_mtf_context(symbol, d1_ohlcv=d1_ohlcv, h4_ohlcv=h4_ohlcv)

        # ── ML predictor ──────────────────────────────────────────────────────
        ml_prob = 0.5
        ml_conf = 0.0
        ml_abstain = True
        ml_direction = "neutral"

        predictor = self._get_predictor()
        if predictor is not None:
            try:
                ml_result = predictor.predict(ohlcv, macro_df=macro_df, symbol=symbol)
                ml_prob = float(ml_result.get("probability", 0.5))
                ml_conf = float(ml_result.get("confidence", 0.0))
                ml_abstain = bool(ml_result.get("abstain", True))
                ml_direction = str(ml_result.get("direction", "neutral"))
            except Exception as exc:
                logger.warning("ML predictor failed for %s: %s", symbol, exc)

        # ── LSTM signal blend (optional) ──────────────────────────────────────
        # When LSTM_SIGNAL_ENABLED=true and LSTM_SIGNAL_WEIGHT > 0, blend the
        # LSTM probability with the XGBoost probability before direction is set.
        # Formula: blended = (1 - w) * xgb_prob + w * lstm_prob
        # The blended probability then re-derives direction, confidence, abstain.
        lstm_layer = self._get_lstm_layer()
        if lstm_layer is not None and lstm_layer.is_available():
            try:
                from ml.lstm_signal_layer import (
                    LSTM_SIGNAL_WEIGHT,
                    LSTM_ABSTAIN_LOW,
                    LSTM_ABSTAIN_HIGH,
                )

                lstm_result = lstm_layer.predict(ohlcv, macro_df=macro_df, symbol=symbol)
                lstm_prob = float(lstm_result.get("probability", 0.5))
                lstm_abstain = bool(lstm_result.get("abstain", True))

                if not lstm_abstain:
                    # Blend probabilities
                    w = float(LSTM_SIGNAL_WEIGHT)
                    blended_prob = (1.0 - w) * ml_prob + w * lstm_prob
                    blended_conf = abs(blended_prob - 0.5) * 2.0
                    blended_abstain = LSTM_ABSTAIN_LOW <= blended_prob <= LSTM_ABSTAIN_HIGH

                    if not blended_abstain:
                        ml_prob = blended_prob
                        ml_conf = blended_conf
                        ml_abstain = False
                        if blended_prob > LSTM_ABSTAIN_HIGH:
                            ml_direction = "long"
                        elif blended_prob < LSTM_ABSTAIN_LOW:
                            ml_direction = "short"
                        else:
                            ml_direction = "neutral"
                            ml_abstain = True
                        logger.debug(
                            "LSTM blend [%s]: xgb=%.3f lstm=%.3f blended=%.3f dir=%s",
                            symbol,
                            ml_prob,
                            lstm_prob,
                            blended_prob,
                            ml_direction,
                        )
            except Exception as exc:
                logger.debug("LSTM blend failed for %s: %s", symbol, exc)

        # ── Strategy routing ──────────────────────────────────────────────────
        strategy_name = self._route_strategy(regime)
        str_direction, str_confidence = self._get_strategy_signal(strategy_name, ohlcv, symbol)

        # ── Signal aggregation ────────────────────────────────────────────────
        final_direction, final_confidence, reason = self._aggregate_signals(
            ml_direction=ml_direction,
            ml_confidence=ml_conf,
            strategy_direction=str_direction,
            strategy_confidence=str_confidence,
        )

        # ── MTF alignment boost/veto ──────────────────────────────────────────
        alignment = mtf.get("mtf_alignment", "unknown")
        if alignment.startswith("aligned_"):
            aligned_dir = alignment.replace("aligned_", "")
            if (aligned_dir == "trending_up" and final_direction == "long") or (
                aligned_dir == "trending_down" and final_direction == "short"
            ):
                final_confidence = min(1.0, final_confidence * 1.15)
                reason += "+mtf_aligned"
        elif alignment == "divergent" and final_direction != "hold":
            # MTF divergence reduces confidence
            final_confidence *= 0.80
            reason += "+mtf_divergent"

        # ── Risk gate ─────────────────────────────────────────────────────────
        if final_direction != "hold" and self._risk_manager is not None:
            try:
                can_trade = True
                if hasattr(self._risk_manager, "_trading_halted"):
                    can_trade = not self._risk_manager._trading_halted
                if not can_trade:
                    final_direction = "hold"
                    reason += "+risk_halted"
            except Exception as exc:
                logger.debug("Risk gate check failed: %s", exc)
                final_direction = "hold"
                reason += "+risk_gate_error"

        # ── Map to action ─────────────────────────────────────────────────────
        action = final_direction if final_direction in ("long", "short") else "hold"

        # ── Record decision ───────────────────────────────────────────────────
        latency_ms = (time.perf_counter() - t0) * 1000
        decision = BrainDecision(
            action=action,
            confidence=round(final_confidence, 4),
            regime=regime.value,
            strategy=strategy_name,
            ml_probability=round(ml_prob, 4),
            ml_confidence=round(ml_conf, 4),
            ml_abstain=ml_abstain,
            strategy_signal=str_direction,
            strategy_confidence=round(str_confidence, 4),
            reason=reason,
            symbol=symbol,
            latency_ms=round(latency_ms, 2),
        )

        with self._lock:
            self._decisions.append(decision.to_dict())
            if action in ("long", "short"):
                self._signal_count += 1
            else:
                self._hold_count += 1

        logger.debug(
            "Brain[%s]: action=%s conf=%.3f regime=%s strategy=%s ml_prob=%.3f reason=%s",
            symbol,
            action,
            final_confidence,
            regime.value,
            strategy_name,
            ml_prob,
            reason,
        )

        return decision

    # ── Stats & introspection ─────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "bar_count": self._bar_count,
            "signal_count": self._signal_count,
            "hold_count": self._hold_count,
            "signal_rate": (self._signal_count / self._bar_count if self._bar_count > 0 else 0.0),
            "regimes": {k: v.value for k, v in self._regimes.items()},
            "killed": self._killed,
            "kill_reason": self._kill_reason,
            "ml_predictor_loaded": self._ml_predictor is not None,
        }

    def recent_decisions(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last n decisions."""
        with self._lock:
            return list(self._decisions)[-n:]

    def regime_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n regime changes."""
        return list(self._regime_history)[-n:]

    def current_regime(self, symbol: str) -> str:
        return self._regimes.get(symbol, Regime.UNKNOWN).value


# ── Module-level singleton ────────────────────────────────────────────────────
_brain: HOPEFXBrain | None = None
_brain_lock = threading.Lock()


def get_brain() -> HOPEFXBrain:
    """Return the module-level HOPEFXBrain singleton (thread-safe)."""
    global _brain
    if _brain is None:
        with _brain_lock:
            if _brain is None:
                _brain = HOPEFXBrain()
    return _brain
