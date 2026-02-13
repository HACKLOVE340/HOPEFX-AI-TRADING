"""
EMA Crossover Trading Strategy

This strategy uses Exponential Moving Average crossovers for signals.
Similar to MA Crossover but more responsive to recent price changes.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class EMAcrossoverStrategy(BaseStrategy):
    """
    EMA Crossover trading strategy.

    Uses exponential moving averages which give more weight to recent prices.
    """

    def __init__(self, name: str, symbol: str, config,
                 fast_period: int = 12, slow_period: int = 26):
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
        self.logger.info(
            f"EMA Crossover Strategy initialized: "
            f"fast={fast_period}, slow={slow_period}"
        )

    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
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
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'Insufficient data',
                    'timestamp': datetime.now()
                }

            close = market_data['close']

            # Calculate EMAs
            fast_ema = close.ewm(span=self.fast_period, adjust=False).mean()
            slow_ema = close.ewm(span=self.slow_period, adjust=False).mean()

            # Current values
            current_fast = fast_ema.iloc[-1]
            current_slow = slow_ema.iloc[-1]
            current_price = close.iloc[-1]

            # Previous values
            prev_fast = fast_ema.iloc[-2]
            prev_slow = slow_ema.iloc[-2]

            # Calculate distance between EMAs (normalized)
            ema_diff = abs(current_fast - current_slow) / current_price

            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''

            # Bullish crossover: Fast EMA crosses above Slow EMA
            if prev_fast <= prev_slow and current_fast > current_slow:
                signal_type = 'BUY'
                confidence = 0.80
                reason = f'Bullish EMA crossover: {current_fast:.5f} > {current_slow:.5f}'

                # Higher confidence if EMAs are converging with momentum
                if ema_diff < 0.001:
                    confidence = min(0.95, confidence + 0.10)
                    reason += ' (strong momentum)'

            # Bearish crossover: Fast EMA crosses below Slow EMA
            elif prev_fast >= prev_slow and current_fast < current_slow:
                signal_type = 'SELL'
                confidence = 0.80
                reason = f'Bearish EMA crossover: {current_fast:.5f} < {current_slow:.5f}'

                # Higher confidence if EMAs are converging with momentum
                if ema_diff < 0.001:
                    confidence = min(0.95, confidence + 0.10)
                    reason += ' (strong momentum)'

            # Already in trend - continuation signals
            elif current_fast > current_slow:
                # Uptrend - Fast EMA above Slow EMA
                if current_fast > prev_fast and current_slow > prev_slow:
                    # Both EMAs rising - strong uptrend
                    signal_type = 'BUY'
                    confidence = 0.60
                    reason = 'Strong uptrend continuation'
                elif current_fast < prev_fast:
                    # Fast EMA declining - potential reversal
                    signal_type = 'SELL'
                    confidence = 0.55
                    reason = 'Uptrend weakening'

            elif current_fast < current_slow:
                # Downtrend - Fast EMA below Slow EMA
                if current_fast < prev_fast and current_slow < prev_slow:
                    # Both EMAs falling - strong downtrend
                    signal_type = 'SELL'
                    confidence = 0.60
                    reason = 'Strong downtrend continuation'
                elif current_fast > prev_fast:
                    # Fast EMA rising - potential reversal
                    signal_type = 'BUY'
                    confidence = 0.55
                    reason = 'Downtrend weakening'

            if signal_type == 'HOLD':
                reason = f'No clear signal: Fast={current_fast:.5f}, Slow={current_slow:.5f}'

            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'fast_ema': current_fast,
                    'slow_ema': current_slow,
                    'price': current_price,
                    'ema_diff': ema_diff,
                    'trend': 'bullish' if current_fast > current_slow else 'bearish'
                }
            }

        except Exception as e:
            self.logger.error(f"Error generating EMA crossover signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
