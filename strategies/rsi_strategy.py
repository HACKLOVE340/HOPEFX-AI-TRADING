"""
RSI (Relative Strength Index) Trading Strategy

This strategy uses RSI to identify overbought and oversold conditions.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from strategies.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    """
    RSI-based trading strategy.
    
    Buys when RSI is oversold (below lower threshold).
    Sells when RSI is overbought (above upper threshold).
    """
    
    def __init__(self, name: str, symbol: str, config,
                 period: int = 14, oversold: float = 30, overbought: float = 70):
        """
        Initialize RSI strategy.
        
        Args:
            name: Strategy name
            symbol: Trading symbol
            config: Configuration manager
            period: RSI calculation period
            oversold: Oversold threshold (buy signal)
            overbought: Overbought threshold (sell signal)
        """
        super().__init__(name, symbol, config)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.logger.info(
            f"RSI Strategy initialized: period={period}, "
            f"oversold={oversold}, overbought={overbought}"
        )
    
    def calculate_rsi(self, prices: pd.Series) -> pd.Series:
        """
        Calculate RSI indicator.
        
        Args:
            prices: Series of closing prices
        
        Returns:
            Series of RSI values
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def generate_signal(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate trading signal based on RSI.
        
        Args:
            market_data: DataFrame with OHLCV data
        
        Returns:
            Dictionary with signal type, confidence, and metadata
        """
        try:
            if len(market_data) < self.period + 1:
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'Insufficient data for RSI calculation',
                    'timestamp': datetime.now()
                }
            
            # Calculate RSI
            close = market_data['close']
            rsi = self.calculate_rsi(close)
            
            current_rsi = rsi.iloc[-1]
            previous_rsi = rsi.iloc[-2]
            current_price = close.iloc[-1]
            
            # Check for NaN
            if pd.isna(current_rsi):
                return {
                    'type': 'HOLD',
                    'confidence': 0.0,
                    'reason': 'RSI calculation resulted in NaN',
                    'timestamp': datetime.now()
                }
            
            signal_type = 'HOLD'
            confidence = 0.0
            reason = ''
            
            # BUY signal: RSI is oversold and starting to rise
            if current_rsi < self.oversold:
                signal_type = 'BUY'
                # Confidence increases as RSI gets more oversold
                confidence = 0.5 + (self.oversold - current_rsi) / self.oversold * 0.4
                confidence = min(0.95, confidence)
                reason = f'RSI oversold: {current_rsi:.2f} < {self.oversold}'
                
                # Higher confidence if RSI is turning up
                if current_rsi > previous_rsi:
                    confidence = min(0.95, confidence + 0.1)
                    reason += ' and rising'
            
            # SELL signal: RSI is overbought and starting to fall
            elif current_rsi > self.overbought:
                signal_type = 'SELL'
                # Confidence increases as RSI gets more overbought
                confidence = 0.5 + (current_rsi - self.overbought) / (100 - self.overbought) * 0.4
                confidence = min(0.95, confidence)
                reason = f'RSI overbought: {current_rsi:.2f} > {self.overbought}'
                
                # Higher confidence if RSI is turning down
                if current_rsi < previous_rsi:
                    confidence = min(0.95, confidence + 0.1)
                    reason += ' and falling'
            
            # Exit long position if RSI reaches neutral/overbought
            elif hasattr(self, 'position') and self.position == 'LONG' and current_rsi > 50:
                if current_rsi > self.overbought or current_rsi < previous_rsi:
                    signal_type = 'SELL'
                    confidence = 0.6
                    reason = f'Exit long: RSI = {current_rsi:.2f}'
            
            # Exit short position if RSI reaches neutral/oversold
            elif hasattr(self, 'position') and self.position == 'SHORT' and current_rsi < 50:
                if current_rsi < self.oversold or current_rsi > previous_rsi:
                    signal_type = 'BUY'
                    confidence = 0.6
                    reason = f'Exit short: RSI = {current_rsi:.2f}'
            
            else:
                reason = f'RSI neutral: {current_rsi:.2f} (range: {self.oversold}-{self.overbought})'
            
            return {
                'type': signal_type,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now(),
                'metadata': {
                    'rsi': current_rsi,
                    'previous_rsi': previous_rsi,
                    'price': current_price,
                    'oversold_level': self.oversold,
                    'overbought_level': self.overbought
                }
            }
        
        except Exception as e:
            self.logger.error(f"Error generating RSI signal: {e}")
            return {
                'type': 'HOLD',
                'confidence': 0.0,
                'reason': f'Error: {str(e)}',
                'timestamp': datetime.now()
            }
