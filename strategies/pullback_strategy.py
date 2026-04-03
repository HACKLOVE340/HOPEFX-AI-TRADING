# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
strategies/pullback_strategy.py
================================
Trend-following pullback strategy — retail-friendly, high-probability.

Strategy logic
--------------
Enter on a pullback into a confirmed trend, not at the breakout.
This gives a better risk/reward than chasing momentum and is the
core of most institutional trend-following approaches.

Entry conditions (LONG)
-----------------------
1. Trend filter: EMA(50) > EMA(200) AND ADX(14) > ADX_MIN (default 20)
   — confirms we are in a trending, not ranging, market
2. Pullback: price retraces to within ATR_PULLBACK_MULT × ATR(14) of
   EMA(50) from above — price has pulled back to the trend line
3. Momentum turn: RSI(14) was below RSI_OVERSOLD (default 40) and is
   now rising — momentum exhaustion and reversal
4. Volume confirmation: current bar volume > VOL_CONFIRM_MULT × 20-bar
   average volume — institutional participation on the reversal bar
5. VWAP filter (optional): price above 20-bar VWAP — institutional
   reference level confirms bullish bias

Entry conditions (SHORT) — mirror image of LONG.

Exit logic
----------
- Stop loss: entry ± SL_ATR_MULT × ATR(14) (default 1.5×)
- Take profit: entry ± TP_ATR_MULT × ATR(14) (default 3.0×)
  → default R:R = 2:1
- Trailing stop: once price moves TP_ATR_MULT × ATR in favour,
  trail stop to breakeven + 0.5 × ATR

All parameters are env-configurable without restart.

Usage
-----
    from strategies.pullback_strategy import PullbackStrategy

    strategy = PullbackStrategy(name="pullback_xauusd", symbol="XAU_USD", config=cfg)
    signal = strategy.generate_signal(ohlcv_df)
    # signal = {"signal_type": "BUY", "confidence": 0.78, "stop_loss": ..., ...}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)

# ── Strategy parameters (env-configurable) ────────────────────────────────────
_EMA_FAST = int(os.getenv("PULLBACK_EMA_FAST", "50"))
_EMA_SLOW = int(os.getenv("PULLBACK_EMA_SLOW", "200"))
_ADX_PERIOD = int(os.getenv("PULLBACK_ADX_PERIOD", "14"))
_ADX_MIN = float(os.getenv("PULLBACK_ADX_MIN", "20"))  # min trend strength
_RSI_PERIOD = int(os.getenv("PULLBACK_RSI_PERIOD", "14"))
_RSI_OVERSOLD = float(os.getenv("PULLBACK_RSI_OVERSOLD", "40"))  # long entry zone
_RSI_OVERBOUGHT = float(os.getenv("PULLBACK_RSI_OVERBOUGHT", "60"))  # short entry zone
_ATR_PERIOD = int(os.getenv("PULLBACK_ATR_PERIOD", "14"))
_ATR_PULLBACK_MULT = float(os.getenv("PULLBACK_ATR_PULLBACK_MULT", "1.5"))  # max pullback depth
_SL_ATR_MULT = float(os.getenv("PULLBACK_SL_ATR_MULT", "1.5"))
_TP_ATR_MULT = float(os.getenv("PULLBACK_TP_ATR_MULT", "3.0"))
_VOL_CONFIRM_MULT = float(os.getenv("PULLBACK_VOL_CONFIRM_MULT", "1.2"))  # vol > 1.2× avg
_VWAP_FILTER = os.getenv("PULLBACK_VWAP_FILTER", "true").lower() == "true"
_MIN_BARS = int(os.getenv("PULLBACK_MIN_BARS", "220"))  # need 200 bars for EMA(200)
_MIN_CONFIDENCE = float(os.getenv("PULLBACK_MIN_CONFIDENCE", "0.60"))


