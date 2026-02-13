"""
Mean Reversion Trading Strategy

This strategy trades when price deviates significantly from its mean,
expecting it to revert back to the average.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy using Bollinger Bands.
    
    Buys when price is below lower band (oversold).
    Sells when price is above upper band (overbought).
    """
    
    def __init__(self, name: str, symbol: str, config, 
                 period: int = 20, std_dev: float = 2.0):
        """
        Initialize mean reversion strategy.
        
        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            period: Moving average period
            std_dev: Standard deviation multiplier for bands
        """
        super().__init__(name, symbol, config)
        self.period = period
        self.std_dev = std_dev
        self.logger.info(
            f"Mean Reversion Strategy initialized: "
            f"period={period}, std_dev={std_dev}"
        )
    
    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate trading signal based on mean reversion.
        
        Args:
            market_data: DataFrame with OHLCV data
        
        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            if len(market_data) < self.period:
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'Insufficient data',
                    'timestamp': datetime.now()
                }
            
            # Calculate Bollinger Bands
            close = market_data['close']
            sma = close.rolling(window=self.period).mean()
            std = close.rolling(window=self.period).std()
            
            upper_band = sma + (std * self.std_dev)
            lower_band = sma - (std * self.std_dev)
            
            # Current values
            current_price = close.iloc[-1]
            current_sma = sma.iloc[-1]
            current_upper = upper_band.iloc[-1]
            current_lower = lower_band.iloc[-1]
            
            # Calculate distance from bands (normalized)
            band_width = current_upper - current_lower
            if band_width == 0:
                return {'type': 'HOLD', 'confidence': 0.0, 'reason': 'Zero band width'}
            
            # Distance from bands as percentage
            distance_from_lower = (current_price - current_lower) / band_width
            distance_from_upper = (current_upper - current_price) / band_width
            
            # Generate signals
            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''
            
            # BUY when price touches or goes below lower band (oversold)
            if current_price <= current_lower:
                signal_type = 'BUY'
                confidence = min(0.9, 0.5 + abs(distance_from_lower) * 0.4)
                reason = f'Price below lower band (oversold): {current_price:.5f} < {current_lower:.5f}'
            
            # SELL when price touches or goes above upper band (overbought)
            elif current_price >= current_upper:
                signal_type = 'SELL'
                confidence = min(0.9, 0.5 + abs(distance_from_upper) * 0.4)
                reason = f'Price above upper band (overbought): {current_price:.5f} > {current_upper:.5f}'
            
            # SELL if we're long and price returns to mean
            elif hasattr(self, 'position') and self.position == 'LONG' and current_price >= current_sma:
                signal_type = 'SELL'
                confidence = 0.6
                reason = f'Price reverted to mean: {current_price:.5f} >= {current_sma:.5f}'
            
            # BUY to close if we're short and price returns to mean
            elif hasattr(self, 'position') and self.position == 'SHORT' and current_price <= current_sma:
                signal_type = 'BUY'
                confidence = 0.6
                reason = f'Price reverted to mean: {current_price:.5f} <= {current_sma:.5f}'
            
            else:
                reason = f'Price within bands: {current_lower:.5f} < {current_price:.5f} < {current_upper:.5f}'
            
            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'price': current_price,
                    'sma': current_sma,
                    'upper_band': current_upper,
                    'lower_band': current_lower,
                    'band_width': band_width
                }
            }
        
        except Exception as e:
            self.logger.error(f"Error generating signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
