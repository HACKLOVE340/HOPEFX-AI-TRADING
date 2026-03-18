"""
Institutional Strategy Framework
Event-driven, backtestable, production-ready
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import pandas as pd
import numpy as np

from hopefx.core.events import EventType, DomainEvent, event_bus

# ============================================================================
# STRATEGY BASE CLASS
# ============================================================================

class Strategy(ABC):
    """
    Institutional-grade strategy base.
    
    Features:
    - Event-driven execution
    - State management
    - Performance tracking
    - Risk integration
    - Parameter optimization
    """
    
    def __init__(self, name: str, params: Optional[Dict] = None):
        self.name = name
        self.params = params or {}
        self._state: Dict[str, Any] = {}
        self._indicators: Dict[str, pd.Series] = {}
        self._signals: List[Dict] = []
        self._performance = {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'pnl': 0.0,
            'max_drawdown': 0.0
        }
        self._enabled = True
        self._positions: Dict[str, Dict] = {}  # symbol -> position info
    
    # -------------------------------------------------------------------------
    # ABSTRACT METHODS — Must implement
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def on_bar(self, symbol: str, bar: pd.Series, ctx: Dict) -> Optional[Dict]:
        """
        Process new bar. Return signal dict or None.
        
        Signal format:
        {
            'action': 'buy' | 'sell' | 'close',
            'size': float,  # position size
            'price': Optional[float],  # limit price or None for market
            'stop_loss': Optional[float],
            'take_profit': Optional[float],
            'metadata': Dict  # strategy-specific data
        }
        """
        pass
    
    # -------------------------------------------------------------------------
    # HOOKS — Optional overrides
    # -------------------------------------------------------------------------
    
    def on_tick(self, symbol: str, tick: Dict, ctx: Dict):
        """High-frequency tick processing."""
        pass
    
    def on_fill(self, fill: Dict):
        """Handle execution fill."""
        self._performance['trades'] += 1
        pnl = fill.get('realized_pnl', 0)
        self._performance['pnl'] += pnl
        
        if pnl > 0:
            self._performance['wins'] += 1
        else:
            self._performance['losses'] += 1
    
    def on_position_change(self, position: Dict):
        """Track position updates."""
        symbol = position['symbol']
        if position['size'] == 0:
            self._positions.pop(symbol, None)
        else:
            self._positions[symbol] = position
    
    # -------------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------------
    
    def calculate_position_size(
        self,
        capital: float,
        risk_per_trade: float,
        entry_price: float,
        stop_price: float
    ) -> float:
        """
        Kelly-inspired position sizing.
        
        risk_per_trade: % of capital to risk (e.g., 0.01 for 1%)
        """
        if stop_price == 0 or entry_price == stop_price:
            return 0
        
        risk_amount = capital * risk_per_trade
        price_risk = abs(entry_price - stop_price) / entry_price
        
        if price_risk == 0:
            return 0
        
        position_value = risk_amount / price_risk
        shares = position_value / entry_price
        
        return shares
    
    def get_indicator(self, name: str) -> Optional[pd.Series]:
        """Get cached indicator."""
        return self._indicators.get(name)
    
    def set_indicator(self, name: str, values: pd.Series):
        """Cache indicator."""
        self._indicators[name] = values
    
    def get_state(self, key: str, default=None):
        """Get strategy state."""
        return self._state.get(key, default)
    
    def set_state(self, key: str, value: Any):
        """Set strategy state."""
        self._state[key] = value
    
    # -------------------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------------------
    
    def enable(self):
        self._enabled = True
    
    def disable(self):
        self._enabled = False
    
    def reset(self):
        """Reset strategy state."""
        self._state.clear()
        self._indicators.clear()
        self._signals.clear()
        self._positions.clear()
        self._performance = {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'pnl': 0.0,
            'max_drawdown': 0.0
        }

# ============================================================================
# EXAMPLE: Moving Average Crossover
# ============================================================================

class MovingAverageCrossover(Strategy):
    """
    Institutional MA Crossover with regime detection.
    """
    
    def __init__(self, fast: int = 20, slow: int = 50, regime_filter: bool = True):
        super().__init__(
            name=f"MA_Cross_{fast}_{slow}",
            params={'fast': fast, 'slow': slow, 'regime_filter': regime_filter}
        )
        self.fast = fast
        self.slow = slow
        self.regime_filter = regime_filter
    
    def on_bar(self, symbol: str, bar: pd.Series, ctx: Dict) -> Optional[Dict]:
        # Get historical data
        history = ctx.get('history', pd.DataFrame())
        if len(history) < self.slow + 10:
            return None
        
        # Calculate MAs
        fast_ma = history['close'].ewm(span=self.fast, adjust=False).mean()
        slow_ma = history['close'].ewm(span=self.slow, adjust=False).mean()
        
        # Store
        self.set_indicator('fast_ma', fast_ma)
        self.set_indicator('slow_ma', slow_ma)
        
        # Current values
        current_fast = fast_ma.iloc[-1]
        current_slow = slow_ma.iloc[-1]
        prev_fast = fast_ma.iloc[-2]
        prev_slow = slow_ma.iloc[-2]
        
        # Regime filter (200 EMA trend)
        if self.regime_filter:
            trend_ema = history['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            price = bar['close']
            
            # Only trade in trend direction
            uptrend = price > trend_ema
            downtrend = price < trend_ema
        else:
            uptrend = downtrend = True
        
        # Generate signals
        position = self._positions.get(symbol, {}).get('size', 0)
        
        # Golden cross (buy)
        if prev_fast <= prev_slow and current_fast > current_slow:
            if uptrend and position <= 0:  # No long position
                return {
                    'action': 'buy',
                    'size': ctx.get('default_size', 1.0),
                    'price': None,  # Market order
                    'metadata': {
                        'fast_ma': float(current_fast),
                        'slow_ma': float(current_slow),
                        'cross_type': 'golden',
                        'trend_aligned': uptrend
                    }
                }
        
        # Death cross (sell)
        elif prev_fast >= prev_slow and current_fast < current_slow:
            if downtrend and position >= 0:  # No short position
                return {
                    'action': 'sell',
                    'size': ctx.get('default_size', 1.0),
                    'price': None,
                    'metadata': {
                        'fast_ma': float(current_fast),
                        'slow_ma': float(current_slow),
                        'cross_type': 'death',
                        'trend_aligned': downtrend
                    }
                }
        
        return None

# ============================================================================
# EXAMPLE: Mean Reversion (Bollinger Bands)
# ============================================================================

class BollingerMeanReversion(Strategy):
    """
    Institutional mean reversion with volatility scaling.
    """
    
    def __init__(self, period: int = 20, dev: float = 2.0, vol_lookback: int = 50):
        super().__init__(
            name=f"BB_MeanRev_{period}",
            params={'period': period, 'dev': dev, 'vol_lookback': vol_lookback}
        )
        self.period = period
        self.dev = dev
        self.vol_lookback = vol_lookback
    
    def on_bar(self, symbol: str, bar: pd.Series, ctx: Dict) -> Optional[Dict]:
        history = ctx.get('history', pd.DataFrame())
        if len(history) < self.vol_lookback:
            return None
        
        # Calculate Bollinger Bands
        sma = history['close'].rolling(self.period).mean()
        std = history['close'].rolling(self.period).std()
        
        upper = sma + (std * self.dev)
        lower = sma - (std * self.dev)
        
        # Volatility scaling (ATR)
        atr = self._calculate_atr(history, 14)
        current_atr = atr.iloc[-1]
        avg_atr = atr.iloc[-self.vol_lookback:].mean()
        
        # Scale position by volatility (lower vol = larger size)
        vol_scalar = avg_atr / current_atr if current_atr > 0 else 1.0
        vol_scalar = np.clip(vol_scalar, 0.5, 2.0)  # Limit scaling
        
        price = bar['close']
        position = self._positions.get(symbol, {}).get('size', 0)
        
        # Long signal: price below lower band
        if price < lower.iloc[-1] and position <= 0:
            return {
                'action': 'buy',
                'size': ctx.get('default_size', 1.0) * vol_scalar,
                'price': None,
                'stop_loss': price - (current_atr * 2),
                'take_profit': sma.iloc[-1],  # Target middle band
                'metadata': {
                    'bb_position': (price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]),
                    'vol_scalar': float(vol_scalar),
                    'atr': float(current_atr)
                }
            }
        
        # Short signal: price above upper band
        elif price > upper.iloc[-1] and position >= 0:
            return {
                'action': 'sell',
                'size': ctx.get('default_size', 1.0) * vol_scalar,
                'price': None,
                'stop_loss': price + (current_atr * 2),
                'take_profit': sma.iloc[-1],
                'metadata': {
                    'bb_position': (price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]),
                    'vol_scalar': float(vol_scalar),
                    'atr': float(current_atr)
                }
            }
        
        # Exit: price crosses middle band
        if position != 0:
            prev_price = history['close'].iloc[-2]
            if (position > 0 and price > sma.iloc[-1] and prev_price <= sma.iloc[-2]) or \
               (position < 0 and price < sma.iloc[-1] and prev_price >= sma.iloc[-2]):
                return {
                    'action': 'close',
                    'size': abs(position),
                    'price': None,
                    'metadata': {'exit_reason': 'mean_reversion_complete'}
                }
        
        return None
    
    def _calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Calculate Average True Range."""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()
