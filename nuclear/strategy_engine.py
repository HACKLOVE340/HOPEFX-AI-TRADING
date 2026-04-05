# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/strategy_engine.py
============================
Nuclear Strategy Engine — ICT/SMC + Breakout + Mean-Reversion.

Generates raw strategy signals from multi-timeframe features and ITOS cones.
All data from Redis streams. No broker APIs.

Three strategy modules
----------------------
SMCICTEngine      Order blocks, FVGs, liquidity sweeps, BOS/CHoCH, OTE
BreakoutEngine    BB squeeze expansion, volume-confirmed breakouts
MeanReversionEngine  RSI extremes, BB band touches, EMA mean-reversion

Each engine returns a StrategySignal. The NuclearStrategyEngine selects
the active engine based on RegimeResult.preferred_strategy, then validates
the signal against the ITOS cone before returning.

ITOS cone validation
--------------------
- Signal direction must align with cone drift bias (or cone is neutral)
- Entry price must be within ±2σ cone at the 1-month horizon
- Signals outside the cone are downgraded (confidence *= 0.5) or rejected

Usage
-----
    engine = NuclearStrategyEngine()
    signal = engine.generate(mtf_features, regime_result, cone_merged, ticks)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from nuclear.feature_builder import MultiTimeframeFeatures, TechnicalFeatures
from nuclear.itos_cone_engine import ItosCone
from nuclear.regime_classifier import (
    REGIME_BREAKOUT, REGIME_CRISIS, REGIME_HIGH_VOL, REGIME_LOW_VOL,
    REGIME_MEAN_REVERTING, REGIME_RANGE_BOUND, REGIME_TRENDING_DOWN,
    REGIME_TRENDING_UP, RegimeResult,
)
from nuclear.redis_stream_reader import TickSnapshot

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Signal direction ──────────────────────────────────────────────────────────
LONG = "long"
SHORT = "short"
FLAT = "flat"


@dataclass
class StrategySignal:
    """Raw signal from a strategy engine module."""

    direction: str          # "long" / "short" / "flat"
    strategy: str           # "smc_ict" / "breakout" / "mean_reversion"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    confidence: float       # 0–1
    regime: str
    timeframe: str          # primary timeframe that triggered the signal
    reasoning: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    cone_aligned: bool = True
    cone_bias: str = "neutral"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def risk_reward(self) -> float:
        if self.direction == LONG:
            risk = self.entry_price - self.stop_loss
            reward = self.take_profit_1 - self.entry_price
        else:
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.take_profit_1
        return reward / (risk + 1e-9)

    @property
    def is_valid(self) -> bool:
        return (
            self.direction in (LONG, SHORT)
            and self.entry_price > 0
            and self.stop_loss > 0
            and self.take_profit_1 > 0
            and self.confidence > 0.1
            and self.risk_reward >= 1.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "strategy": self.strategy,
            "entry_price": round(self.entry_price, 4),
            "stop_loss": round(self.stop_loss, 4),
            "take_profit_1": round(self.take_profit_1, 4),
            "take_profit_2": round(self.take_profit_2, 4),
            "take_profit_3": round(self.take_profit_3, 4),
            "confidence": round(self.confidence, 3),
            "risk_reward": round(self.risk_reward, 2),
            "regime": self.regime,
            "timeframe": self.timeframe,
            "cone_aligned": self.cone_aligned,
            "cone_bias": self.cone_bias,
            "is_valid": self.is_valid,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
            "generated_at": self.generated_at.isoformat(),
        }


# ── SMC / ICT Engine ──────────────────────────────────────────────────────────

