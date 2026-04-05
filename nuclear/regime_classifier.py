# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/regime_classifier.py
==============================
Multi-timeframe market regime classifier for the Nuclear Strategy Engine.

Detects the current market regime by combining signals across ALL timeframes
(1m → yearly) plus macro environment (VIX/DXY/US10Y) and ITOS cone bias.

Regimes
-------
  TRENDING_UP      Strong uptrend: ADX > 25, price above EMA50/200, HH/HL
  TRENDING_DOWN    Strong downtrend: ADX > 25, price below EMA50/200, LL/LH
  BREAKOUT         Volatility expansion from squeeze: BB squeeze → expansion
  MEAN_REVERTING   Oscillating around mean: ADX < 20, RSI extremes
  RANGE_BOUND      Low-vol sideways: tight BB, low ATR, no trend
  HIGH_VOL         Elevated volatility: VIX > 25 or ATR spike
  LOW_VOL          Compressed volatility: VIX < 12, BB squeeze
  CRISIS           Extreme conditions: VIX > 35, gap moves, news shock

Classification logic
--------------------
1. Macro layer (VIX/DXY/US10Y) → sets crisis/high-vol floor
2. Long-term TF (monthly/yearly) → macro cycle bias
3. Medium-term TF (daily/weekly) → primary trend regime
4. Short-term TF (1h/30m) → intraday context
5. Entry TF (5m/1m) → micro regime for entry precision
6. ITOS cone → forward vol and drift alignment

Each layer votes; final regime is the weighted majority with confidence score.