class PullbackStrategy(BaseStrategy):
    """
    Trend-following pullback strategy.

    Enters on confirmed pullbacks into an established trend.
    Uses EMA trend filter, ADX strength filter, RSI momentum turn,
    and volume confirmation to produce high-probability entries.

    Parameters (all env-configurable)
    ----------------------------------
    PULLBACK_EMA_FAST          : Fast EMA period (default 50)
    PULLBACK_EMA_SLOW          : Slow EMA period (default 200)
    PULLBACK_ADX_MIN           : Minimum ADX for trend confirmation (default 20)
    PULLBACK_RSI_OVERSOLD      : RSI level for long entry zone (default 40)
    PULLBACK_RSI_OVERBOUGHT    : RSI level for short entry zone (default 60)
    PULLBACK_ATR_PULLBACK_MULT : Max pullback depth in ATR units (default 1.5)
    PULLBACK_SL_ATR_MULT       : Stop loss distance in ATR (default 1.5)
    PULLBACK_TP_ATR_MULT       : Take profit distance in ATR (default 3.0)
    PULLBACK_VOL_CONFIRM_MULT  : Volume confirmation multiplier (default 1.2)
    PULLBACK_VWAP_FILTER       : Require price above/below VWAP (default true)
    """

    def __init__(
        self,
        config: StrategyConfig | None = None,
        *,
        name: str = "pullback",
        symbol: str = "XAU_USD",
        ema_fast: int = _EMA_FAST,
        ema_slow: int = _EMA_SLOW,
        adx_min: float = _ADX_MIN,
        rsi_oversold: float = _RSI_OVERSOLD,
        rsi_overbought: float = _RSI_OVERBOUGHT,
        atr_pullback_mult: float = _ATR_PULLBACK_MULT,
        sl_atr_mult: float = _SL_ATR_MULT,
        tp_atr_mult: float = _TP_ATR_MULT,
        vol_confirm_mult: float = _VOL_CONFIRM_MULT,
        vwap_filter: bool = _VWAP_FILTER,
    ) -> None:
        # Build a StrategyConfig if one wasn't supplied
        if config is None:
            config = StrategyConfig(
                name=name,
                symbol=symbol,
                timeframe="H1",
                risk_per_trade=1.0,
            )
        super().__init__(config)
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_min = adx_min
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_pullback_mult = atr_pullback_mult
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.vol_confirm_mult = vol_confirm_mult
        self.vwap_filter = vwap_filter
        self._bar_buffer: list = []

        logger.info(
            "PullbackStrategy '%s' initialised: symbol=%s ema=%d/%d adx_min=%.0f "
            "rsi_zone=[%.0f,%.0f] sl=%.1f×ATR tp=%.1f×ATR vwap_filter=%s",
            self.name,
            self.symbol,
            ema_fast,
            ema_slow,
            adx_min,
            rsi_oversold,
            rsi_overbought,
            sl_atr_mult,
            tp_atr_mult,
            vwap_filter,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_signal(self, analysis: pd.DataFrame) -> dict[str, Any]:  # type: ignore[override]
        market_data = analysis
        """
        Analyse OHLCV data and return a signal dict.

        Parameters
        ----------
        market_data : DataFrame with columns [open, high, low, close, volume]
                      and a DatetimeIndex. Minimum _MIN_BARS rows required.

        Returns
        -------
        dict with keys:
          signal_type  : "BUY" | "SELL" | "HOLD"
          confidence   : float [0, 1]
          entry_price  : float
          stop_loss    : float
          take_profit  : float
          reason       : str — human-readable explanation
          indicators   : dict — all computed indicator values for debugging
          symbol       : str
          timestamp    : ISO string
        """
        now_iso = datetime.now(UTC).isoformat()
        hold = {
            "signal_type": "HOLD",
            "confidence": 0.0,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "reason": "insufficient data",
            "indicators": {},
            "symbol": self.symbol,
            "timestamp": now_iso,
        }

        df = self._prepare(market_data)
        if df is None or len(df) < _MIN_BARS:
            hold["reason"] = f"need {_MIN_BARS} bars, got {len(market_data) if market_data is not None else 0}"
            return hold

        indicators = self._compute_indicators(df)
        if indicators is None:
            hold["reason"] = "indicator computation failed"
            return hold

        signal_type, confidence, reason = self._evaluate_conditions(indicators)

        if signal_type == "HOLD":
            return {**hold, "reason": reason, "indicators": indicators}

        entry = indicators["last_close"]
        atr = indicators["atr"]

        if signal_type == "BUY":
            stop_loss = round(entry - self.sl_atr_mult * atr, 5)
            take_profit = round(entry + self.tp_atr_mult * atr, 5)
        else:  # SELL
            stop_loss = round(entry + self.sl_atr_mult * atr, 5)
            take_profit = round(entry - self.tp_atr_mult * atr, 5)

        return {
            "signal_type": signal_type,
            "confidence": round(confidence, 4),
            "entry_price": round(entry, 5),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": reason,
            "indicators": indicators,
            "symbol": self.symbol,
            "timestamp": now_iso,
            # Fields expected by TradeExecutor
            "action": "buy" if signal_type == "BUY" else "sell",
            "price": round(entry, 5),
            "size": 0,  # sized by RiskManager.filter_signals()
        }

    def analyze(self, data: pd.DataFrame) -> dict[str, Any]:  # type: ignore[override]
        """Alias for generate_signal — satisfies BaseStrategy ABC."""
        return self.generate_signal(data)

    def on_bar(self, bar: dict[str, Any]) -> Signal | None:
        """
        Process a single new bar and return a Signal if conditions are met.

        Builds a minimal DataFrame from the bar dict and delegates to
        generate_signal().  Returns None when no signal is generated.
        """
        # Accumulate bars in internal buffer
        self._bar_buffer.append(bar)
        # Keep only the last _MIN_BARS + 50 bars to bound memory
        if len(self._bar_buffer) > _MIN_BARS + 50:
            self._bar_buffer = self._bar_buffer[-(_MIN_BARS + 50) :]

        if len(self._bar_buffer) < _MIN_BARS:
            return None

        df = pd.DataFrame(self._bar_buffer)
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        df.columns = [c.lower() for c in df.columns]

        result = self.generate_signal(df)
        if result["signal_type"] == "HOLD":
            return None

        return Signal(
            signal_type=SignalType[result["signal_type"]],
            symbol=self.symbol,
            price=result["entry_price"],
            timestamp=datetime.now(UTC),
            confidence=result["confidence"],
            metadata={
                "stop_loss": result["stop_loss"],
                "take_profit": result["take_profit"],
                "reason": result["reason"],
                "indicators": result["indicators"],
            },
        )

    # ── Indicator computation ─────────────────────────────────────────────────

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Normalise column names and validate required columns."""
        try:
            d = df.copy()
            d.columns = [c.lower() for c in d.columns]
            required = {"open", "high", "low", "close"}
            if not required.issubset(d.columns):
                logger.debug(
                    "PullbackStrategy: missing columns %s",
                    required - set(d.columns),
                )
                return None
            if "volume" not in d.columns:
                d["volume"] = 0.0
            return d.dropna(subset=["open", "high", "low", "close"])
        except Exception as exc:
            logger.debug("PullbackStrategy._prepare failed: %s", exc)
            return None

    def _compute_indicators(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Compute all indicators needed for entry condition evaluation.

        Returns a flat dict of scalar values for the most recent bar.
        Returns None on any computation failure.
        """
        try:
            c = df["close"]
            h = df["high"]
            l = df["low"]
            v = df["volume"]

            # ── EMAs ──────────────────────────────────────────────────────────
            ema_fast = c.ewm(span=self.ema_fast, adjust=False).mean()
            ema_slow = c.ewm(span=self.ema_slow, adjust=False).mean()

            # ── ATR(14) ───────────────────────────────────────────────────────
            atr = self._atr(h, l, c, _ATR_PERIOD)

            # ── ADX(14) ───────────────────────────────────────────────────────
            adx = self._adx(h, l, c, _ADX_PERIOD)

            # ── RSI(14) ───────────────────────────────────────────────────────
            rsi = self._rsi(c, _RSI_PERIOD)

            # ── Volume MA(20) ─────────────────────────────────────────────────
            vol_ma20 = v.rolling(20).mean()

            # ── VWAP(20) ──────────────────────────────────────────────────────
            typical = (h + l + c) / 3.0
            vwap_num = (typical * v.replace(0, np.nan).fillna(0)).rolling(20).sum()
            vwap_den = v.replace(0, np.nan).fillna(0).rolling(20).sum().replace(0, np.nan)
            vwap_20 = (vwap_num / vwap_den).fillna(c)

            # ── Swing high/low (20-bar) ───────────────────────────────────────
            swing_high_20 = h.rolling(20).max()
            swing_low_20 = l.rolling(20).min()

            # ── Last bar values ───────────────────────────────────────────────
            last_close = float(c.iloc[-1])
            last_ema_fast = float(ema_fast.iloc[-1])
            last_ema_slow = float(ema_slow.iloc[-1])
            last_atr = float(atr.iloc[-1])
            last_adx = float(adx.iloc[-1])
            last_rsi = float(rsi.iloc[-1])
            prev_rsi = float(rsi.iloc[-2]) if len(rsi) >= 2 else last_rsi
            last_vol = float(v.iloc[-1])
            last_vol_ma = float(vol_ma20.iloc[-1]) if not np.isnan(vol_ma20.iloc[-1]) else 1.0
            last_vwap = float(vwap_20.iloc[-1])
            last_swing_high = float(swing_high_20.iloc[-1])
            last_swing_low = float(swing_low_20.iloc[-1])

            # Pullback depth: distance from EMA_fast to close, in ATR units
            pullback_depth_long = (last_ema_fast - last_close) / last_atr if last_atr > 0 else 0.0
            pullback_depth_short = (last_close - last_ema_fast) / last_atr if last_atr > 0 else 0.0

            return {
                "last_close": last_close,
                "ema_fast": last_ema_fast,
                "ema_slow": last_ema_slow,
                "atr": last_atr,
                "adx": last_adx,
                "rsi": last_rsi,
                "prev_rsi": prev_rsi,
                "volume": last_vol,
                "vol_ma20": last_vol_ma,
                "vwap_20": last_vwap,
                "swing_high_20": last_swing_high,
                "swing_low_20": last_swing_low,
                "pullback_depth_long": pullback_depth_long,
                "pullback_depth_short": pullback_depth_short,
                "trend_bull": last_ema_fast > last_ema_slow,
                "trend_bear": last_ema_fast < last_ema_slow,
                "above_vwap": last_close > last_vwap,
                "vol_confirmed": last_vol > last_vol_ma * self.vol_confirm_mult,
            }

        except Exception as exc:
            logger.debug("PullbackStrategy._compute_indicators failed: %s", exc)
            return None

    def _evaluate_conditions(self, ind: dict[str, Any]) -> tuple:
        """
        Evaluate entry conditions and return (signal_type, confidence, reason).

        Confidence is built additively: each condition that passes adds weight.
        The final confidence is normalised to [0, 1].
        """
        # ── LONG conditions ───────────────────────────────────────────────────
        long_score = 0.0
        long_reasons = []

        # 1. Trend filter (weight 0.30)
        if ind["trend_bull"]:
            long_score += 0.30
            long_reasons.append("EMA50>EMA200")
        else:
            return "HOLD", 0.0, "no bull trend (EMA50 < EMA200)"

        # 2. ADX trend strength (weight 0.20)
        if ind["adx"] >= self.adx_min:
            long_score += 0.20
            long_reasons.append(f"ADX={ind['adx']:.1f}>={self.adx_min:.0f}")
        else:
            return (
                "HOLD",
                0.0,
                f"trend too weak: ADX={ind['adx']:.1f} < {self.adx_min:.0f}",
            )

        # 3. Pullback to EMA_fast (weight 0.25)
        # Price must be within ATR_PULLBACK_MULT × ATR of EMA_fast from above
        pb = ind["pullback_depth_long"]
        if 0.0 <= pb <= self.atr_pullback_mult:
            long_score += 0.25
            long_reasons.append(f"pullback={pb:.2f}×ATR")
        else:
            return (
                "HOLD",
                0.0,
                f"no pullback: depth={pb:.2f}×ATR (need 0–{self.atr_pullback_mult})",
            )

        # 4. RSI momentum turn (weight 0.15)
        # RSI was in oversold zone and is now rising
        if ind["prev_rsi"] < self.rsi_oversold and ind["rsi"] > ind["prev_rsi"]:
            long_score += 0.15
            long_reasons.append(f"RSI turn up ({ind['prev_rsi']:.1f}→{ind['rsi']:.1f})")
        elif ind["rsi"] < self.rsi_oversold:
            long_score += 0.08  # partial credit — still in zone
            long_reasons.append(f"RSI oversold ({ind['rsi']:.1f})")
        else:
            return "HOLD", 0.0, f"RSI not in pullback zone: {ind['rsi']:.1f}"

        # 5. Volume confirmation (weight 0.10)
        if ind["vol_confirmed"]:
            long_score += 0.10
            long_reasons.append(f"vol={ind['volume']:.0f}>{self.vol_confirm_mult:.1f}×avg")

        # 6. VWAP filter (optional, weight 0.05 bonus)
        if self.vwap_filter:
            if ind["above_vwap"]:
                long_score += 0.05
                long_reasons.append("above VWAP")
            else:
                return "HOLD", 0.0, "below VWAP (long filter)"

        if long_score >= _MIN_CONFIDENCE:
            return "BUY", min(long_score, 1.0), " | ".join(long_reasons)

        # ── SHORT conditions ──────────────────────────────────────────────────
        short_score = 0.0
        short_reasons = []

        # 1. Trend filter
        if ind["trend_bear"]:
            short_score += 0.30
            short_reasons.append("EMA50<EMA200")
        else:
            return "HOLD", 0.0, "no bear trend"

        # 2. ADX
        if ind["adx"] >= self.adx_min:
            short_score += 0.20
            short_reasons.append(f"ADX={ind['adx']:.1f}>={self.adx_min:.0f}")
        else:
            return "HOLD", 0.0, f"trend too weak: ADX={ind['adx']:.1f}"

        # 3. Pullback to EMA_fast from below
        pb = ind["pullback_depth_short"]
        if 0.0 <= pb <= self.atr_pullback_mult:
            short_score += 0.25
            short_reasons.append(f"pullback={pb:.2f}×ATR")
        else:
            return "HOLD", 0.0, f"no pullback: depth={pb:.2f}×ATR"

        # 4. RSI momentum turn
        if ind["prev_rsi"] > self.rsi_overbought and ind["rsi"] < ind["prev_rsi"]:
            short_score += 0.15
            short_reasons.append(f"RSI turn down ({ind['prev_rsi']:.1f}→{ind['rsi']:.1f})")
        elif ind["rsi"] > self.rsi_overbought:
            short_score += 0.08
            short_reasons.append(f"RSI overbought ({ind['rsi']:.1f})")
        else:
            return "HOLD", 0.0, f"RSI not in pullback zone: {ind['rsi']:.1f}"

        # 5. Volume confirmation
        if ind["vol_confirmed"]:
            short_score += 0.10
            short_reasons.append(f"vol={ind['volume']:.0f}>{self.vol_confirm_mult:.1f}×avg")

        # 6. VWAP filter
        if self.vwap_filter:
            if not ind["above_vwap"]:
                short_score += 0.05
                short_reasons.append("below VWAP")
            else:
                return "HOLD", 0.0, "above VWAP (short filter)"

        if short_score >= _MIN_CONFIDENCE:
            return "SELL", min(short_score, 1.0), " | ".join(short_reasons)

        return "HOLD", 0.0, "conditions not met"

    # ── Technical indicator helpers ───────────────────────────────────────────

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Average True Range."""
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(period).mean().fillna(tr)

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        """Relative Strength Index."""
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean().replace(0, np.nan)
        rs = gain / loss
        return (100 - 100 / (1 + rs)).fillna(50.0)

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """
        Average Directional Index (Wilder smoothing).

        Returns ADX values in [0, 100].  Values > 25 indicate a trending market.
        """
        prev_high = high.shift(1)
        prev_low = low.shift(1)
        prev_close = close.shift(1)

        # True Range
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Directional movement
        dm_plus = (high - prev_high).clip(lower=0)
        dm_minus = (prev_low - low).clip(lower=0)
        # When both are positive, keep only the larger
        both_pos = (dm_plus > 0) & (dm_minus > 0)
        dm_plus = dm_plus.where(~both_pos | (dm_plus >= dm_minus), 0.0)
        dm_minus = dm_minus.where(~both_pos | (dm_minus > dm_plus), 0.0)

        # Wilder smoothing
        atr_w = tr.ewm(alpha=1 / period, adjust=False).mean()
        di_plus = 100 * dm_plus.ewm(alpha=1 / period, adjust=False).mean() / atr_w.replace(0, np.nan)
        di_minus = 100 * dm_minus.ewm(alpha=1 / period, adjust=False).mean() / atr_w.replace(0, np.nan)

        dx_denom = (di_plus + di_minus).replace(0, np.nan)
        dx = 100 * (di_plus - di_minus).abs() / dx_denom
        adx = dx.ewm(alpha=1 / period, adjust=False).mean()
        return adx.fillna(0.0)