class SMCICTEngine:
    """
    Smart Money Concepts / Inner Circle Trader signal generator.

    Detects:
    - Order Blocks (OB): last bearish/bullish candle before impulse move
    - Fair Value Gaps (FVG): imbalance between candle 1 and candle 3
    - Liquidity Sweeps: price raids above/below swing highs/lows
    - Break of Structure (BOS) / Change of Character (CHoCH)
    - Optimal Trade Entry (OTE): 61.8–79% Fibonacci retracement
    - Kill Zone timing: London (02-05 UTC), NY (07-10 UTC)
    """

    # OTE Fibonacci levels (ICT optimal zone)
    _OTE_LEVELS = [0.618, 0.705, 0.786]

    def generate(
        self,
        mtf: MultiTimeframeFeatures,
        regime: RegimeResult,
        ticks: list[TickSnapshot],
    ) -> StrategySignal | None:
        """Generate an ICT/SMC signal from multi-timeframe features."""
        # Use daily for structure, 1h for context, 5m/1m for entry
        daily = mtf.get("daily")
        h1 = mtf.get("1h")
        m5 = mtf.get("5m")
        m1 = mtf.get("1m")

        primary = daily or h1 or m5
        if primary is None:
            return None

        price = primary.current_price
        if price <= 0:
            return None

        reasoning: list[str] = []

        # ── Market structure bias from daily ──────────────────────────────────
        if daily:
            if daily.ema_9_above_21 and daily.ema_21_above_50 and daily.price_above_ema_200:
                structure = LONG
                reasoning.append("Daily: bullish structure (EMA9>21>50, price>EMA200)")
            elif not daily.ema_9_above_21 and not daily.ema_21_above_50 and not daily.price_above_ema_200:
                structure = SHORT
                reasoning.append("Daily: bearish structure (EMA9<21<50, price<EMA200)")
            else:
                structure = FLAT
                reasoning.append("Daily: mixed structure")
        else:
            structure = FLAT

        if structure == FLAT:
            return None

        # ── 1h context alignment ──────────────────────────────────────────────
        if h1:
            h1_aligned = (
                (structure == LONG and h1.price_above_ema_50) or
                (structure == SHORT and not h1.price_above_ema_50)
            )
            if not h1_aligned:
                reasoning.append("1h: context not aligned — skipping")
                return None
            reasoning.append(f"1h: context aligned with {structure}")

        # ── Order Block detection (5m entry) ──────────────────────────────────
        entry_feat = m5 or m1 or primary
        atr = entry_feat.atr if entry_feat.atr > 0 else price * 0.005

        # OB: price near EMA21 (institutional re-entry zone)
        ob_zone_long = abs(price - entry_feat.ema_21) / (price + 1e-9) < 0.003
        ob_zone_short = abs(price - entry_feat.ema_21) / (price + 1e-9) < 0.003

        # FVG: BB pct_b at extremes signals imbalance
        fvg_long = entry_feat.bb_pct_b < 0.2 and structure == LONG
        fvg_short = entry_feat.bb_pct_b > 0.8 and structure == SHORT

        # Liquidity sweep: RSI divergence at extremes
        liq_sweep_long = entry_feat.rsi_oversold and structure == LONG
        liq_sweep_short = entry_feat.rsi_overbought and structure == SHORT

        # OTE: price in 61.8–79% retracement zone (approximated via BB pct_b)
        ote_long = 0.2 <= entry_feat.bb_pct_b <= 0.45 and structure == LONG
        ote_short = 0.55 <= entry_feat.bb_pct_b <= 0.8 and structure == SHORT

        # Score entry conditions
        entry_score = 0
        if structure == LONG:
            if ob_zone_long:
                entry_score += 2
                reasoning.append("OB zone: price near EMA21 (long)")
            if fvg_long:
                entry_score += 2
                reasoning.append("FVG: BB pct_b < 0.2 (long imbalance)")
            if liq_sweep_long:
                entry_score += 3
                reasoning.append("Liquidity sweep: RSI oversold (long)")
            if ote_long:
                entry_score += 2
                reasoning.append("OTE: price in 61.8-79% retracement zone (long)")
            if entry_feat.macd_bullish:
                entry_score += 1
                reasoning.append("MACD bullish histogram")
        else:
            if ob_zone_short:
                entry_score += 2
                reasoning.append("OB zone: price near EMA21 (short)")
            if fvg_short:
                entry_score += 2
                reasoning.append("FVG: BB pct_b > 0.8 (short imbalance)")
            if liq_sweep_short:
                entry_score += 3
                reasoning.append("Liquidity sweep: RSI overbought (short)")
            if ote_short:
                entry_score += 2
                reasoning.append("OTE: price in 61.8-79% retracement zone (short)")
            if not entry_feat.macd_bullish and entry_feat.macd_histogram < 0:
                entry_score += 1
                reasoning.append("MACD bearish histogram")

        if entry_score < 3:
            reasoning.append(f"ICT entry score {entry_score} < 3 — no signal")
            return None

        # ── Risk levels ───────────────────────────────────────────────────────
        confidence = min(0.4 + entry_score * 0.08, 0.92)

        if structure == LONG:
            sl = price - 1.5 * atr
            tp1 = price + 1.5 * atr
            tp2 = price + 2.5 * atr
            tp3 = price + 4.0 * atr
        else:
            sl = price + 1.5 * atr
            tp1 = price - 1.5 * atr
            tp2 = price - 2.5 * atr
            tp3 = price - 4.0 * atr

        return StrategySignal(
            direction=structure,
            strategy="smc_ict",
            entry_price=price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            confidence=confidence,
            regime=regime.regime,
            timeframe=entry_feat.timeframe,
            reasoning=reasoning,
            metadata={
                "entry_score": entry_score,
                "ob_zone": ob_zone_long or ob_zone_short,
                "fvg": fvg_long or fvg_short,
                "liq_sweep": liq_sweep_long or liq_sweep_short,
                "ote": ote_long or ote_short,
                "atr": round(atr, 4),
            },
        )


