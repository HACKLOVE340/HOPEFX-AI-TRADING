"""
Stochastic Oscillator Trading Strategy

This strategy uses the Stochastic Oscillator to identify overbought/oversold conditions.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class StochasticStrategy(BaseStrategy):
    """
    Stochastic Oscillator trading strategy.
    
    Uses %K and %D lines to identify momentum and reversals.
    """
    
    def __init__(self, name: str, symbol: str, config,
                 k_period: int = 14, d_period: int = 3, oversold: float = 20, overbought: float = 80):
        """
        Initialize Stochastic strategy.
        
        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            k_period: %K period
            d_period: %D smoothing period
            oversold: Oversold threshold
            overbought: Overbought threshold
        """
        super().__init__(name, symbol, config)
        self.k_period = k_period
        self.d_period = d_period
        self.oversold = oversold
        self.overbought = overbought
        self.logger.info(
            f"Stochastic Strategy initialized: k={k_period}, d={d_period}, "
            f"oversold={oversold}, overbought={overbought}"
        )
    
    def calculate_stochastic(self, market_data: pd.DataFrame) -> tuple:
        """
        Calculate Stochastic Oscillator.
        
        Args:
            market_data: DataFrame with OHLCV data
        
        Returns:
            Tuple of (%K, %D)
        """
        high = market_data['high']
        low = market_data['low']
        close = market_data['close']
        
        # Calculate %K
        lowest_low = low.rolling(window=self.k_period).min()
        highest_high = high.rolling(window=self.k_period).max()
        
        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        
        # Calculate %D (SMA of %K)
        d_percent = k_percent.rolling(window=self.d_period).mean()
        
        return k_percent, d_percent
    
    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate trading signal based on Stochastic Oscillator.
        
        Args:
            market_data: DataFrame with OHLCV data
        
        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            min_length = self.k_period + self.d_period
            if len(market_data) < min_length:
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': f'Insufficient data (need {min_length} periods)',
                    'timestamp': datetime.now()
                }
            
            # Calculate Stochastic
            k_percent, d_percent = self.calculate_stochastic(market_data)
            
            # Current values
            current_k = k_percent.iloc[-1]
            current_d = d_percent.iloc[-1]
            current_price = market_data['close'].iloc[-1]
            
            # Previous values
            prev_k = k_percent.iloc[-2]
            prev_d = d_percent.iloc[-2]
            
            # Check for NaN
            if pd.isna(current_k) or pd.isna(current_d):
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'Stochastic calculation resulted in NaN',
                    'timestamp': datetime.now()
                }
            
            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''
            
            # BUY signals
            # 1. Bullish crossover in oversold region
            if current_k < self.oversold and prev_k <= prev_d and current_k > current_d:
                signal_type = 'BUY'
                confidence = 0.85
                reason = f'Bullish crossover in oversold: %K={current_k:.1f} crossed above %D={current_d:.1f}'
            
            # 2. Rising from oversold
            elif current_k < self.oversold and current_k > prev_k:
                signal_type = 'BUY'
                confidence = 0.70
                reason = f'Rising from oversold: %K={current_k:.1f}'
            
            # 3. Exiting oversold zone
            elif prev_k < self.oversold and current_k > self.oversold:
                signal_type = 'BUY'
                confidence = 0.75
                reason = f'Exiting oversold zone: %K={current_k:.1f}'
            
            # SELL signals
            # 1. Bearish crossover in overbought region
            elif current_k > self.overbought and prev_k >= prev_d and current_k < current_d:
                signal_type = 'SELL'
                confidence = 0.85
                reason = f'Bearish crossover in overbought: %K={current_k:.1f} crossed below %D={current_d:.1f}'
            
            # 2. Falling from overbought
            elif current_k > self.overbought and current_k < prev_k:
                signal_type = 'SELL'
                confidence = 0.70
                reason = f'Falling from overbought: %K={current_k:.1f}'
            
            # 3. Exiting overbought zone
            elif prev_k > self.overbought and current_k < self.overbought:
                signal_type = 'SELL'
                confidence = 0.75
                reason = f'Exiting overbought zone: %K={current_k:.1f}'
            
            # Divergence signals (weaker)
            elif current_k > 50:
                # In bullish territory
                if prev_k > prev_d and current_k < current_d:
                    # Bearish crossover above 50
                    signal_type = 'SELL'
                    confidence = 0.55
                    reason = f'Bearish crossover: %K={current_k:.1f} < %D={current_d:.1f}'
            
            elif current_k < 50:
                # In bearish territory
                if prev_k < prev_d and current_k > current_d:
                    # Bullish crossover below 50
                    signal_type = 'BUY'
                    confidence = 0.55
                    reason = f'Bullish crossover: %K={current_k:.1f} > %D={current_d:.1f}'
            
            if signal_type == 'HOLD':
                reason = f'Stochastic neutral: %K={current_k:.1f}, %D={current_d:.1f}'
            
            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'k_percent': current_k,
                    'd_percent': current_d,
                    'previous_k': prev_k,
                    'previous_d': prev_d,
                    'price': current_price,
                    'oversold_level': self.oversold,
                    'overbought_level': self.overbought
                }
            }
        
        except Exception as e:
            self.logger.error(f"Error generating Stochastic signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
