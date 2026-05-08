# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Signal Strength Scorer — multi-factor signal validation engine.

Evaluates every candidate signal across six independent dimensions and
returns a composite score (0–1) along with a full breakdown so that both
the auto-trade engine and human operators can understand WHY a signal is
strong or weak.

Dimensions
----------
1. ML Confidence       — distance of blended ML probability from neutral (0.5)
2. Technical Consensus — fraction of technical indicators that agree with direction
3. Macro Alignment     — macro environment support (DXY trend, yield curve, VIX regime)
4. Regime Suitability  — current market regime compatibility with signal type
5. MTF Confluence      — multi-timeframe trend agreement
6. Volatility Quality  — volatility in the tradeable sweet-spot (not too low, not spiking)

Composite formula
-----------------
score = Σ (weight_i × dimension_score_i)

Weights (sum = 1.0):
  ml_confidence    : 0.35  (most important — model edge)
  technical        : 0.20
  macro_alignment  : 0.15
  regime           : 0.15
  mtf_confluence   : 0.10
  volatility       : 0.05

Grade mapping:
  ≥ 0.75 : STRONG    — auto-trade eligible, high conviction
  0.60–0.75 : GOOD   — auto-trade eligible with normal sizing
  0.45–0.60 : FAIR   — human review recommended; reduce size
  < 0.45  : WEAK     — block from auto-trade

Usage
-----
    from ml.signal_scorer import SignalScorer, score_signal

    result = score_signal(
        signal_payload=signal_dict,
        ohlcv=df,          # pd.DataFrame with OHLCV columns
        macro_df=macro,    # optional macro DataFrame
        symbol="XAU_USD",
    )
    if result.grade in ("STRONG", "GOOD"):
        submit_order(signal_dict)

    print(result)
    # SignalScore(score=0.72 grade=GOOD ml=0.81 tech=0.67 macro=0.60
    #            regime=0.75 mtf=0.50 vol=0.80)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Weight configuration ──────────────────────────────────────────────────────

_W_ML     = float(os.getenv("SCORER_W_ML",    "0.35"))
_W_TECH   = float(os.getenv("SCORER_W_TECH",  "0.20"))
_W_MACRO  = float(os.getenv("SCORER_W_MACRO", "0.15"))
_W_REGIME = float(os.getenv("SCORER_W_REGIME","0.15"))
_W_MTF    = float(os.getenv("SCORER_W_MTF",   "0.10"))
_W_VOL    = float(os.getenv("SCORER_W_VOL",   "0.05"))

_STRONG_THRESHOLD = float(os.getenv("SCORER_STRONG_THRESHOLD", "0.75"))
_GOOD_THRESHOLD   = float(os.getenv("SCORER_GOOD_THRESHOLD",   "0.60"))
_FAIR_THRESHOLD   = float(os.getenv("SCORER_FAIR_THRESHOLD",   "0.45"))


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class DimensionScores:
    ml_confidence:   float = 0.5
    technical:       float = 0.5
    macro_alignment: float = 0.5
    regime:          float = 0.5
    mtf_confluence:  float = 0.5
    volatility:      float = 0.5
    details:         dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalScore:
    composite: float
    grade: str            # STRONG / GOOD / FAIR / WEAK
    dimensions: DimensionScores
    direction: str
    symbol: str
    latency_ms: float = 0.0

    def __str__(self) -> str:
        d = self.dimensions
        return (
            f"SignalScore({self.symbol} {self.direction} "
            f"score={self.composite:.3f} [{self.grade}] "
            f"ml={d.ml_confidence:.2f} tech={d.technical:.2f} "
            f"macro={d.macro_alignment:.2f} regime={d.regime:.2f} "
            f"mtf={d.mtf_confluence:.2f} vol={d.volatility:.2f} "
            f"{self.latency_ms:.1f}ms)"
        )

    def to_dict(self) -> dict[str, Any]:
        d = self.dimensions
        return {
            "composite_score": round(self.composite, 4),
            "grade": self.grade,
            "direction": self.direction,
            "symbol": self.symbol,
            "dimensions": {
                "ml_confidence":   round(d.ml_confidence, 4),
                "technical":       round(d.technical, 4),
                "macro_alignment": round(d.macro_alignment, 4),
                "regime":          round(d.regime, 4),
                "mtf_confluence":  round(d.mtf_confluence, 4),
                "volatility":      round(d.volatility, 4),
            },
            "details": d.details,
            "latency_ms": round(self.latency_ms, 2),
        }