# ── Breakout Engine ───────────────────────────────────────────────────────────

class BreakoutEngine:
    """
    Volatility breakout signal generator.

    Detects BB squeeze → expansion with volume confirmation.
    Uses multi-timeframe alignment: daily/weekly for direction,
    1h/30m for breakout confirmation, 5m/1m for entry.
    """

    def generate(
        self,
        mtf: MultiTimeframeFeatures,
        regime: RegimeResult,
        ticks: list[TickSnapshot],
    ) -> StrategySignal | None:
        entry_feat = mtf.get("5m") or mtf.get("1h") or mtf.get("daily")
        confirm_feat = mtf.get("1h") or mtf.get("daily")
        daily = mtf.get("daily")

        if entry_feat is None:
            return None

        price = entry_feat.current_price
        atr = entry_feat.atr if entry_feat.atr > 0 else price * 0.005
        reasoning: list[str] = []

        # Require BB squeeze on entry TF
        if not entry_feat.bb_squeeze:
            reasoning.append("No BB squeeze on entry TF — no breakout signal")
            return None

        # Volume confirmation
        if not entry_feat.volume_surge:
            reasoning.append("No volume surge — breakout not confirmed")
            return None

        reasoning.append(f"BB squeeze + volume surge on {entry_feat.timeframe}")

        # Direction from price vs BB mid and daily structure
        if price > entry_feat.bb_mid:
            direction = LONG
            reasoning.append("Price above BB mid → long breakout")
        else:
            direction = SHORT
            reasoning.append("Price below BB mid → short breakout")

        # Confirm with daily EMA alignment
        if daily:
            if direction == LONG and not daily.price_above_ema_50:
                reasoning.append("Daily EMA50 not aligned for long — reducing confidence")
                conf_penalty = 0.15
            elif direction == SHORT and daily.price_above_ema_50:
                reasoning.append("Daily EMA50 not aligned for short — reducing confidence")
                conf_penalty = 0.15
            else:
                conf_penalty = 0.0
                reasoning.append(f"Daily EMA50 aligned for {direction}")
        else:
            conf_penalty = 0.0

        # Confirm with 1h
        if confirm_feat:
            if direction == LONG and confirm_feat.macd_bullish:
                reasoning.append("1h MACD bullish — breakout confirmed")
                conf_bonus = 0.1
            elif direction == SHORT and confirm_feat.macd_histogram < 0:
                reasoning.append("1h MACD bearish — breakout confirmed")
                conf_bonus = 0.1
            else:
                conf_bonus = 0.0
        else:
            conf_bonus = 0.0

        confidence = min(0.55 + conf_bonus - conf_penalty, 0.90)

        if direction == LONG:
            sl = entry_feat.bb_lower - 0.5 * atr
            tp1 = price + 1.5 * atr
            tp2 = price + 2.5 * atr
            tp3 = price + 4.0 * atr
        else:
            sl = entry_feat.bb_upper + 0.5 * atr
            tp1 = price - 1.5 * atr
            tp2 = price - 2.5 * atr
            tp3 = price - 4.0 * atr

        return StrategySignal(
            direction=direction,
            strategy="breakout",
            entry_price=price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            confidence=confidence,
            regime=regime.regime,
            timeframe=entry_feat.timeframe,
            reasoning=reasoning,
            metadata={
                "bb_width": round(entry_feat.bb_width, 6),
                "volume_ratio": round(entry_feat.volume_ratio, 3),
                "atr": round(atr, 4),
            },
        )


