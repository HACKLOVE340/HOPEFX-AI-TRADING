"""
Breakout/Momentum Trading Strategy

This strategy identifies and trades breakouts from consolidation periods.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class BreakoutStrategy(BaseStrategy):
    """
    Breakout momentum trading strategy.

    Identifies support/resistance levels and trades breakouts.
    """

    def __init__(self, name: str, symbol: str, config,
                 lookback_period: int = 20, breakout_threshold: float = 0.02):
        """
        Initialize Breakout strategy.

        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            lookback_period: Period for identifying support/resistance
            breakout_threshold: Minimum breakout percentage (e.g., 0.02 = 2%)
        """
        super().__init__(name, symbol, config)
        self.lookback_period = lookback_period
        self.breakout_threshold = breakout_threshold
        self.logger.info(
            f"Breakout Strategy initialized: lookback={lookback_period}, "
            f"threshold={breakout_threshold}"
        )

    def identify_support_resistance(self, market_data: pd.DataFrame) -> tuple:
        """
        Identify support and resistance levels.

        Args:
            market_data: DataFrame with OHLCV data

        Returns:
            Tuple of (support_level, resistance_level)
        """
        high = market_data['high']
        low = market_data['low']

        # Use recent period for levels
        recent_high = high.tail(self.lookback_period).max()
        recent_low = low.tail(self.lookback_period).min()

        return recent_low, recent_high

    def calculate_atr(self, market_data: pd.DataFrame, period: int = 14) -> float:
        """
        Calculate Average True Range (ATR) for volatility.

        Args:
            market_data: DataFrame with OHLCV data
            period: ATR period

        Returns:
            Current ATR value
        """
        high = market_data['high']
        low = market_data['low']
        close = market_data['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr.iloc[-1]

    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate trading signal based on breakouts.

        Args:
            market_data: DataFrame with OHLCV data

        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            if len(market_data) < self.lookback_period:
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'Insufficient data',
                    'timestamp': datetime.now()
                }

            # Identify levels
            support, resistance = self.identify_support_resistance(market_data)

            # Current values
            current_price = market_data['close'].iloc[-1]
            current_high = market_data['high'].iloc[-1]
            current_low = market_data['low'].iloc[-1]
            current_volume = market_data['volume'].iloc[-1] if 'volume' in market_data else 0

            # Average volume for confirmation
            avg_volume = market_data['volume'].tail(self.lookback_period).mean() if 'volume' in market_data else 0
            high_volume = current_volume > avg_volume * 1.2 if avg_volume > 0 else False

            # Calculate ATR for volatility
            atr = self.calculate_atr(market_data)

            # Calculate breakout distance
            range_size = resistance - support
            breakout_threshold_price = range_size * self.breakout_threshold

            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''

            # Bullish breakout above resistance
            if current_high > resistance:
                breakout_distance = current_high - resistance

                if breakout_distance >= breakout_threshold_price:
                    signal_type = 'BUY'
                    confidence = 0.70
                    reason = f'Bullish breakout above resistance: {current_price:.5f} > {resistance:.5f}'

                    # Higher confidence with volume
                    if high_volume:
                        confidence = min(0.90, confidence + 0.15)
                        reason += ' with high volume'

                    # Higher confidence if price closes above resistance
                    if current_price > resistance:
                        confidence = min(0.95, confidence + 0.10)
                        reason += ' (strong close)'

            # Bearish breakout below support
            elif current_low < support:
                breakout_distance = support - current_low

                if breakout_distance >= breakout_threshold_price:
                    signal_type = 'SELL'
                    confidence = 0.70
                    reason = f'Bearish breakout below support: {current_price:.5f} < {support:.5f}'

                    # Higher confidence with volume
                    if high_volume:
                        confidence = min(0.90, confidence + 0.15)
                        reason += ' with high volume'

                    # Higher confidence if price closes below support
                    if current_price < support:
                        confidence = min(0.95, confidence + 0.10)
                        reason += ' (strong close)'

            # Approaching resistance
            elif current_price > resistance * 0.995 and current_price < resistance:
                signal_type = 'BUY'
                confidence = 0.50
                reason = f'Approaching resistance: {current_price:.5f} near {resistance:.5f}'

            # Approaching support
            elif current_price < support * 1.005 and current_price > support:
                signal_type = 'BUY'
                confidence = 0.55
                reason = f'Near support level: {current_price:.5f} near {support:.5f}'

            # Consolidation (no clear signal)
            else:
                reason = f'Consolidating: {support:.5f} < {current_price:.5f} < {resistance:.5f}'

            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'price': current_price,
                    'support': support,
                    'resistance': resistance,
                    'range_size': range_size,
                    'atr': atr,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'high_volume': high_volume
                }
            }

        except Exception as e:
            self.logger.error(f"Error generating breakout signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