# ── Individual dimension scorers ──────────────────────────────────────────────

def _score_ml_confidence(
    signal_payload: dict[str, Any],
    direction: str,
) -> tuple[float, dict[str, Any]]:
    """
    Score based on ML probability distance from 0.5.

    - Blended HybridEnsemble probability (XGB + LSTM + RL) if available
    - Falls back to AdvancedPredictor probability
    - Falls back to signal_payload["probability"]

    Returns a 0–1 score where 1.0 = maximum conviction, 0.5 = neutral.
    Direction mismatch returns a score below 0.5 (actively contradicting).
    """
    prob: float = float(signal_payload.get("probability", 0.5))
    model_version: str = signal_payload.get("model_version", "unknown")

    is_long = direction.upper() in ("BUY", "LONG")

    # directional confidence: how strongly does the model agree?
    if is_long:
        # prob > 0.5 = bullish confirmation
        raw = (prob - 0.5) * 2.0   # maps [0.5, 1.0] → [0.0, 1.0]
    else:
        # prob < 0.5 = bearish confirmation
        raw = (0.5 - prob) * 2.0   # maps [0.0, 0.5] → [1.0, 0.0] ... wait:
        # Actually: for a SELL signal, low prob is good. (0.5 - prob)*2 → [0,1] as prob→0
        raw = (0.5 - prob) * 2.0

    raw = float(np.clip(raw, 0.0, 1.0))

    # Boost for high-confidence flag in payload
    high_conf: bool = bool(signal_payload.get("high_confidence", False))
    if high_conf and raw > 0.5:
        raw = min(1.0, raw * 1.1)

    # Penalty when model abstained
    if signal_payload.get("abstain", False):
        raw *= 0.5

    details = {
        "raw_probability": prob,
        "model_version": model_version,
        "high_confidence": high_conf,
        "abstain": signal_payload.get("abstain", False),
        "hybrid_components": signal_payload.get("hybrid_components", {}),
    }
    return float(np.clip(raw, 0.0, 1.0)), details