# ── Mean Reversion Engine ─────────────────────────────────────────────────────

class MeanReversionEngine:
    """
    Mean-reversion signal generator.

    Triggers on RSI extremes + BB band touches + EMA mean-reversion setups.
    Requires range-bound or low-vol regime confirmation.
    """

    def generate(
        self,
        mtf: MultiTimeframeFeatures,
        regime: RegimeResult,
        ticks: list[TickSnapshot],
    ) -> StrategySignal | None:
        entry_feat = mtf.get("1h") or mtf.get("5m") or mtf.get("daily")
        daily = mtf.get("daily")

        if entry_feat is None:
            return None

        price = entry_feat.current_price
        atr = entry_feat.atr if entry_feat.atr > 0 else price * 0.005
        reasoning: list[str] = []

        # ── Long: oversold at BB lower ────────────────────────────────────────
        long_signal = (
            entry_feat.rsi_oversold
            and entry_feat.bb_pct_b < 0.1
            and not entry_feat.lower_lows  # not in a downtrend
        )

        # ── Short: overbought at BB upper ─────────────────────────────────────
        short_signal = (
            entry_feat.rsi_overbought
            and entry_feat.bb_pct_b > 0.9
            and not entry_feat.higher_highs  # not in an uptrend
        )

        if not long_signal and not short_signal:
            return None

        direction = LONG if long_signal else SHORT

        if long_signal:
            reasoning.append(
                f"RSI oversold ({entry_feat.rsi:.1f}) + BB pct_b={entry_feat.bb_pct_b:.2f} → long MR"
            )
        else:
            reasoning.append(
                f"RSI overbought ({entry_feat.rsi:.1f}) + BB pct_b={entry_feat.bb_pct_b:.2f} → short MR"
            )

        # Daily alignment check
        confidence = 0.55
        if daily:
            if direction == LONG and daily.rsi_oversold:
                confidence += 0.1
                reasoning.append("Daily RSI also oversold — strong MR setup")
            elif direction == SHORT and daily.rsi_overbought:
                confidence += 0.1
                reasoning.append("Daily RSI also overbought — strong MR setup")
            # Penalise if daily trend opposes
            if direction == LONG and daily.trend_slope < -0.001:
                confidence -= 0.15
                reasoning.append("Daily downtrend — reducing MR confidence")
            elif direction == SHORT and daily.trend_slope > 0.001:
                confidence -= 0.15
                reasoning.append("Daily uptrend — reducing MR confidence")

        confidence = max(0.25, min(confidence, 0.85))

        # Mean-reversion targets: tighter than trend-following
        if direction == LONG:
            sl = price - 1.2 * atr
            tp1 = entry_feat.bb_mid          # target: BB mid
            tp2 = price + 1.5 * atr
            tp3 = entry_feat.bb_upper
        else:
            sl = price + 1.2 * atr
            tp1 = entry_feat.bb_mid
            tp2 = price - 1.5 * atr
            tp3 = entry_feat.bb_lower

        return StrategySignal(
            direction=direction,
            strategy="mean_reversion",
            entry_price=price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            confidence=confidence,
            regime=regime.regime,
            timeframe=entry_feat.timeframe,
            reasoning=reasoning,
            metadata={
                "rsi": round(entry_feat.rsi, 2),
                "bb_pct_b": round(entry_feat.bb_pct_b, 4),
                "bb_mid": round(entry_feat.bb_mid, 4),
                "atr": round(atr, 4),
            },
        )


