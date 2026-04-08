# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/feature_builder.py
============================
Multi-timeframe feature builder for the Nuclear Strategy Engine.

Computes validated technical features from Redis OHLCV streams:
  - ATR(14)          — Average True Range, normalised
  - Bollinger Bands  — upper/lower/width/squeeze flag
  - RSI(14)          — Relative Strength Index
  - EMA(9/21/50/200) — Exponential Moving Averages
  - MACD             — 12/26/9 signal line
  - Volume delta     — buy/sell pressure from tick data

Macro features (from macro_channel via RedisStreamReader):
  - VIX              — CBOE Volatility Index
  - DXY              — US Dollar Index
  - SPX              — S&P 500 level
  - GLD              — Gold ETF proxy
  - US10Y            — 10-year Treasury yield

All computations use numpy/pandas only — no TA-Lib, no broker APIs.

Usage
-----
    from nuclear.feature_builder import FeatureBuilder
    from nuclear.redis_stream_reader import RedisStreamReader

    reader = RedisStreamReader()
    builder = FeatureBuilder(reader)

    features = builder.build_all()
    # features["daily"]["rsi"] → float
    # features["macro"]["vix"] → float
    # features["1h"]["bb_squeeze"] → bool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from nuclear.redis_stream_reader import MacroSnapshot, OHLCVBar, RedisStreamReader

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Indicator parameters ──────────────────────────────────────────────────────
_ATR_PERIOD = 14
_RSI_PERIOD = 14
_BB_PERIOD = 20
_BB_STD = 2.0
_EMA_PERIODS = [9, 21, 50, 200]
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_VOLUME_MA_PERIOD = 20

# Minimum bars needed per timeframe for reliable features
_MIN_BARS: dict[str, int] = {
    "1m": 30,
    "5m": 30,
    "30m": 30,
    "1h": 30,
    "daily": 50,
    "weekly": 20,
    "monthly": 12,
    "yearly": 3,
}


# ── Feature containers ────────────────────────────────────────────────────────


@dataclass
class TechnicalFeatures:
    """Technical indicator features for a single timeframe."""

    timeframe: str
    symbol: str
    bar_count: int
    current_price: float

    # ATR
    atr: float = 0.0
    atr_pct: float = 0.0  # ATR / price

    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_mid: float = 0.0
    bb_width: float = 0.0  # (upper - lower) / mid
    bb_pct_b: float = 0.5  # (price - lower) / (upper - lower)
    bb_squeeze: bool = False  # width < historical 20th percentile

    # RSI
    rsi: float = 50.0
    rsi_overbought: bool = False  # rsi > 70
    rsi_oversold: bool = False  # rsi < 30

    # EMAs
    ema_9: float = 0.0
    ema_21: float = 0.0
    ema_50: float = 0.0
    ema_200: float = 0.0
    price_above_ema_50: bool = False
    price_above_ema_200: bool = False
    ema_9_above_21: bool = False
    ema_21_above_50: bool = False
    golden_cross: bool = False  # ema_50 crossed above ema_200 recently
    death_cross: bool = False  # ema_50 crossed below ema_200 recently

    # MACD
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    macd_bullish: bool = False  # histogram > 0 and rising

    # Volume
    volume_ma: float = 0.0
    volume_ratio: float = 1.0  # current_vol / volume_ma
    volume_surge: bool = False  # ratio > 1.5

    # Trend
    trend_slope: float = 0.0  # linear regression slope of closes (normalised)
    higher_highs: bool = False
    lower_lows: bool = False

    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "bar_count": self.bar_count,
            "current_price": round(self.current_price, 4),
            "atr": round(self.atr, 4),
            "atr_pct": round(self.atr_pct, 6),
            "bb_upper": round(self.bb_upper, 4),
            "bb_lower": round(self.bb_lower, 4),
            "bb_mid": round(self.bb_mid, 4),
            "bb_width": round(self.bb_width, 6),
            "bb_pct_b": round(self.bb_pct_b, 4),
            "bb_squeeze": self.bb_squeeze,
            "rsi": round(self.rsi, 2),
            "rsi_overbought": self.rsi_overbought,
            "rsi_oversold": self.rsi_oversold,
            "ema_9": round(self.ema_9, 4),
            "ema_21": round(self.ema_21, 4),
            "ema_50": round(self.ema_50, 4),
            "ema_200": round(self.ema_200, 4),
            "price_above_ema_50": self.price_above_ema_50,
            "price_above_ema_200": self.price_above_ema_200,
            "ema_9_above_21": self.ema_9_above_21,
            "ema_21_above_50": self.ema_21_above_50,
            "golden_cross": self.golden_cross,
            "death_cross": self.death_cross,
            "macd_line": round(self.macd_line, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_histogram": round(self.macd_histogram, 4),
            "macd_bullish": self.macd_bullish,
            "volume_ma": round(self.volume_ma, 2),
            "volume_ratio": round(self.volume_ratio, 3),
            "volume_surge": self.volume_surge,
            "trend_slope": round(self.trend_slope, 6),
            "higher_highs": self.higher_highs,
            "lower_lows": self.lower_lows,
            "computed_at": self.computed_at.isoformat(),
        }


