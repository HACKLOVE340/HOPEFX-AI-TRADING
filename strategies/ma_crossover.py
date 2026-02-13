"""
Moving Average Crossover Strategy

A simple trend-following strategy based on moving average crossovers.
"""

from typing import Dict, Optional, Any
import logging
from datetime import datetime

from .base import BaseStrategy, Signal, SignalType, StrategyConfig

logger = logging.getLogger(__name__)


class MovingAverageCrossover(BaseStrategy):
    """
    Moving Average Crossover Strategy.
    
    Generates signals when:
    - BUY: Fast MA crosses above slow MA
    - SELL: Fast MA crosses below slow MA
    
    Parameters:
    - fast_period: Fast MA period (default: 10)
    - slow_period: Slow MA period (default: 30)
    - min_confidence: Minimum confidence threshold (default: 0.6)
    """
    
    def __init__(self, config: StrategyConfig):
        """Initialize MA Crossover strategy"""
        super().__init__(config)
        
        # Get parameters from config
        params = config.parameters or {}
        self.fast_period = params.get('fast_period', 10)
        self.slow_period = params.get('slow_period', 30)
        self.min_confidence = params.get('min_confidence', 0.6)
        
        # Internal state
        self.price_history = []
        self.fast_ma = None
        self.slow_ma = None
        self.prev_fast_ma = None
        self.prev_slow_ma = None
        
        logger.info(
            f"MA Crossover Strategy initialized: "
            f"fast={self.fast_period}, slow={self.slow_period}"
        )
    
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze market data using moving averages.
        
        Args:
            data: Market data with 'close' price
            
        Returns:
            Analysis with MA values and crossover signals
        """
        close_price = data.get('close', 0.0)
        
        # Add to price history
        self.price_history.append(close_price)
        
        # Keep only necessary history
        max_period = max(self.fast_period, self.slow_period)
        if len(self.price_history) > max_period * 2:
            self.price_history = self.price_history[-max_period * 2:]
        
        # Calculate moving averages
        analysis = {
            'close': close_price,
            'fast_ma': None,
            'slow_ma': None,
            'crossover': None,
            'trend': 'NEUTRAL',
        }
        
        if len(self.price_history) >= self.slow_period:
            # Calculate fast MA
            fast_ma = self._calculate_ma(self.fast_period)
            slow_ma = self._calculate_ma(self.slow_period)
            
            analysis['fast_ma'] = fast_ma
            analysis['slow_ma'] = slow_ma
            
            # Check for crossover
            if self.prev_fast_ma is not None and self.prev_slow_ma is not None:
                # Bullish crossover
                if fast_ma > slow_ma and self.prev_fast_ma <= self.prev_slow_ma:
                    analysis['crossover'] = 'BULLISH'
                    analysis['trend'] = 'BULLISH'
                # Bearish crossover
                elif fast_ma < slow_ma and self.prev_fast_ma >= self.prev_slow_ma:
                    analysis['crossover'] = 'BEARISH'
                    analysis['trend'] = 'BEARISH'
                # Existing trend
                elif fast_ma > slow_ma:
                    analysis['trend'] = 'BULLISH'
                elif fast_ma < slow_ma:
                    analysis['trend'] = 'BEARISH'
            
            # Store previous values
            self.prev_fast_ma = fast_ma
            self.prev_slow_ma = slow_ma
        
        return analysis
    
    def generate_signal(self, analysis: Dict[str, Any]) -> Optional[Signal]:
        """
        Generate trading signal based on MA crossover.
        
        Args:
            analysis: Analysis results from analyze()
            
        Returns:
            Signal if crossover detected, None otherwise
        """
        crossover = analysis.get('crossover')
        close_price = analysis.get('close', 0.0)
        
        if not crossover:
            return None
        
        # Calculate confidence based on MA distance
        fast_ma = analysis.get('fast_ma', 0.0)
        slow_ma = analysis.get('slow_ma', 0.0)
        
        if slow_ma > 0:
            ma_distance = abs(fast_ma - slow_ma) / slow_ma
            # Higher distance = higher confidence
            confidence = min(0.5 + ma_distance * 10, 1.0)
        else:
            confidence = 0.5
        
        # Only generate signal if confidence meets threshold
        if confidence < self.min_confidence:
            return None
        
        # Generate signal
        if crossover == 'BULLISH':
            signal_type = SignalType.BUY
        elif crossover == 'BEARISH':
            signal_type = SignalType.SELL
        else:
            return None
        
        signal = Signal(
            signal_type=signal_type,
            symbol=self.config.symbol,
            price=close_price,
            timestamp=datetime.utcnow(),
            confidence=confidence,
            metadata={
                'fast_ma': fast_ma,
                'slow_ma': slow_ma,
                'crossover': crossover,
                'strategy': self.config.name,
            }
        )
        
        return signal
    
    def _calculate_ma(self, period: int) -> float:
        """
        Calculate simple moving average.
        
        Args:
            period: Number of periods
            
        Returns:
            Moving average value
        """
        if len(self.price_history) < period:
            return 0.0
        
        return sum(self.price_history[-period:]) / period
