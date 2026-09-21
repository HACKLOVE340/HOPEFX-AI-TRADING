# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
EMA Crossover Trading Strategy

This strategy uses Exponential Moving Average crossovers for signals.
Similar to MA Crossover but more responsive to recent price changes.
"""

from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class EMAcrossoverStrategy(BaseStrategy):
    """
    EMA Crossover trading strategy.

    Uses exponential moving averages which give more weight to recent prices.
    """

    def __init__(
        self,
        name: str,
        symbol: str,
        config,
        fast_period: int = 12,
        slow_period: int = 26,
    ):
        """
        Initialize EMA Crossover strategy.

        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            fast_period: Fast EMA period
            slow_period: Slow EMA period
        """
        super().__init__(name, symbol, config)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.logger.info("EMA Crossover Strategy initialized: fast=%s, slow=%s", fast_period, slow_period)

    def analyze(self, data: Any) -> dict[str, Any]:
        """Return the current fast/slow EMA snapshot.

        ``BaseStrategy`` declares ``analyze`` abstract and this class did not
        implement it, so ``EMAcrossoverStrategy(...)`` raised
        ``TypeError: Can't instantiate abstract class`` — the strategy was
        listed as available and could not be constructed at all.
        """
        frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        if frame.empty or "close" not in frame.columns:
            return {"fast_ema": None, "slow_ema": None, "error": "no close prices"}
        close = frame["close"]
        fast = close.ewm(span=self.fast_period, adjust=False).mean().fillna(close)
        slow = close.ewm(span=self.slow_period, adjust=False).mean().fillna(close)
        return {
            "fast_ema": float(fast.iloc[-1]),
            "slow_ema": float(slow.iloc[-1]),
            "price": float(close.iloc[-1]),
        }

    def generate_signal(self, analysis: pd.DataFrame) -> dict[str, Any]:  # type: ignore[override]
        market_data = analysis
        """
        Generate trading signal based on EMA crossover.

        Args:
            market_data: DataFrame with OHLCV data

        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            if len(market_data) < self.slow_period:
                return {
                    "type": "HOLD",
                    "confidence": 0.0,
                    "reason": "Insufficient data",
                    "timestamp": datetime.now(UTC),
                }

            close = market_data["close"]

            # Calculate EMAs
            fast_ema = close.ewm(span=self.fast_period, adjust=False).mean().fillna(close)
            slow_ema = close.ewm(span=self.slow_period, adjust=False).mean().fillna(close)

            # Current values
            current_fast = float(np.nan_to_num(fast_ema.iloc[-1], nan=0.0))
            current_slow = float(np.nan_to_num(slow_ema.iloc[-1], nan=0.0))
            current_price = float(np.nan_to_num(close.iloc[-1], nan=0.0))

            # Previous values
            prev_fast = float(np.nan_to_num(fast_ema.iloc[-2], nan=current_fast))
            prev_slow = float(np.nan_to_num(slow_ema.iloc[-2], nan=current_slow))

            # Calculate distance between EMAs (normalized)
            ema_diff = abs(current_fast - current_slow) / current_price if current_price != 0 else 0.0

            signal_type = "HOLD"
            confidence = 0.0
            reason = ""

            # Bullish crossover: Fast EMA crosses above Slow EMA
            if prev_fast <= prev_slow and current_fast > current_slow:
                signal_type = "BUY"
                confidence = 0.80
                reason = f"Bullish EMA crossover: {current_fast:.5f} > {current_slow:.5f}"

                # Higher confidence if EMAs are converging with momentum
                if ema_diff < 0.001:
                    confidence = min(0.95, confidence + 0.10)
                    reason += " (strong momentum)"

            # Bearish crossover: Fast EMA crosses below Slow EMA
            elif prev_fast >= prev_slow and current_fast < current_slow:
                signal_type = "SELL"
                confidence = 0.80
                reason = f"Bearish EMA crossover: {current_fast:.5f} < {current_slow:.5f}"

                # Higher confidence if EMAs are converging with momentum
                if ema_diff < 0.001:
                    confidence = min(0.95, confidence + 0.10)
                    reason += " (strong momentum)"

            # Already in trend - continuation signals
            elif current_fast > current_slow:
                # Uptrend - Fast EMA above Slow EMA
                if current_fast > prev_fast and current_slow > prev_slow:
                    # Both EMAs rising - strong uptrend
                    signal_type = "BUY"
                    confidence = 0.60
                    reason = "Strong uptrend continuation"
                elif current_fast < prev_fast:
                    # Fast EMA declining - potential reversal
                    signal_type = "SELL"
                    confidence = 0.55
                    reason = "Uptrend weakening"

            elif current_fast < current_slow:
                # Downtrend - Fast EMA below Slow EMA
                if current_fast < prev_fast and current_slow < prev_slow:
                    # Both EMAs falling - strong downtrend
                    signal_type = "SELL"
                    confidence = 0.60
                    reason = "Strong downtrend continuation"
                elif current_fast > prev_fast:
                    # Fast EMA rising - potential reversal
                    signal_type = "BUY"
                    confidence = 0.55
                    reason = "Downtrend weakening"

            if signal_type == "HOLD":
                reason = f"No clear signal: Fast={current_fast:.5f}, Slow={current_slow:.5f}"

            return {
                "type": signal_type,
                "confidence": confidence,
                "reason": reason,
                "timestamp": datetime.now(UTC),
                "metadata": {
                    "fast_ema": current_fast,
                    "slow_ema": current_slow,
                    "price": current_price,
                    "ema_diff": ema_diff,
                    "trend": "bullish" if current_fast > current_slow else "bearish",
                },
            }

        except Exception as e:
            self.logger.error("Error generating EMA crossover signal: %s", e)

            return {
                "type": "HOLD",
                "confidence": 0.0,
                "reason": f"Error: {e!s}",
                "timestamp": datetime.now(UTC),
            }