@dataclass
class MacroFeatures:
    """Macro environment features from macro_channel."""

    vix: float = 0.0
    dxy: float = 0.0
    spx: float = 0.0
    gld: float = 0.0
    us10y: float = 0.0

    # Derived
    risk_off: bool = False
    dollar_strong: bool = False
    gold_bullish_macro: bool = False  # risk_off + weak dollar
    gold_bearish_macro: bool = False  # risk_on + strong dollar
    vix_regime: str = "normal"  # "low" / "normal" / "elevated" / "crisis"
    yield_curve_pressure: str = "neutral"  # "rising" / "falling" / "neutral"

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "vix": round(self.vix, 2),
            "dxy": round(self.dxy, 3),
            "spx": round(self.spx, 2),
            "gld": round(self.gld, 2),
            "us10y": round(self.us10y, 3),
            "risk_off": self.risk_off,
            "dollar_strong": self.dollar_strong,
            "gold_bullish_macro": self.gold_bullish_macro,
            "gold_bearish_macro": self.gold_bearish_macro,
            "vix_regime": self.vix_regime,
            "yield_curve_pressure": self.yield_curve_pressure,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MultiTimeframeFeatures:
    """Complete feature set across all timeframes + macro."""

    symbol: str
    timeframes: dict[str, TechnicalFeatures]  # tf → features
    macro: MacroFeatures
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get(self, timeframe: str) -> TechnicalFeatures | None:
        return self.timeframes.get(timeframe)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframes": {tf: f.to_dict() for tf, f in self.timeframes.items()},
            "macro": self.macro.to_dict(),
            "computed_at": self.computed_at.isoformat(),
        }


# ── FeatureBuilder ────────────────────────────────────────────────────────────


class FeatureBuilder:
    """
    Builds validated technical + macro features from Redis stream data.

    Parameters
    ----------
    reader : RedisStreamReader
        Live data source. All data comes from Redis pub/sub.
    symbol : str
        Instrument symbol (default: "XAU_USD").
    """

    def __init__(
        self,
        reader: RedisStreamReader,
        symbol: str = "XAU_USD",
    ) -> None:
        self._reader = reader
        self._symbol = symbol

    # ── Public API ────────────────────────────────────────────────────────────

    def build_all(
        self,
        timeframes: list[str] | None = None,
        min_bars_override: dict[str, int] | None = None,
    ) -> MultiTimeframeFeatures:
        """
        Build features for all (or specified) timeframes plus macro.

        Parameters
        ----------
        timeframes : list[str], optional
            Subset of timeframes to compute. Defaults to all available.
        min_bars_override : dict, optional
            Override minimum bar requirements per timeframe.

        Returns
        -------
        MultiTimeframeFeatures
        """
        all_bars = self._reader.get_all_bars()
        macro_snap = self._reader.get_macro()
        min_bars = {**_MIN_BARS, **(min_bars_override or {})}

        tf_features: dict[str, TechnicalFeatures] = {}
        target_tfs = timeframes or list(all_bars.keys())

        for tf in target_tfs:
            bars = all_bars.get(tf, [])
            required = min_bars.get(tf, 30)
            if len(bars) < 2:
                logger.debug("FeatureBuilder: skipping %s — only %d bars", tf, len(bars))
                continue
            try:
                tf_features[tf] = self._build_tf_features(bars, tf, required)
            except Exception as exc:
                logger.error("FeatureBuilder error for %s: %s", tf, exc)

        macro = self._build_macro_features(macro_snap)

        return MultiTimeframeFeatures(
            symbol=self._symbol,
            timeframes=tf_features,
            macro=macro,
        )

    def build_timeframe(
        self,
        bars: list[OHLCVBar],
        timeframe: str,
    ) -> TechnicalFeatures:
        """Build features for a single timeframe from a bar list."""
        return self._build_tf_features(bars, timeframe, min_bars=2)

    # ── Internal builders ─────────────────────────────────────────────────────

    def _build_tf_features(
        self,
        bars: list[OHLCVBar],
        timeframe: str,
        min_bars: int = 30,
    ) -> TechnicalFeatures:
        """Compute all technical indicators for one timeframe."""
        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        volumes = np.array([b.volume for b in bars], dtype=float)
        n = len(closes)

        price = float(closes[-1])
        symbol = bars[-1].symbol if bars else self._symbol

        feat = TechnicalFeatures(
            timeframe=timeframe,
            symbol=symbol,
            bar_count=n,
            current_price=price,
        )

        if n < 2:
            return feat

        # ── ATR ───────────────────────────────────────────────────────────────
        period = min(_ATR_PERIOD, n - 1)
        atr = _compute_atr(highs, lows, closes, period)
        feat.atr = atr
        feat.atr_pct = atr / (price + 1e-9)

        # ── Bollinger Bands ───────────────────────────────────────────────────
        bb_period = min(_BB_PERIOD, n)
        if bb_period >= 2:
            bb_mid = float(np.mean(closes[-bb_period:]))
            bb_std = float(np.std(closes[-bb_period:], ddof=1))
            bb_upper = bb_mid + _BB_STD * bb_std
            bb_lower = bb_mid - _BB_STD * bb_std
            bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-9)
            bb_pct_b = (price - bb_lower) / (bb_upper - bb_lower + 1e-9)

            feat.bb_upper = bb_upper
            feat.bb_lower = bb_lower
            feat.bb_mid = bb_mid
            feat.bb_width = bb_width
            feat.bb_pct_b = float(np.clip(bb_pct_b, -0.5, 1.5))

            # Squeeze: current width < 20th percentile of rolling widths
            if n >= bb_period + 10:
                widths = []
                for i in range(bb_period, n + 1):
                    w_mid = float(np.mean(closes[i - bb_period : i]))
                    w_std = float(np.std(closes[i - bb_period : i], ddof=1))
                    widths.append((w_std * 2 * _BB_STD) / (w_mid + 1e-9))
                feat.bb_squeeze = bb_width < float(np.percentile(widths, 20))

        # ── RSI ───────────────────────────────────────────────────────────────
        rsi_period = min(_RSI_PERIOD, n - 1)
        if rsi_period >= 2:
            rsi = _compute_rsi(closes, rsi_period)
            feat.rsi = rsi
            feat.rsi_overbought = rsi > 70
            feat.rsi_oversold = rsi < 30

        # ── EMAs ──────────────────────────────────────────────────────────────
        emas: dict[int, float] = {}
        for p in _EMA_PERIODS:
            if n >= p:
                emas[p] = float(_ema(closes, p)[-1])
            elif n >= 2:
                emas[p] = float(_ema(closes, n)[-1])

        feat.ema_9 = emas.get(9, price)
        feat.ema_21 = emas.get(21, price)
        feat.ema_50 = emas.get(50, price)
        feat.ema_200 = emas.get(200, price)
        feat.price_above_ema_50 = price > feat.ema_50
        feat.price_above_ema_200 = price > feat.ema_200
        feat.ema_9_above_21 = feat.ema_9 > feat.ema_21
        feat.ema_21_above_50 = feat.ema_21 > feat.ema_50

        # Cross detection (last 3 bars)
        if n >= 53:
            ema50_prev = float(_ema(closes[:-1], 50)[-1])
            ema200_prev = float(_ema(closes[:-1], 200)[-1])
            feat.golden_cross = (feat.ema_50 > feat.ema_200) and (ema50_prev <= ema200_prev)
            feat.death_cross = (feat.ema_50 < feat.ema_200) and (ema50_prev >= ema200_prev)

        # ── MACD ──────────────────────────────────────────────────────────────
        if n >= _MACD_SLOW + _MACD_SIGNAL:
            ema_fast = _ema(closes, _MACD_FAST)
            ema_slow = _ema(closes, _MACD_SLOW)
            macd_line = ema_fast - ema_slow
            signal_line = _ema(macd_line, _MACD_SIGNAL)
            histogram = macd_line - signal_line

            feat.macd_line = float(macd_line[-1])
            feat.macd_signal = float(signal_line[-1])
            feat.macd_histogram = float(histogram[-1])
            feat.macd_bullish = (
                feat.macd_histogram > 0 and len(histogram) >= 2 and float(histogram[-1]) > float(histogram[-2])
            )

        # ── Volume ────────────────────────────────────────────────────────────
        vol_period = min(_VOLUME_MA_PERIOD, n)
        if vol_period >= 1 and volumes[-1] > 0:
            vol_ma = float(np.mean(volumes[-vol_period:]))
            vol_ratio = volumes[-1] / (vol_ma + 1e-9)
            feat.volume_ma = vol_ma
            feat.volume_ratio = vol_ratio
            feat.volume_surge = vol_ratio > 1.5

        # ── Trend slope ───────────────────────────────────────────────────────
        slope_period = min(20, n)
        if slope_period >= 3:
            x = np.arange(slope_period, dtype=float)
            y = closes[-slope_period:]
            slope = float(np.polyfit(x, y, 1)[0])
            feat.trend_slope = slope / (price + 1e-9)  # normalise

        # ── Higher highs / lower lows (last 5 bars) ───────────────────────────
        if n >= 5:
            recent_highs = highs[-5:]
            recent_lows = lows[-5:]
            feat.higher_highs = bool(recent_highs[-1] > recent_highs[-2] > recent_highs[-3])
            feat.lower_lows = bool(recent_lows[-1] < recent_lows[-2] < recent_lows[-3])

        return feat

    @staticmethod
    def _build_macro_features(snap: MacroSnapshot) -> MacroFeatures:
        """Derive macro regime features from a MacroSnapshot."""
        risk_off = snap.vix > 25.0 or snap.us10y > 5.0
        dollar_strong = snap.dxy > 105.0

        # VIX regime
        if snap.vix < 12:
            vix_regime = "low"
        elif snap.vix < 20:
            vix_regime = "normal"
        elif snap.vix < 30:
            vix_regime = "elevated"
        else:
            vix_regime = "crisis"

        # Yield curve pressure (simplified: high yield = pressure on gold)
        if snap.us10y > 4.5:
            yield_pressure = "rising"
        elif snap.us10y < 3.0:
            yield_pressure = "falling"
        else:
            yield_pressure = "neutral"

        # Gold macro bias
        gold_bullish = risk_off and not dollar_strong
        gold_bearish = not risk_off and dollar_strong

        return MacroFeatures(
            vix=snap.vix,
            dxy=snap.dxy,
            spx=snap.spx,
            gld=snap.gld,
            us10y=snap.us10y,
            risk_off=risk_off,
            dollar_strong=dollar_strong,
            gold_bullish_macro=gold_bullish,
            gold_bearish_macro=gold_bearish,
            vix_regime=vix_regime,
            yield_curve_pressure=yield_pressure,
            timestamp=snap.timestamp,
        )


