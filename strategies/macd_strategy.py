"""
MACD (Moving Average Convergence Divergence) Trading Strategy

This strategy uses MACD indicator for trend-following signals.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """
    MACD-based trading strategy.

    Generates signals based on MACD line crossing signal line.
    """

    def __init__(self, name: str, symbol: str, config,
                 fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        """
        Initialize MACD strategy.

        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line EMA period
        """
        super().__init__(name, symbol, config)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.logger.info(
            f"MACD Strategy initialized: fast={fast_period}, "
            f"slow={slow_period}, signal={signal_period}"
        )

    def calculate_macd(self, prices: pd.Series) -> tuple:
        """
        Calculate MACD indicator.

        Args:
            prices: Series of closing prices

        Returns:
            Tuple of (macd_line, signal_line, histogram)
        """
        # Calculate EMAs
        ema_fast = prices.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = prices.ewm(span=self.slow_period, adjust=False).mean()

        # MACD line
        macd_line = ema_fast - ema_slow

        # Signal line
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()

        # Histogram
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate trading signal based on MACD.

        Args:
            market_data: DataFrame with OHLCV data

        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            min_length = self.slow_period + self.signal_period
            if len(market_data) < min_length:
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': f'Insufficient data (need {min_length} periods)',
                    'timestamp': datetime.now()
                }

            close = market_data['close']

            # Calculate MACD
            macd_line, signal_line, histogram = self.calculate_macd(close)

            # Current values
            current_macd = macd_line.iloc[-1]
            current_signal = signal_line.iloc[-1]
            current_hist = histogram.iloc[-1]
            current_price = close.iloc[-1]

            # Previous values
            prev_macd = macd_line.iloc[-2]
            prev_signal = signal_line.iloc[-2]
            prev_hist = histogram.iloc[-2]

            # Check for NaN
            if pd.isna(current_macd) or pd.isna(current_signal):
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'MACD calculation resulted in NaN',
                    'timestamp': datetime.now()
                }

            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''

            # Bullish crossover: MACD crosses above signal line
            if prev_macd <= prev_signal and current_macd > current_signal:
                signal_type = 'BUY'
                confidence = 0.75
                reason = 'Bullish MACD crossover'

                # Higher confidence if MACD is below zero (oversold)
                if current_macd < 0:
                    confidence = 0.85
                    reason += ' from oversold'

                # Higher confidence if histogram is growing
                if current_hist > prev_hist:
                    confidence = min(0.95, confidence + 0.1)
                    reason += ' with momentum'

            # Bearish crossover: MACD crosses below signal line
            elif prev_macd >= prev_signal and current_macd < current_signal:
                signal_type = 'SELL'
                confidence = 0.75
                reason = 'Bearish MACD crossover'

                # Higher confidence if MACD is above zero (overbought)
                if current_macd > 0:
                    confidence = 0.85
                    reason += ' from overbought'

                # Higher confidence if histogram is shrinking
                if current_hist < prev_hist:
                    confidence = min(0.95, confidence + 0.1)
                    reason += ' with momentum'

            # Histogram divergence signals
            elif current_macd > current_signal:
                # MACD above signal (bullish territory)
                if current_hist < prev_hist and current_hist > 0:
                    # Weakening momentum
                    signal_type = 'SELL'
                    confidence = 0.55
                    reason = 'MACD momentum weakening (bearish divergence)'
                elif current_hist > prev_hist:
                    # Strengthening momentum
                    signal_type = 'BUY'
                    confidence = 0.50
                    reason = 'MACD momentum strengthening'

            elif current_macd < current_signal:
                # MACD below signal (bearish territory)
                if current_hist > prev_hist and current_hist < 0:
                    # Weakening downward momentum
                    signal_type = 'BUY'
                    confidence = 0.55
                    reason = 'MACD momentum weakening (bullish divergence)'
                elif current_hist < prev_hist:
                    # Strengthening downward momentum
                    signal_type = 'SELL'
                    confidence = 0.50
                    reason = 'MACD downward momentum strengthening'

            if signal_type == 'HOLD':
                reason = f'No MACD signal: MACD={current_macd:.5f}, Signal={current_signal:.5f}'

            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'macd': current_macd,
                    'signal': current_signal,
                    'histogram': current_hist,
                    'previous_histogram': prev_hist,
                    'price': current_price
                }
            }

        except Exception as e:
            self.logger.error(f"Error generating MACD signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