def _score_technical_consensus(
    ohlcv,
    direction: str,
    signal_payload: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Count technical indicators that agree with direction.

    Indicators checked:
    - RSI position (>50 bullish, <50 bearish)
    - MACD histogram sign
    - EMA20 vs EMA50 crossover
    - Price above/below Bollinger mid band
    - ADX trend strength (neutral if < 20)
    - Stochastic position
    - Price momentum (5-bar return sign)

    Returns fraction of agreeing indicators as the score.
    """
    if ohlcv is None or len(ohlcv) < 52:
        # Use signal payload metadata when OHLCV unavailable
        rsi = float(signal_payload.get("rsi", 50.0))
        macd_hist = float(signal_payload.get("macd_hist", 0.0))
        votes = [
            (rsi > 50) == (direction.upper() in ("BUY", "LONG")),
            (macd_hist > 0) == (direction.upper() in ("BUY", "LONG")),
        ]
        score = sum(votes) / max(len(votes), 1)
        return float(score), {"source": "payload_fallback", "votes": int(sum(votes)), "total": len(votes)}

    try:
        import pandas as pd
        from research.ta_compat import (
            RSIIndicator, MACD, EMAIndicator, ADXIndicator,
            BollingerBands, StochasticOscillator,
        )

        c = pd.Series(ohlcv["close"].astype(float).values)
        h = pd.Series(ohlcv["high"].astype(float).values)
        l = pd.Series(ohlcv["low"].astype(float).values)

        rsi = float(RSIIndicator(c).rsi().iloc[-1])
        macd_obj = MACD(c)
        macd_hist_v = float(macd_obj.macd_diff().iloc[-1])
        ema20 = float(EMAIndicator(c, 20).ema_indicator().iloc[-1])
        ema50 = float(EMAIndicator(c, 50).ema_indicator().iloc[-1])
        adx = float(ADXIndicator(h, l, c).adx().iloc[-1])
        bb = BollingerBands(c, 20)
        bb_pct = float(bb.bollinger_pband().iloc[-1])
        stoch = float(StochasticOscillator(h, l, c).stoch().iloc[-1])
        last_close = float(c.iloc[-1])
        mom5 = float((c.iloc[-1] - c.iloc[-6]) / (c.iloc[-6] + 1e-9)) if len(c) >= 6 else 0.0

        is_long = direction.upper() in ("BUY", "LONG")

        indicator_votes = {
            "rsi_bullish":      (rsi > 50) == is_long,
            "macd_hist":        (macd_hist_v > 0) == is_long,
            "ema_crossover":    (ema20 > ema50) == is_long,
            "bb_position":      (bb_pct > 0.5) == is_long,
            "stoch_position":   (stoch > 50) == is_long,
            "momentum_5bar":    (mom5 > 0) == is_long,
        }

        # ADX: only vote when trend is strong (> 20), otherwise neutral
        if adx > 20:
            indicator_votes["adx_trending"] = True  # trending = good for trend signals

        n_agree = sum(indicator_votes.values())
        n_total = len(indicator_votes)
        score = n_agree / n_total

        details = {
            "rsi": round(rsi, 1),
            "macd_hist": round(macd_hist_v, 4),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "adx": round(adx, 1),
            "bb_pct": round(bb_pct, 3),
            "stoch": round(stoch, 1),
            "mom_5bar": round(mom5 * 100, 3),
            "votes": n_agree,
            "total": n_total,
            "indicator_votes": {k: int(v) for k, v in indicator_votes.items()},
        }
        return float(np.clip(score, 0.0, 1.0)), details

    except Exception as exc:
        logger.debug("Technical consensus scorer error: %s", exc)
        return 0.5, {"error": str(exc)}


def _score_macro_alignment(
    macro_df,
    direction: str,
    symbol: str,
) -> tuple[float, dict[str, Any]]:
    """
    Score macro environment alignment with signal direction.

    For XAU_USD (gold):
    - DXY rising → bearish gold  (inverse correlation)
    - Yield curve steepening (10Y-2Y spread widening) → bearish gold
    - VIX > 20 → bullish gold (safe-haven demand)
    - VIX > 35 → very bullish gold (panic safe-haven)

    For FX pairs:
    - Uses relative interest rate differential direction
    """
    if macro_df is None or macro_df.empty:
        return 0.5, {"source": "no_macro_data"}

    try:
        votes: list[bool] = []
        details: dict[str, Any] = {}

        is_long = direction.upper() in ("BUY", "LONG")
        is_gold = "XAU" in symbol.upper() or "GOLD" in symbol.upper()

        # DXY trend (5-bar EMA slope)
        if "dxy" in macro_df.columns:
            dxy = macro_df["dxy"].dropna()
            if len(dxy) >= 5:
                dxy_slope = float((dxy.iloc[-1] - dxy.iloc[-5]) / (dxy.iloc[-5] + 1e-9))
                details["dxy_slope_5d"] = round(dxy_slope * 100, 3)
                if is_gold:
                    # Rising DXY = bearish gold
                    votes.append((dxy_slope < 0) == is_long)
                else:
                    # Proxy: if the base currency is USD, rising DXY = bullish USD
                    votes.append(True)  # neutral for non-gold

        # VIX level
        if "vix" in macro_df.columns:
            vix = macro_df["vix"].dropna()
            if len(vix) >= 1:
                vix_val = float(vix.iloc[-1])
                details["vix"] = round(vix_val, 1)
                if is_gold:
                    if vix_val > 25:
                        votes.append(is_long)    # high VIX = safe-haven → bullish gold
                    elif vix_val < 15:
                        votes.append(not is_long) # very low VIX = risk-on → bearish gold
                    # 15–25 = neutral, no vote

        # Yield curve spread (10Y - 2Y): steepening = risk-on = bearish gold
        if "yield_10y" in macro_df.columns and "yield_5y" in macro_df.columns:
            y10 = macro_df["yield_10y"].dropna()
            y2  = macro_df["yield_5y"].dropna()
            if len(y10) >= 5 and len(y2) >= 5:
                spread_now  = float(y10.iloc[-1] - y2.iloc[-1])
                spread_prev = float(y10.iloc[-5] - y2.iloc[-5])
                spread_chg  = spread_now - spread_prev
                details["yield_curve_spread"] = round(spread_now, 3)
                details["spread_change_5d"] = round(spread_chg, 3)
                if is_gold:
                    # Steepening (risk-on) = bearish gold
                    votes.append((spread_chg < 0) == is_long)

        if not votes:
            return 0.5, {**details, "source": "insufficient_macro_signals"}

        score = sum(votes) / len(votes)
        details["votes"] = int(sum(votes))
        details["total"] = len(votes)
        return float(np.clip(score, 0.0, 1.0)), details

    except Exception as exc:
        logger.debug("Macro alignment scorer error: %s", exc)
        return 0.5, {"error": str(exc)}


def _score_regime_suitability(
    ohlcv,
    direction: str,
    signal_payload: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Score market regime compatibility.

    Regimes:
    - trending_up   : BUY signals get 0.85, SELL get 0.30
    - trending_down : SELL signals get 0.85, BUY get 0.30
    - overbought    : SELL signals get 0.75, BUY get 0.35
    - oversold      : BUY signals get 0.75, SELL get 0.35
    - ranging       : moderate score for both (0.55) — mean reversion possible
    - unknown       : neutral 0.50

    High ADX (> 30) boosts trending regime confidence.
    """
    regime: str = signal_payload.get("regime", "unknown")
    if not regime or regime == "unknown":
        if ohlcv is not None and len(ohlcv) >= 52:
            try:
                from research.vector_store import _regime_label
                import pandas as pd
                regime = _regime_label(ohlcv)
            except Exception:
                regime = "unknown"

    is_long = direction.upper() in ("BUY", "LONG")

    regime_matrix = {
        "trending_up":   {True: 0.85, False: 0.20},
        "trending_down": {True: 0.20, False: 0.85},
        "overbought":    {True: 0.30, False: 0.75},
        "oversold":      {True: 0.75, False: 0.30},
        "ranging":       {True: 0.55, False: 0.55},
        "unknown":       {True: 0.50, False: 0.50},
    }

    score = regime_matrix.get(regime, {True: 0.50, False: 0.50}).get(is_long, 0.50)

    # ADX boost for strong trends
    adx_val = float(signal_payload.get("adx", 0.0))
    if adx_val > 30 and regime in ("trending_up", "trending_down"):
        score = min(1.0, score * 1.1)

    details = {
        "regime": regime,
        "adx": round(adx_val, 1),
        "regime_score": round(score, 3),
    }
    return float(np.clip(score, 0.0, 1.0)), details


def _score_mtf_confluence(
    signal_payload: dict[str, Any],
    direction: str,
) -> tuple[float, dict[str, Any]]:
    """
    Score multi-timeframe trend confluence.

    Reads from signal_payload keys injected by the signal engine:
    - h4_trend : "up" / "down" / "flat"
    - d1_trend : "up" / "down" / "flat"
    - w1_trend : "up" / "down" / "flat"  (optional)

    Full alignment (H4 + D1 + W1 all agree with signal direction): 1.0
    Two timeframes agree: 0.75
    One timeframe agrees: 0.50
    Zero agree (counter-trend): 0.20
    No MTF data: 0.50 (neutral)
    """
    is_long = direction.upper() in ("BUY", "LONG")

    timeframe_trends = {
        "h4_trend": signal_payload.get("h4_trend", "").lower(),
        "d1_trend": signal_payload.get("d1_trend", "").lower(),
        "w1_trend": signal_payload.get("w1_trend", "").lower(),
    }

    trend_votes = []
    for tf, trend in timeframe_trends.items():
        if trend in ("up", "down"):
            trend_votes.append((trend == "up") == is_long)

    if not trend_votes:
        return 0.5, {"source": "no_mtf_data", "trends": timeframe_trends}

    n_agree = sum(trend_votes)
    n_total = len(trend_votes)

    # Non-linear scoring: consensus matters more than linear fraction
    score_map = {0: 0.20, 1: 0.50, 2: 0.75, 3: 1.00}
    score = score_map.get(n_agree, 0.50)

    details = {
        "timeframe_trends": timeframe_trends,
        "agree": n_agree,
        "total": n_total,
        "score": round(score, 3),
    }
    return float(score), details


def _score_volatility_quality(
    ohlcv,
    signal_payload: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Score current volatility environment quality for trading.

    Sweet-spot: ATR percentile 20–80 (neither too quiet nor too noisy).
    - Flat/dead markets (ATR < 10th pct): signals are noise → 0.20
    - Normal vol (10th–80th pct): good trading conditions → 0.80
    - High vol spike (> 90th pct): spread widens, execution risk → 0.40
    - Extreme spike (> 95th pct): very dangerous → 0.10

    Also checks for news-blackout flag in payload.
    """
    # Check for news blackout
    if signal_payload.get("news_blackout", False):
        return 0.10, {"reason": "news_blackout_active"}

    if ohlcv is None or len(ohlcv) < 20:
        return 0.5, {"source": "insufficient_data"}

    try:
        import pandas as pd
        from research.ta_compat import AverageTrueRange

        c = pd.Series(ohlcv["close"].astype(float).values)
        h = pd.Series(ohlcv["high"].astype(float).values)
        l = pd.Series(ohlcv["low"].astype(float).values)

        atr_series = AverageTrueRange(h, l, c, window=14).average_true_range().dropna()
        if len(atr_series) < 10:
            return 0.5, {"source": "insufficient_atr"}

        atr_current = float(atr_series.iloc[-1])
        atr_median = float(atr_series.median())

        # ATR relative to median
        atr_rel = atr_current / (atr_median + 1e-9)

        if atr_rel < 0.3:
            score = 0.20    # dead market
        elif atr_rel < 0.6:
            score = 0.50    # below-normal vol
        elif atr_rel <= 1.8:
            score = 0.85    # sweet-spot
        elif atr_rel <= 2.5:
            score = 0.50    # elevated — wider spreads
        elif atr_rel <= 3.5:
            score = 0.25    # high vol spike
        else:
            score = 0.10    # extreme spike

        # ATR as pct of price for context
        last_close = float(c.iloc[-1])
        atr_pct = atr_current / (last_close + 1e-9) * 100

        details = {
            "atr_current": round(atr_current, 4),
            "atr_median": round(atr_median, 4),
            "atr_relative": round(atr_rel, 3),
            "atr_pct_of_price": round(atr_pct, 4),
        }
        return float(np.clip(score, 0.0, 1.0)), details

    except Exception as exc:
        logger.debug("Volatility quality scorer error: %s", exc)
        return 0.5, {"error": str(exc)}


# ── Composite scorer ──────────────────────────────────────────────────────────

class SignalScorer:
    """
    Computes a composite signal strength score across six dimensions.

    Thread-safe.  Singleton via ``get_signal_scorer()``.
    """

    def __init__(self) -> None:
        # Normalize weights so they always sum to 1.0
        raw = [_W_ML, _W_TECH, _W_MACRO, _W_REGIME, _W_MTF, _W_VOL]
        total = sum(raw) or 1.0
        self._w_ml, self._w_tech, self._w_macro, self._w_regime, self._w_mtf, self._w_vol = [
            w / total for w in raw
        ]

    def score(
        self,
        signal_payload: dict[str, Any],
        ohlcv=None,
        macro_df=None,
        symbol: str = "UNKNOWN",
    ) -> SignalScore:
        """
        Compute composite signal strength score.

        Parameters
        ----------
        signal_payload : dict returned by signal_engine (includes probability,
                         direction, model_version, etc.)
        ohlcv          : pd.DataFrame with open/high/low/close/volume columns
        macro_df       : pd.DataFrame with dxy/vix/yield_10y/yield_5y columns
        symbol         : instrument symbol for logging

        Returns
        -------
        SignalScore with composite score, grade, and per-dimension breakdown.
        """
        t0 = time.perf_counter()

        direction: str = str(signal_payload.get("direction", "NEUTRAL")).upper()

        # ── Dimension 1: ML Confidence ────────────────────────────────────────
        d_ml, ml_details = _score_ml_confidence(signal_payload, direction)

        # ── Dimension 2: Technical Consensus ─────────────────────────────────
        d_tech, tech_details = _score_technical_consensus(ohlcv, direction, signal_payload)

        # ── Dimension 3: Macro Alignment ──────────────────────────────────────
        d_macro, macro_details = _score_macro_alignment(macro_df, direction, symbol)

        # ── Dimension 4: Regime Suitability ───────────────────────────────────
        d_regime, regime_details = _score_regime_suitability(ohlcv, direction, signal_payload)

        # ── Dimension 5: MTF Confluence ───────────────────────────────────────
        d_mtf, mtf_details = _score_mtf_confluence(signal_payload, direction)

        # ── Dimension 6: Volatility Quality ──────────────────────────────────
        d_vol, vol_details = _score_volatility_quality(ohlcv, signal_payload)

        # ── Composite ─────────────────────────────────────────────────────────
        composite = (
            self._w_ml     * d_ml
            + self._w_tech   * d_tech
            + self._w_macro  * d_macro
            + self._w_regime * d_regime
            + self._w_mtf    * d_mtf
            + self._w_vol    * d_vol
        )
        composite = float(np.clip(composite, 0.0, 1.0))

        # ── Grade ─────────────────────────────────────────────────────────────
        if composite >= _STRONG_THRESHOLD:
            grade = "STRONG"
        elif composite >= _GOOD_THRESHOLD:
            grade = "GOOD"
        elif composite >= _FAIR_THRESHOLD:
            grade = "FAIR"
        else:
            grade = "WEAK"

        latency_ms = (time.perf_counter() - t0) * 1000

        dims = DimensionScores(
            ml_confidence=d_ml,
            technical=d_tech,
            macro_alignment=d_macro,
            regime=d_regime,
            mtf_confluence=d_mtf,
            volatility=d_vol,
            details={
                "ml": ml_details,
                "technical": tech_details,
                "macro": macro_details,
                "regime": regime_details,
                "mtf": mtf_details,
                "volatility": vol_details,
            },
        )

        result = SignalScore(
            composite=composite,
            grade=grade,
            dimensions=dims,
            direction=direction,
            symbol=symbol,
            latency_ms=latency_ms,
        )
        logger.debug("SignalScore: %s", result)
        return result


# ── Module-level singleton ────────────────────────────────────────────────────

_scorer: SignalScorer | None = None


def get_signal_scorer() -> SignalScorer:
    global _scorer
    if _scorer is None:
        _scorer = SignalScorer()
    return _scorer


def score_signal(
    signal_payload: dict[str, Any],
    ohlcv=None,
    macro_df=None,
    symbol: str = "UNKNOWN",
) -> SignalScore:
    """Convenience wrapper — compute signal score via the module singleton."""
    return get_signal_scorer().score(
        signal_payload=signal_payload,
        ohlcv=ohlcv,
        macro_df=macro_df,
        symbol=symbol,
    )