# ── ITOS Cone Validator ───────────────────────────────────────────────────────

class ConeValidator:
    """
    Validates and adjusts strategy signals against ITOS cone projections.

    Rules:
    1. Signal direction must align with cone drift bias (or cone neutral)
    2. Entry price must be within ±2σ at 1-month horizon
    3. Stop loss must not exceed ±3σ at 1-week horizon
    4. Misaligned signals: confidence *= 0.5 (downgrade, not reject)
    5. Price outside ±2σ cone: reject signal
    """

    def validate(
        self,
        signal: StrategySignal,
        cone: ItosCone | None,
        cone_merged: dict[str, Any] | None = None,
    ) -> StrategySignal:
        """
        Validate signal against ITOS cone. Returns adjusted signal.
        Returns signal with direction=FLAT if rejected.
        """
        if cone is None and not cone_merged:
            signal.cone_aligned = True
            signal.cone_bias = "neutral"
            return signal

        # Get cone parameters
        if cone is not None:
            bias = cone.bias
            vol_regime = cone.vol_regime
            upper_2s_1m = cone.upper_2sigma_1m
            lower_2s_1m = cone.lower_2sigma_1m
            upper_3s_1w = cone.dots.get("1w", None)
            lower_3s_1w = cone.dots.get("1w", None)
        else:
            bias = cone_merged.get("bias", "neutral")
            vol_regime = cone_merged.get("vol_regime", "normal_vol")
            dots = cone_merged.get("dots", {})
            dot_1m = dots.get("1m", {})
            dot_1w = dots.get("1w", {})
            upper_2s_1m = dot_1m.get("upper_2sigma", signal.entry_price * 1.05)
            lower_2s_1m = dot_1m.get("lower_2sigma", signal.entry_price * 0.95)
            upper_3s_1w = type("D", (), {"upper_3sigma": dot_1w.get("upper_3sigma", signal.entry_price * 1.03)})()
            lower_3s_1w = type("D", (), {"lower_3sigma": dot_1w.get("lower_3sigma", signal.entry_price * 0.97)})()

        signal.cone_bias = bias

        # Rule 1: Direction alignment
        direction_ok = (
            bias == "neutral"
            or (signal.direction == LONG and bias == "bullish")
            or (signal.direction == SHORT and bias == "bearish")
        )

        if not direction_ok:
            signal.confidence *= 0.5
            signal.cone_aligned = False
            signal.reasoning.append(
                f"ITOS cone misaligned: signal={signal.direction} cone={bias} → confidence halved"
            )
        else:
            signal.cone_aligned = True
            signal.reasoning.append(f"ITOS cone aligned: {bias}")

        # Rule 2: Entry within ±2σ at 1m horizon
        price = signal.entry_price
        if not (lower_2s_1m <= price <= upper_2s_1m):
            signal.direction = FLAT
            signal.confidence = 0.0
            signal.reasoning.append(
                f"REJECTED: price {price:.2f} outside ±2σ cone "
                f"[{lower_2s_1m:.2f}, {upper_2s_1m:.2f}]"
            )
            return signal

        signal.reasoning.append(
            f"Price {price:.2f} within ±2σ cone [{lower_2s_1m:.2f}, {upper_2s_1m:.2f}]"
        )

        # Rule 3: High-vol cone → widen stops
        if vol_regime == "high_vol":
            if signal.direction == LONG:
                signal.stop_loss = min(signal.stop_loss, price * 0.985)
            else:
                signal.stop_loss = max(signal.stop_loss, price * 1.015)
            signal.reasoning.append("High-vol cone: stop widened")

        return signal


