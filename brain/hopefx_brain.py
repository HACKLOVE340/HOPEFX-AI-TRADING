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
from pathlib import Path
from typing import Any

UTC = timezone.utc

ROOT = Path(__file__).parent.parent

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


logger = logging.getLogger(__name__)

try:
    import numpy as np

    _NP = True
except ImportError:
    _NP = False


# ── Regime ────────────────────────────────────────────────────────────────────


class Regime(StrEnum):
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
    tick_mid: float = 0.0  # live mid-price at signal time (used by RiskManager.size_order)

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
            "tick_mid": round(self.tick_mid, 5),
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
        self._edge_selector = None  # AdaptiveEdgeSelector (optional, overrides _route_strategy)

        # Regime state per symbol
        self._regimes: dict[str, Regime] = {}
        self._regime_history: deque = deque(maxlen=200)
        # Thresholds calibrated for XAU/USD H1 (ATR typically 0.3-0.8% of price).
        self._regime_volatile_threshold: float = float(os.getenv("REGIME_VOLATILE_THRESHOLD", "0.8"))
        self._regime_ranging_threshold: float = float(os.getenv("REGIME_RANGING_THRESHOLD", "0.2"))

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

        # ── Horizon hold tracking ──────────────────────────────────────────────
        # When the ML model predicts direction for horizon H bars ahead, hold the
        # position for H bars before accepting a new opposing signal.
        # Read from model metadata; default is 1 (no enforced hold).
        _horizon_default = 1
        try:
            _meta_path = ROOT / "ml" / "saved_models" / "advanced_oos_meta.json"
            if _meta_path.exists():
                import json

                _meta = json.loads(_meta_path.read_text())
                _horizon_default = int(_meta.get("horizon", 1))
        except Exception as _exc:  # non-fatal: fall back to default horizon
            logger.debug("Could not read signal horizon from model metadata: %s", _exc)
        self._signal_horizon: int = int(os.getenv("SIGNAL_HORIZON", str(_horizon_default)))
        # Per-symbol hold countdown: {symbol: bars_remaining}
        self._hold_bars_remaining: dict[str, int] = {}
        self._hold_direction: dict[str, str] = {}  # "long" | "short"

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
        edge_selector=None,
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
        edge_selector : AdaptiveEdgeSelector | None
            Optional edge selector. When provided, its decision overrides
            the default _route_strategy() lookup after regime detection.
            The selected strategy_name is used for signal generation and
            the edge confidence boosts the final aggregated confidence.
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
            if edge_selector is not None:
                self._edge_selector = edge_selector
        logger.info(
            "HOPEFXBrain.inject: risk=%s broker=%s strategies=%s ml=%s lstm=%s edge_selector=%s",
            risk_manager is not None,
            broker is not None,
            strategy_manager is not None,
            ml_predictor is not None,
            lstm_layer is not None,
            edge_selector is not None,
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
            from ml.lstm_signal_layer import LSTM_SIGNAL_WEIGHT, get_lstm_signal_layer

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

            if len(closes) < 20:
                return Regime.UNKNOWN

            # ── ATR (14-bar) ──────────────────────────────────────────────────
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(np.maximum(tr1, tr2), tr3)
            atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))

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
            # Thresholds calibrated for XAU/USD H1: typical ATR is 0.3-0.8% of price.
            # REGIME_VOLATILE_THRESHOLD default 0.8 (was 2.0 — too coarse for gold).
            # REGIME_RANGING_THRESHOLD  default 0.2 (explicit low-volatility ranging).
            if volatility_pct > self._regime_volatile_threshold:
                regime = Regime.VOLATILE
            elif volatility_pct < self._regime_ranging_threshold:
                regime = Regime.RANGING
            elif abs(norm_slope) > 0.0008 and range_atr_ratio > 3.0:
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

        if d1_ohlcv is not None and len(d1_ohlcv) >= 20:
            d1_regime = self.detect_regime(d1_ohlcv, symbol=f"{symbol}_D1")
            ctx["d1_regime"] = d1_regime.value

        if h4_ohlcv is not None and len(h4_ohlcv) >= 20:
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

        Handles two strategy calling conventions:
        1. analyze(ohlcv) → analysis_dict, then generate_signal(analysis_dict)
        2. generate_signal(ohlcv) → dict directly
        """
        if self._strategy_manager is None:
            return "neutral", 0.0

        try:
            strategy = getattr(self._strategy_manager, "get_strategy", lambda n: None)(strategy_name)
            if strategy is None:
                return "neutral", 0.0

            # Detect whether strategy needs analyze() first
            if hasattr(strategy, "analyze"):
                analysis = strategy.analyze(ohlcv)
                sig = strategy.generate_signal(analysis)
            else:
                sig = strategy.generate_signal(ohlcv)

            if sig is None:
                return "neutral", 0.0

            # Normalize result — may be Signal object or dict
            if hasattr(sig, "direction"):
                raw_dir = str(sig.direction).lower()
                confidence = float(getattr(sig, "confidence", 0.5))
            elif hasattr(sig, "signal_type"):
                raw_dir = str(sig.signal_type).lower()
                confidence = float(getattr(sig, "confidence", 0.5))
            elif isinstance(sig, dict):
                raw_dir = str(sig.get("direction", sig.get("signal", sig.get("type", "neutral")))).lower()
                confidence = float(sig.get("confidence", sig.get("strength", 0.5)))
            else:
                return "neutral", 0.0

            # Map all known direction strings to canonical "long"/"short"/"neutral".
            # The 'signaltype.buy/sell' patterns match str(SignalType.BUY/SELL) enum
            # representations, which Python serialises as 'SignalType.BUY' (lowercased).
            if raw_dir in ("buy", "1", "long", "signaltype.buy"):
                direction = "long"
            elif raw_dir in ("sell", "-1", "short", "signaltype.sell"):
                direction = "short"
            else:
                direction = "neutral"

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
                    LSTM_ABSTAIN_HIGH,
                    LSTM_ABSTAIN_LOW,
                    LSTM_SIGNAL_WEIGHT,
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

        # ── HybridEnsemblePredictor blend (XGBoost + LSTM + RL meta-blend) ────
        # When the HybridEnsemblePredictor is available and not abstaining, blend
        # its probability with the current ml_prob at a configurable weight.
        # Default weight is 0.20 (controllable via HYBRID_SIGNAL_WEIGHT env var).
        _hybrid_weight = float(os.getenv("HYBRID_SIGNAL_WEIGHT", "0.20"))
        if _hybrid_weight > 0.0 and not ml_abstain:
            try:
                from ml.advanced_predictor import get_hybrid_predictor
                from ml.features_extended import build_features_extended

                _hybrid = get_hybrid_predictor()
                # Build tabular feature row for XGBoost component
                _feat_df = build_features_extended(ohlcv)
                if _feat_df is not None and not _feat_df.empty:
                    import numpy as np

                    _X = _feat_df.fillna(0.0).values[-1:].astype(np.float32)
                    _hybrid_prob = _hybrid.predict_proba(_X)
                    _hybrid_conf = abs(_hybrid_prob - 0.5) * 2.0
                    # Only blend when hybrid is confident
                    if _hybrid_conf >= 0.10:
                        _blended = (1.0 - _hybrid_weight) * ml_prob + _hybrid_weight * _hybrid_prob
                        ml_prob = float(np.clip(_blended, 0.0, 1.0))
                        ml_conf = abs(ml_prob - 0.5) * 2.0
                        _ABSTAIN_LOW = float(os.getenv("ML_ABSTAIN_LOW", "0.45"))
                        _ABSTAIN_HIGH = float(os.getenv("ML_ABSTAIN_HIGH", "0.55"))
                        if _ABSTAIN_LOW <= ml_prob <= _ABSTAIN_HIGH:
                            ml_direction = "neutral"
                            ml_abstain = True
                        else:
                            ml_direction = "long" if ml_prob > _ABSTAIN_HIGH else "short"
                            ml_abstain = False
                        logger.debug(
                            "HybridEnsemble blend [%s]: base=%.3f hybrid=%.3f blended=%.3f dir=%s",
                            symbol,
                            ml_prob,
                            _hybrid_prob,
                            _blended,
                            ml_direction,
                        )
            except Exception as exc:
                logger.debug("HybridEnsemble blend failed for %s: %s", symbol, exc)

        # ── Adaptive edge selection (optional override) ───────────────────────
        # When an AdaptiveEdgeSelector is injected it analyses the live
        # indicators derived from the current bar and picks the single best
        # edge.  Its strategy_name overrides the default regime routing table
        # and its confidence is blended into the final aggregated score.
        _edge_decision = None
        _edge_conf_boost = 0.0
        if self._edge_selector is not None:
            try:
                from strategies.adaptive_edge_selector import (
                    EDGE_SKIP,
                    MarketSnapshot,
                )

                # Build a lightweight snapshot from the current bar
                _last = ohlcv.iloc[-1] if hasattr(ohlcv, "iloc") else {}
                _price = float(_last.get("close", 0) if isinstance(_last, dict) else getattr(_last, "close", 0))
                _atr_val = 0.0
                try:
                    import numpy as _np  # noqa: F401 — used for to_numpy()

                    _closes = ohlcv["close"].astype(float).to_numpy()
                    _highs = ohlcv["high"].astype(float).to_numpy()
                    _lows = ohlcv["low"].astype(float).to_numpy()
                    _trs = [
                        max(_highs[i] - _lows[i], abs(_highs[i] - _closes[i - 1]), abs(_lows[i] - _closes[i - 1]))
                        for i in range(max(1, len(_closes) - 14), len(_closes))
                    ]
                    _atr_val = float(sum(_trs) / len(_trs)) if _trs else 0.0
                except Exception as _exc:  # non-fatal: ATR defaults to 0.0
                    logger.debug("ATR computation failed for %s: %s", symbol, _exc)

                _snap = MarketSnapshot(
                    symbol=symbol,
                    price=_price,
                    atr=_atr_val,
                    adx=0.0,  # not computed here; edge selector falls back gracefully
                    rsi=50.0,
                    volume_delta=0.0,
                    cone_strength=0.0,
                )
                _edge_decision = self._edge_selector.select(_snap)

                if _edge_decision.edge != EDGE_SKIP and _edge_decision.strategy_name not in ("", "none"):
                    # Override strategy routing with the edge selector's choice
                    logger.debug(
                        "Brain[%s]: edge_selector chose edge=%s strategy=%s conf=%d",
                        symbol,
                        _edge_decision.edge,
                        _edge_decision.strategy_name,
                        _edge_decision.confidence,
                    )
                    # Confidence boost: edge confidence above 80 adds up to 0.10
                    _edge_conf_boost = max(0.0, (_edge_decision.confidence - 80) / 200.0)
            except Exception as exc:
                logger.debug("AdaptiveEdgeSelector failed for %s: %s", symbol, exc)
                _edge_decision = None

        # ── Strategy routing ──────────────────────────────────────────────────
        # Use edge selector's strategy if available and not skip, else default routing.
        if (
            _edge_decision is not None
            and _edge_decision.edge != "skip"
            and _edge_decision.strategy_name not in ("", "none")
        ):
            strategy_name = _edge_decision.strategy_name
        else:
            strategy_name = self._route_strategy(regime)
        str_direction, str_confidence = self._get_strategy_signal(strategy_name, ohlcv, symbol)

        # ── Signal aggregation ────────────────────────────────────────────────
        final_direction, final_confidence, reason = self._aggregate_signals(
            ml_direction=ml_direction,
            ml_confidence=ml_conf,
            strategy_direction=str_direction,
            strategy_confidence=str_confidence,
        )

        # ── Edge selector confidence boost ────────────────────────────────────
        if _edge_conf_boost > 0.0 and final_direction != "hold":
            final_confidence = min(1.0, final_confidence + _edge_conf_boost)
            reason += f"+edge_boost={_edge_conf_boost:.3f}"

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

        # ── Horizon hold logic ────────────────────────────────────────────────
        # If SIGNAL_HORIZON > 1 (e.g. 5 for a 5-bar-ahead model) enforce a
        # minimum hold period before accepting a reversal.
        # • On a new directional signal: start a countdown of _signal_horizon bars.
        # • While the countdown is active, suppress opposite-direction signals
        #   (they become "hold").  Same-direction signals extend the countdown.
        # • A "hold" action from the ML/strategy logic does NOT reset the counter.
        if self._signal_horizon > 1:
            remaining = self._hold_bars_remaining.get(symbol, 0)
            current_dir = self._hold_direction.get(symbol, "")

            if action in ("long", "short"):
                if remaining > 0 and action != current_dir:
                    # Opposite signal while still in hold window — suppress it
                    logger.debug(
                        "Brain[%s]: horizon hold active (%d bars left) — suppressing %s reversal",
                        symbol,
                        remaining,
                        action,
                    )
                    action = "hold"
                    reason += "+horizon_hold"
                else:
                    # New signal (or extending same direction) — reset counter
                    self._hold_bars_remaining[symbol] = self._signal_horizon
                    self._hold_direction[symbol] = action
            elif remaining > 0:
                # Neutral bar — tick down the counter
                self._hold_bars_remaining[symbol] = remaining - 1

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