# ── Pure numpy indicator implementations ──────────────────────────────────────


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average — Wilder smoothing (alpha = 2/(n+1))."""
    alpha = 2.0 / (period + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1.0 - alpha) * result[i - 1]
    return result


def _compute_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
) -> float:
    """Average True Range over the last `period` bars."""
    if len(highs) < 2:
        return float(highs[-1] - lows[-1]) if len(highs) == 1 else 0.0
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _compute_rsi(closes: np.ndarray, period: int) -> float:
    """Wilder RSI."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial averages
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # Wilder smoothing for remaining bars
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


# ── Convenience function ──────────────────────────────────────────────────────


def build_features_from_bars(
    bars_by_tf: dict[str, list[OHLCVBar]],
    macro: MacroSnapshot | None = None,
    symbol: str = "XAU_USD",
) -> MultiTimeframeFeatures:
    """
    Build MultiTimeframeFeatures directly from bar dicts without a reader.

    Useful for backtesting and unit tests where a live reader is not available.
    """

    # Create a minimal reader-like object
    class _StaticReader:
        def get_all_bars(self):
            return bars_by_tf

        def get_macro(self):
            return macro or MacroSnapshot()

    builder = FeatureBuilder(_StaticReader(), symbol=symbol)  # type: ignore[arg-type]
    return builder.build_all()