# ── NuclearStrategyEngine ─────────────────────────────────────────────────────

class NuclearStrategyEngine:
    """
    Top-level strategy engine that selects and runs the appropriate
    sub-engine based on the detected regime, then validates against
    the ITOS cone.

    Strategy selection:
      trending_up / trending_down → SMCICTEngine
      breakout / high_vol         → BreakoutEngine
      mean_reverting / range_bound / low_vol → MeanReversionEngine
      crisis                      → SMCICTEngine (liquidity sweeps)
    """

    def __init__(self) -> None:
        self._smc = SMCICTEngine()
        self._breakout = BreakoutEngine()
        self._mean_rev = MeanReversionEngine()
        self._cone_validator = ConeValidator()
        self._signal_history: list[StrategySignal] = []

    def generate(
        self,
        mtf: MultiTimeframeFeatures,
        regime: RegimeResult,
        cone: ItosCone | None = None,
        cone_merged: dict[str, Any] | None = None,
        ticks: list[TickSnapshot] | None = None,
    ) -> StrategySignal | None:
        """
        Generate a validated strategy signal.

        Parameters
        ----------
        mtf : MultiTimeframeFeatures
        regime : RegimeResult
        cone : ItosCone, optional
            Single-TF cone (daily preferred).
        cone_merged : dict, optional
            Multi-TF merged cone from ItosConeEngine.merge_cones().
        ticks : list[TickSnapshot], optional
            Recent ticks for microstructure context.

        Returns
        -------
        StrategySignal or None
        """
        ticks = ticks or []
        strategy_type = regime.preferred_strategy

        # Select engine
        raw_signal: StrategySignal | None = None
        if strategy_type == "smc_ict":
            raw_signal = self._smc.generate(mtf, regime, ticks)
            # Fallback to breakout if SMC finds nothing
            if raw_signal is None and regime.regime in (REGIME_HIGH_VOL, REGIME_BREAKOUT):
                raw_signal = self._breakout.generate(mtf, regime, ticks)
        elif strategy_type == "breakout":
            raw_signal = self._breakout.generate(mtf, regime, ticks)
            if raw_signal is None:
                raw_signal = self._smc.generate(mtf, regime, ticks)
        elif strategy_type == "mean_reversion":
            raw_signal = self._mean_rev.generate(mtf, regime, ticks)
            if raw_signal is None:
                raw_signal = self._smc.generate(mtf, regime, ticks)
        else:
            raw_signal = self._smc.generate(mtf, regime, ticks)

        if raw_signal is None:
            logger.debug("NuclearStrategyEngine: no signal for regime=%s", regime.regime)
            return None

        # Validate against ITOS cone
        validated = self._cone_validator.validate(raw_signal, cone, cone_merged)

        if validated.direction == FLAT:
            logger.debug("NuclearStrategyEngine: signal rejected by cone validator")
            return None

        if not validated.is_valid:
            logger.debug(
                "NuclearStrategyEngine: signal invalid (RR=%.2f conf=%.2f)",
                validated.risk_reward, validated.confidence,
            )
            return None

        self._signal_history.append(validated)
        if len(self._signal_history) > 200:
            self._signal_history = self._signal_history[-200:]

        logger.info(
            "NuclearStrategyEngine: %s %s @ %.4f SL=%.4f TP1=%.4f conf=%.2f RR=%.2f",
            validated.direction, validated.strategy, validated.entry_price,
            validated.stop_loss, validated.take_profit_1,
            validated.confidence, validated.risk_reward,
        )
        return validated

    def signal_history(self, n: int = 20) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._signal_history[-n:]]


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine_instance: NuclearStrategyEngine | None = None


def get_strategy_engine() -> NuclearStrategyEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = NuclearStrategyEngine()
    return _engine_instance