Usage
-----
    from nuclear.regime_classifier import RegimeClassifier
    from nuclear.feature_builder import MultiTimeframeFeatures

    clf = RegimeClassifier()
    result = clf.classify(mtf_features, cone_merged)
    print(result.regime, result.confidence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nuclear.feature_builder import MacroFeatures, MultiTimeframeFeatures, TechnicalFeatures

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Regime labels ─────────────────────────────────────────────────────────────
REGIME_TRENDING_UP = "trending_up"
REGIME_TRENDING_DOWN = "trending_down"
REGIME_BREAKOUT = "breakout"
REGIME_MEAN_REVERTING = "mean_reverting"
REGIME_RANGE_BOUND = "range_bound"
REGIME_HIGH_VOL = "high_vol"
REGIME_LOW_VOL = "low_vol"
REGIME_CRISIS = "crisis"
REGIME_UNKNOWN = "unknown"

ALL_REGIMES = [
    REGIME_TRENDING_UP, REGIME_TRENDING_DOWN, REGIME_BREAKOUT,
    REGIME_MEAN_REVERTING, REGIME_RANGE_BOUND, REGIME_HIGH_VOL,
    REGIME_LOW_VOL, REGIME_CRISIS, REGIME_UNKNOWN,
]

# Timeframe weights for regime voting (higher = more influence)
_TF_WEIGHTS: dict[str, float] = {
    "yearly":  5.0,
    "monthly": 4.0,
    "weekly":  3.0,
    "daily":   2.5,
    "1h":      2.0,
    "30m":     1.5,
    "5m":      1.0,
    "1m":      0.5,
}


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class RegimeResult:
    """Output of the regime classifier."""

    regime: str
    confidence: float                    # 0–1
    sub_regime: str = ""                 # e.g. "trending_up:strong"
    macro_regime: str = ""               # macro-layer regime
    cone_bias: str = "neutral"           # from ITOS cone
    cone_vol_regime: str = "normal_vol"  # from ITOS cone
    votes: dict[str, float] = field(default_factory=dict)   # regime → weighted votes
    tf_regimes: dict[str, str] = field(default_factory=dict)  # tf → local regime
    reasoning: list[str] = field(default_factory=list)
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_trending(self) -> bool:
        return self.regime in (REGIME_TRENDING_UP, REGIME_TRENDING_DOWN)

    @property
    def is_volatile(self) -> bool:
        return self.regime in (REGIME_HIGH_VOL, REGIME_CRISIS, REGIME_BREAKOUT)

    @property
    def is_ranging(self) -> bool:
        return self.regime in (REGIME_RANGE_BOUND, REGIME_MEAN_REVERTING, REGIME_LOW_VOL)

    @property
    def preferred_strategy(self) -> str:
        """Default strategy type for this regime."""
        _MAP = {
            REGIME_TRENDING_UP:    "smc_ict",
            REGIME_TRENDING_DOWN:  "smc_ict",
            REGIME_BREAKOUT:       "breakout",
            REGIME_MEAN_REVERTING: "mean_reversion",
            REGIME_RANGE_BOUND:    "mean_reversion",
            REGIME_HIGH_VOL:       "breakout",
            REGIME_LOW_VOL:        "mean_reversion",
            REGIME_CRISIS:         "smc_ict",   # ICT handles crisis via liquidity sweeps
            REGIME_UNKNOWN:        "smc_ict",
        }
        return _MAP.get(self.regime, "smc_ict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 3),
            "sub_regime": self.sub_regime,
            "macro_regime": self.macro_regime,
            "cone_bias": self.cone_bias,
            "cone_vol_regime": self.cone_vol_regime,
            "is_trending": self.is_trending,
            "is_volatile": self.is_volatile,
            "is_ranging": self.is_ranging,
            "preferred_strategy": self.preferred_strategy,
            "votes": {k: round(v, 3) for k, v in self.votes.items()},
            "tf_regimes": self.tf_regimes,
            "reasoning": self.reasoning,
            "computed_at": self.computed_at.isoformat(),
        }


# ── RegimeClassifier ──────────────────────────────────────────────────────────

class RegimeClassifier:
    """
    Multi-timeframe regime classifier.

    Combines macro environment, ITOS cone bias, and per-timeframe
    technical signals into a single regime label with confidence score.

    Parameters
    ----------
    crisis_vix_threshold : float
        VIX level above which CRISIS regime is forced (default: 35).
    high_vol_vix_threshold : float
        VIX level above which HIGH_VOL is signalled (default: 25).
    adx_trend_threshold : float
        ADX-proxy above which a trend is considered strong (default: 25).
    """

    def __init__(
        self,
        crisis_vix_threshold: float = 35.0,
        high_vol_vix_threshold: float = 25.0,
        adx_trend_threshold: float = 25.0,
    ) -> None:
        self._crisis_vix = crisis_vix_threshold
        self._high_vol_vix = high_vol_vix_threshold
        self._adx_trend = adx_trend_threshold
        self._history: list[RegimeResult] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(
        self,
        mtf: MultiTimeframeFeatures,
        cone_merged: dict[str, Any] | None = None,
    ) -> RegimeResult:
        """
        Classify the current market regime.

        Parameters
        ----------
        mtf : MultiTimeframeFeatures
            Feature set from FeatureBuilder.build_all().
        cone_merged : dict, optional
            Merged ITOS cone dict from ItosConeEngine.merge_cones().

        Returns
        -------
        RegimeResult
        """
        reasoning: list[str] = []
        votes: dict[str, float] = {r: 0.0 for r in ALL_REGIMES}
        tf_regimes: dict[str, str] = {}

        # ── Layer 1: Macro override ───────────────────────────────────────────
        macro = mtf.macro
        macro_regime = self._classify_macro(macro, reasoning)

        if macro_regime == REGIME_CRISIS:
            result = RegimeResult(
                regime=REGIME_CRISIS,
                confidence=0.95,
                macro_regime=macro_regime,
                cone_bias=_cone_bias(cone_merged),
                cone_vol_regime=_cone_vol(cone_merged),
                votes={REGIME_CRISIS: 1.0},
                tf_regimes={},
                reasoning=reasoning,
            )
            self._record(result)
            return result

        # ── Layer 2: Per-timeframe voting ─────────────────────────────────────
        for tf, weight in _TF_WEIGHTS.items():
            feat = mtf.get(tf)
            if feat is None or feat.bar_count < 2:
                continue
            local_regime = self._classify_tf(feat, reasoning, tf)
            tf_regimes[tf] = local_regime
            votes[local_regime] = votes.get(local_regime, 0.0) + weight

        # ── Layer 3: Macro votes ──────────────────────────────────────────────
        if macro_regime == REGIME_HIGH_VOL:
            votes[REGIME_HIGH_VOL] += 3.0
            votes[REGIME_BREAKOUT] += 1.5
        elif macro_regime == REGIME_LOW_VOL:
            votes[REGIME_LOW_VOL] += 2.0
            votes[REGIME_RANGE_BOUND] += 1.0

        # ── Layer 4: ITOS cone alignment ──────────────────────────────────────
        cone_bias = _cone_bias(cone_merged)
        cone_vol = _cone_vol(cone_merged)

        if cone_bias == "bullish":
            votes[REGIME_TRENDING_UP] += 1.5
            reasoning.append("ITOS cone: bullish drift → +1.5 trending_up")
        elif cone_bias == "bearish":
            votes[REGIME_TRENDING_DOWN] += 1.5
            reasoning.append("ITOS cone: bearish drift → +1.5 trending_down")

        if cone_vol == "high_vol":
            votes[REGIME_HIGH_VOL] += 1.0
            votes[REGIME_BREAKOUT] += 0.5
        elif cone_vol == "low_vol":
            votes[REGIME_LOW_VOL] += 1.0
            votes[REGIME_RANGE_BOUND] += 0.5

        # ── Determine winner ──────────────────────────────────────────────────
        total_votes = sum(votes.values())
        if total_votes == 0:
            regime = REGIME_UNKNOWN
            confidence = 0.0
        else:
            regime = max(votes, key=lambda r: votes[r])
            top_vote = votes[regime]
            confidence = min(top_vote / (total_votes + 1e-9), 1.0)

        # Sub-regime label
        sub_regime = self._sub_regime(regime, mtf, cone_merged)

        result = RegimeResult(
            regime=regime,
            confidence=round(confidence, 3),
            sub_regime=sub_regime,
            macro_regime=macro_regime,
            cone_bias=cone_bias,
            cone_vol_regime=cone_vol,
            votes={k: round(v, 3) for k, v in votes.items() if v > 0},
            tf_regimes=tf_regimes,
            reasoning=reasoning,
        )
        self._record(result)
        logger.debug(
            "RegimeClassifier: %s (conf=%.2f) sub=%s macro=%s cone=%s",
            regime, confidence, sub_regime, macro_regime, cone_bias,
        )
        return result

    def classify_single_tf(
        self,
        feat: TechnicalFeatures,
    ) -> str:
        """Classify regime for a single timeframe (no macro/cone context)."""
        return self._classify_tf(feat, [], feat.timeframe)

    def history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n regime results."""
        return [r.to_dict() for r in self._history[-n:]]

    # ── Internal classifiers ──────────────────────────────────────────────────

    def _classify_macro(
        self,
        macro: MacroFeatures,
        reasoning: list[str],
    ) -> str:
        """Classify macro regime from VIX/DXY/US10Y."""
        if macro.vix >= self._crisis_vix:
            reasoning.append(f"CRISIS: VIX={macro.vix:.1f} ≥ {self._crisis_vix}")
            return REGIME_CRISIS
        if macro.vix >= self._high_vol_vix:
            reasoning.append(f"HIGH_VOL: VIX={macro.vix:.1f} ≥ {self._high_vol_vix}")
            return REGIME_HIGH_VOL
        if macro.vix < 12:
            reasoning.append(f"LOW_VOL: VIX={macro.vix:.1f} < 12")
            return REGIME_LOW_VOL
        reasoning.append(f"Macro normal: VIX={macro.vix:.1f}")
        return "normal"

    def _classify_tf(
        self,
        feat: TechnicalFeatures,
        reasoning: list[str],
        tf: str,
    ) -> str:
        """
        Classify regime for a single timeframe using technical features.

        Uses ADX-proxy (trend_slope + EMA alignment), BB squeeze, RSI,
        and volume to determine the local regime.
        """
        price = feat.current_price

        # ── Trend detection via EMA alignment + slope ─────────────────────────
        ema_bullish = feat.ema_9_above_21 and feat.ema_21_above_50 and feat.price_above_ema_50
        ema_bearish = (
            not feat.ema_9_above_21
            and not feat.ema_21_above_50
            and not feat.price_above_ema_50
        )
        strong_slope = abs(feat.trend_slope) > 0.0005  # 0.05% per bar

        # ── Volatility state ──────────────────────────────────────────────────
        high_atr = feat.atr_pct > 0.015   # ATR > 1.5% of price
        low_atr = feat.atr_pct < 0.004    # ATR < 0.4% of price

        # ── Breakout: squeeze → expansion ────────────────────────────────────
        if feat.bb_squeeze and feat.volume_surge:
            reasoning.append(f"{tf}: BB squeeze + volume surge → BREAKOUT")
            return REGIME_BREAKOUT

        # ── Crisis / high-vol at TF level ─────────────────────────────────────
        if feat.atr_pct > 0.025:
            reasoning.append(f"{tf}: ATR%={feat.atr_pct:.3f} > 2.5% → HIGH_VOL")
            return REGIME_HIGH_VOL

        # ── Trending up ───────────────────────────────────────────────────────
        if ema_bullish and strong_slope and feat.trend_slope > 0:
            if feat.higher_highs:
                reasoning.append(f"{tf}: EMA bullish + HH + slope → TRENDING_UP")
                return REGIME_TRENDING_UP
            reasoning.append(f"{tf}: EMA bullish + slope → TRENDING_UP")
            return REGIME_TRENDING_UP

        # ── Trending down ─────────────────────────────────────────────────────
        if ema_bearish and strong_slope and feat.trend_slope < 0:
            if feat.lower_lows:
                reasoning.append(f"{tf}: EMA bearish + LL + slope → TRENDING_DOWN")
                return REGIME_TRENDING_DOWN
            reasoning.append(f"{tf}: EMA bearish + slope → TRENDING_DOWN")
            return REGIME_TRENDING_DOWN

        # ── Mean reverting: RSI extremes + moderate vol ───────────────────────
        if (feat.rsi_overbought or feat.rsi_oversold) and not high_atr:
            reasoning.append(
                f"{tf}: RSI={'OB' if feat.rsi_overbought else 'OS'} → MEAN_REVERTING"
            )
            return REGIME_MEAN_REVERTING

        # ── Range bound: low vol, no trend ───────────────────────────────────
        if low_atr and not strong_slope and feat.bb_width < 0.02:
            reasoning.append(f"{tf}: low ATR + tight BB → RANGE_BOUND")
            return REGIME_RANGE_BOUND

        # ── Low vol ───────────────────────────────────────────────────────────
        if low_atr and feat.bb_squeeze:
            reasoning.append(f"{tf}: low ATR + BB squeeze → LOW_VOL")
            return REGIME_LOW_VOL

        # ── High vol ─────────────────────────────────────────────────────────
        if high_atr:
            reasoning.append(f"{tf}: high ATR → HIGH_VOL")
            return REGIME_HIGH_VOL

        # ── Default: mean reverting ───────────────────────────────────────────
        reasoning.append(f"{tf}: no clear signal → MEAN_REVERTING")
        return REGIME_MEAN_REVERTING

    @staticmethod
    def _sub_regime(
        regime: str,
        mtf: MultiTimeframeFeatures,
        cone_merged: dict[str, Any] | None,
    ) -> str:
        """Generate a sub-regime label with additional context."""
        daily = mtf.get("daily")
        cone_bias = _cone_bias(cone_merged)

        if regime == REGIME_TRENDING_UP:
            strength = "strong" if (daily and daily.price_above_ema_200) else "moderate"
            return f"trending_up:{strength}:{cone_bias}"
        if regime == REGIME_TRENDING_DOWN:
            strength = "strong" if (daily and not daily.price_above_ema_200) else "moderate"
            return f"trending_down:{strength}:{cone_bias}"
        if regime == REGIME_BREAKOUT:
            direction = cone_bias if cone_bias != "neutral" else "unknown"
            return f"breakout:{direction}"
        if regime == REGIME_MEAN_REVERTING:
            if daily:
                if daily.rsi_overbought:
                    return "mean_reverting:overbought"
                if daily.rsi_oversold:
                    return "mean_reverting:oversold"
            return "mean_reverting:neutral"
        return regime

    def _record(self, result: RegimeResult) -> None:
        self._history.append(result)
        if len(self._history) > 500:
            self._history = self._history[-500:]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cone_bias(cone: dict[str, Any] | None) -> str:
    if not cone:
        return "neutral"
    return str(cone.get("bias", "neutral"))


def _cone_vol(cone: dict[str, Any] | None) -> str:
    if not cone:
        return "normal_vol"
    return str(cone.get("vol_regime", "normal_vol"))


# ── Module-level singleton ────────────────────────────────────────────────────

_classifier_instance: RegimeClassifier | None = None


def get_regime_classifier() -> RegimeClassifier:
    """Return the process-wide RegimeClassifier singleton."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = RegimeClassifier()
    return _classifier_instance
