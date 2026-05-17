# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Bollinger Bands Trading Strategy

This strategy uses Bollinger Bands for identifying trend strength
and potential reversals.
"""

import logging
from datetime import datetime, timezone

import numpy as np

UTC = timezone.utc
from typing import Any

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)


class BollingerBandsStrategy(BaseStrategy):
    """
    Bollinger Bands trading strategy.

    Combines band touches with band squeeze for signal generation.
    """

    def __init__(
        self,
        config: StrategyConfig,
        *_args,
        period: int = 20,
        std_dev: float = 2.0,
    ):
        """
        Initialize Bollinger Bands strategy.

        Args:
            config: StrategyConfig with name, symbol, timeframe
            period: Moving average period
            std_dev: Standard deviation multiplier
        """
        super().__init__(config)
        self.period = period
        self.std_dev = std_dev
        logger.info("Bollinger Bands Strategy initialized: period=%s, std_dev=%s", period, std_dev)

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """Compute Bollinger Bands from OHLCV data dict."""
        prices = data.get("prices") or data.get("close")
        if prices is None:
            return {"upper": None, "lower": None, "sma": None, "price": None}
        series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
        sma = series.rolling(window=self.period).mean()
        std = series.rolling(window=self.period).std().fillna(0.0)
        upper = sma + std * self.std_dev
        lower = sma - std * self.std_dev
        price = float(np.nan_to_num(series.iloc[-1], nan=0.0))
        prev_price = float(np.nan_to_num(series.iloc[-2], nan=price)) if len(series) > 1 else price
        return {
            "upper": float(np.nan_to_num(upper.iloc[-1], nan=0.0)) if not upper.empty else None,
            "lower": float(np.nan_to_num(lower.iloc[-1], nan=0.0)) if not lower.empty else None,
            "sma": float(np.nan_to_num(sma.iloc[-1], nan=0.0)) if not sma.empty else None,
            "price": price,
            "prev_price": prev_price,
            "prev_upper": float(np.nan_to_num(upper.iloc[-2], nan=0.0)) if len(upper) > 1 else None,
            "prev_lower": float(np.nan_to_num(lower.iloc[-2], nan=0.0)) if len(lower) > 1 else None,
        }

    def generate_signal(self, analysis):  # type: ignore[override]
        """Generate trading signal.

        Accepts either:
        - ``pd.DataFrame`` — delegates to ``_generate_dict_signal()`` and returns
          a ``dict[str, Any]`` with keys ``type``, ``confidence``, ``reason``,
          ``timestamp``, and ``metadata``.  This is the path used by backtesting,
          hyperopt, and all DataFrame-based callers.
        - ``dict`` (from ``analyze()``) — returns ``Signal | None`` per the
          ``BaseStrategy`` abstract contract.
        """
        if isinstance(analysis, pd.DataFrame):
            return self._generate_dict_signal(analysis)
        # dict path — BaseStrategy abstract method contract
        upper = analysis.get("upper")
        lower = analysis.get("lower")
        price = analysis.get("price")
        prev_price = analysis.get("prev_price", price)
        if any(v is None for v in (upper, lower, price)):
            return None
        if price < lower:
            conf = 0.85 if price > prev_price else 0.70
            return Signal(
                SignalType.BUY,
                self.config.symbol,
                price,
                datetime.now(UTC),
                confidence=conf,
            )
        if price > upper:
            conf = 0.85 if price < prev_price else 0.70
            return Signal(
                SignalType.SELL,
                self.config.symbol,
                price,
                datetime.now(UTC),
                confidence=conf,
            )
        return None

    def _generate_dict_signal(self, market_data: pd.DataFrame) -> dict[str, Any]:
        """Generate dict-style signal from OHLCV DataFrame (used by backtesting)."""
        try:
            if len(market_data) < self.period:
                return {
                    "type": "HOLD",
                    "confidence": 0.0,
                    "reason": "Insufficient data",
                    "timestamp": datetime.now(UTC),
                }

            close = market_data["close"]

            # Calculate Bollinger Bands
            sma = close.rolling(window=self.period).mean()
            std = close.rolling(window=self.period).std().fillna(0.0)
            upper_band = sma + (std * self.std_dev)
            lower_band = sma - (std * self.std_dev)

            # Current values
            current_price = close.iloc[-1]
            current_upper = upper_band.iloc[-1]
            current_lower = lower_band.iloc[-1]
            current_sma = sma.iloc[-1]
            current_std = std.iloc[-1]

            # Previous values for trend detection
            prev_price = close.iloc[-2]
            prev_upper = upper_band.iloc[-2]
            prev_lower = lower_band.iloc[-2]

            # Calculate %B (position within bands)
            band_width = current_upper - current_lower
            if band_width == 0:
                return {"type": "HOLD", "confidence": 0.0, "reason": "Zero band width"}

            percent_b = (current_price - current_lower) / band_width

            # Calculate band squeeze (volatility)
            avg_std = (
                float(np.nan_to_num(std.rolling(window=50).mean().iloc[-1], nan=current_std))
                if len(std) >= 50
                else current_std
            )
            is_squeeze = (
                current_std < avg_std * 0.75
                if avg_std > 0 and float("-inf") < current_std < float("inf") and float("-inf") < avg_std < float("inf")
                else False
            )

            signal_type = "HOLD"
            confidence = 0.0
            reason = ""

            # BUY signals
            if current_price < current_lower:
                # Price below lower band - oversold
                signal_type = "BUY"
                confidence = 0.7
                reason = "Price below lower Bollinger Band (oversold)"

                # Higher confidence if bouncing back
                if current_price > prev_price:
                    confidence = 0.85
                    reason += " with bounce"

            elif prev_price < prev_lower and current_price > current_lower:
                # Price crossing back above lower band
                signal_type = "BUY"
                confidence = 0.75
                reason = "Price crossing above lower band"

            elif is_squeeze and current_price > current_sma:
                # Band squeeze breakout to upside
                signal_type = "BUY"
                confidence = 0.65
                reason = "Bollinger Band squeeze breakout (bullish)"

            # SELL signals
            elif current_price > current_upper:
                # Price above upper band - overbought
                signal_type = "SELL"
                confidence = 0.7
                reason = "Price above upper Bollinger Band (overbought)"

                # Higher confidence if turning down
                if current_price < prev_price:
                    confidence = 0.85
                    reason += " with reversal"

            elif prev_price > prev_upper and current_price < current_upper:
                # Price crossing back below upper band
                signal_type = "SELL"
                confidence = 0.75
                reason = "Price crossing below upper band"

            elif is_squeeze and current_price < current_sma:
                # Band squeeze breakout to downside
                signal_type = "SELL"
                confidence = 0.65
                reason = "Bollinger Band squeeze breakout (bearish)"

            # Walking the bands
            elif percent_b > 0.9 and current_price > current_sma:
                # Walking the upper band (strong uptrend)
                signal_type = "BUY"
                confidence = 0.55
                reason = "Walking upper band (strong uptrend)"

            elif percent_b < 0.1 and current_price < current_sma:
                # Walking the lower band (strong downtrend)
                signal_type = "SELL"
                confidence = 0.55
                reason = "Walking lower band (strong downtrend)"

            else:
                reason = f"Price within bands: %B = {percent_b:.2f}"

            return {
                "type": signal_type,
                "confidence": confidence,
                "reason": reason,
                "timestamp": datetime.now(UTC),
                "metadata": {
                    "price": current_price,
                    "upper_band": current_upper,
                    "lower_band": current_lower,
                    "sma": current_sma,
                    "percent_b": percent_b,
                    "band_width": band_width,
                    "is_squeeze": is_squeeze,
                },
            }

        except Exception as e:
            self.logger.error("Error generating Bollinger Bands signal: %s", e)

            return {
                "type": "HOLD",
                "confidence": 0.0,
                "reason": f"Error: {e!s}",
                "timestamp": datetime.now(UTC),
            }
