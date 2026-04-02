# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
cognitive_engine.py
HOPEFX AI Trading – Cognitive Engine

Provides analytical building blocks for intelligent trading decisions:
trend analysis, momentum, volatility assessment, support/resistance detection,
and (optionally) sentiment analysis.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CognitiveEngine:
    """
    Lightweight cognitive engine that combines multiple analytical techniques
    to produce a composite view of market conditions.

    Args:
        data: OHLCV DataFrame with columns ['open','high','low','close','volume'].
              The index must be a DatetimeIndex (or similar time-ordered index).
    """

    def __init__(self, data: pd.DataFrame) -> None:
        if data is None or data.empty:
            raise ValueError("data must be a non-empty DataFrame")
        self.data = data.copy()
        self.trends: list[str] = []
        self.momentum: float | None = None
        self.volatility: float | None = None
        self.support: float | None = None
        self.resistance: float | None = None
        self.sentiment: float | None = None

    # ------------------------------------------------------------------ #
    # Public analysis methods                                              #
    # ------------------------------------------------------------------ #

    def analyze_trend(self, short_window: int = 9, long_window: int = 21) -> str:
        """
        Determine trend direction using two EMAs.

        Returns:
            "uptrend", "downtrend", or "sideways"
        """
        close = self.data["close"] if "close" in self.data.columns else self.data.iloc[:, 3]
        ema_short = close.ewm(span=short_window, adjust=False).mean()
        ema_long = close.ewm(span=long_window, adjust=False).mean()

        last_short = ema_short.iloc[-1]
        last_long = ema_long.iloc[-1]
        margin = last_long * 0.001  # 0.1 % band

        if last_short > last_long + margin:
            trend = "uptrend"
        elif last_short < last_long - margin:
            trend = "downtrend"
        else:
            trend = "sideways"

        self.trends.append(trend)
        logger.debug(
            "analyze_trend: %s (ema%d=%.4f, ema%d=%.4f)",
            trend,
            short_window,
            last_short,
            long_window,
            last_long,
        )
        return trend

    def calculate_momentum(self, period: int = 14) -> float:
        """
        Compute RSI-based momentum (0–100 scale, centred at 50).

        Returns:
            RSI value as a float.
        """
        close = self.data["close"] if "close" in self.data.columns else self.data.iloc[:, 3]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        self.momentum = float(rsi.iloc[-1]) if not rsi.empty else 50.0
        logger.debug("calculate_momentum: RSI=%.2f", self.momentum)
        return self.momentum

    def assess_volatility(self, period: int = 20) -> float:
        """
        Measure volatility using Bollinger Band width (relative to mid band).

        Returns:
            Band-width ratio (higher → more volatile).
        """
        close = self.data["close"] if "close" in self.data.columns else self.data.iloc[:, 3]
        rolling_mean = close.rolling(period).mean()
        rolling_std = close.rolling(period).std()
        upper = rolling_mean + 2 * rolling_std
        lower = rolling_mean - 2 * rolling_std
        band_width = (upper - lower) / rolling_mean
        self.volatility = float(band_width.iloc[-1]) if not band_width.empty else 0.0
        logger.debug("assess_volatility: band_width=%.4f", self.volatility)
        return self.volatility

    def detect_support_resistance(self, lookback: int = 50) -> tuple[float, float]:
        """
        Identify support and resistance using rolling min/max.

        Returns:
            (support_level, resistance_level) as floats.
        """
        window = self.data.tail(lookback)
        low_col = "low" if "low" in window.columns else window.columns[2]
        high_col = "high" if "high" in window.columns else window.columns[1]
        self.support = float(window[low_col].min())
        self.resistance = float(window[high_col].max())
        logger.debug(
            "detect_support_resistance: support=%.4f, resistance=%.4f",
            self.support,
            self.resistance,
        )
        return self.support, self.resistance

    def perform_sentiment_analysis(self, sentiment_score: float | None = None) -> float:
        """
        Integrate external sentiment score (−1 = very bearish, +1 = very bullish).

        If no external score is provided a neutral value (0.0) is assumed.

        Args:
            sentiment_score: Pre-computed sentiment score from a news/social feed.

        Returns:
            Clamped sentiment score in [−1, 1].
        """
        if sentiment_score is None:
            self.sentiment = 0.0
        else:
            self.sentiment = max(-1.0, min(1.0, float(sentiment_score)))
        logger.debug("perform_sentiment_analysis: sentiment=%.4f", self.sentiment)
        return self.sentiment

    def composite_signal(self) -> dict[str, object]:
        """
        Run all analyses and return a consolidated signal dictionary.

        Returns:
            Dict with keys: trend, momentum, volatility, support,
            resistance, sentiment, signal_strength.
        """
        trend = self.analyze_trend()
        momentum = self.calculate_momentum()
        volatility = self.assess_volatility()
        support, resistance = self.detect_support_resistance()

        # Compute a simple signal strength in [0, 1]
        bullish = (trend == "uptrend") and (momentum > 55)  # noqa: PLR2004
        bearish = (trend == "downtrend") and (momentum < 45)  # noqa: PLR2004
        strength = 0.75 if (bullish or bearish) else 0.25

        return {
            "trend": trend,
            "momentum": momentum,
            "volatility": volatility,
            "support": support,
            "resistance": resistance,
            "sentiment": self.sentiment,
            "signal_strength": strength,
        }


## Features:
