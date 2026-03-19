
# 5. STRATEGY MANAGER - Multi-strategy system with regime detection
"""
strategy_code 
HOPEFX Strategy Manager
Multi-strategy system with market regime adaptation
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod
import numpy as np

import enum

try:
    from sqlalchemy import (
        Column, Integer, BigInteger, String, Float, Boolean,
        DateTime, ForeignKey, Enum, Text, Index, create_engine
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    # Create dummy base for type hints
    class _DummyBase:
        pass
    declarative_base = lambda: _DummyBase

Base = declarative_base()


class TradeStatus(enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    ERROR = "error"


class OrderSide(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class SignalSource(enum.Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class Trade(Base):
    """Trade record"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum(OrderSide), nullable=False)
    
    # Entry
    entry_time = Column(DateTime, default=datetime.utcnow)
    entry_price = Column(Float, nullable=False)
    entry_quantity = Column(Float, nullable=False)
    
    # Exit
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_quantity = Column(Float, nullable=True)
    
    # P&L
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    swap = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    
    # Risk
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    risk_reward_ratio = Column(Float, nullable=True)
    
    # Strategy
    strategy = Column(String(50), nullable=True)
    signal_source = Column(Enum(SignalSource), nullable=True)
    signal_strength = Column(Float, nullable=True)
    
    # Status
    status = Column(Enum(TradeStatus), default=TradeStatus.PENDING)
    is_open = Column(Boolean, default=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)
    
    # Relationships
    orders = relationship("Order", back_populates="trade", lazy="dynamic")
    signals = relationship("Signal", back_populates="trade", lazy="dynamic")
    
    def __repr__(self):
        return f"<Trade({self.trade_id}, {self.symbol}, {self.side.value}, PnL={self.total_pnl})>"
    
    def to_dict(self) -> dict:
        return {
           
logger = logging.getLogger(__name__)

@dataclass
class Signal:
    symbol: str
    action: str  # 'buy', 'sell', 'close'
    size: float
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = ""
    confidence: float = 0.5
    metadata: Dict = None

class BaseStrategy(ABC):
    """Abstract base for all strategies"""
    
    def __init__(self, name: str, params: Dict = None):
        self.name = name
        self.params = params or {}
        self.enabled = True
        self.performance = {'wins': 0, 'losses': 0, 'pnl': 0}
    
    @abstractmethod
    async def generate_signal(self, symbol: str, price_engine: Any, regime: str) -> Optional[Signal]:
        """Generate trading signal"""
        pass
    
    def on_trade_closed(self, pnl: float):
        """Update performance stats"""
        if pnl > 0:
            self.performance['wins'] += 1
        else:
            self.performance['losses'] += 1
        self.performance['pnl'] += pnl

class MovingAverageCrossover(BaseStrategy):
    """Classic MA Crossover with regime filtering"""
    
    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        super().__init__("MA_Cross", {'fast': fast_period, 'slow': slow_period})
        self.last_state = {}
    
    async def generate_signal(self, symbol: str, price_engine: Any, regime: str) -> Optional[Signal]:
        # Skip if ranging (choppy)
        if regime == 'ranging':
            return None
        
        # Get OHLCV data
        ohlcv = price_engine.get_ohlcv(symbol, '1h', limit=50)
        if len(ohlcv) < self.params['slow']:
            return None
        
        closes = [c.close for c in ohlcv]
        
        # Calculate MAs
        fast_ma = np.mean(closes[-self.params['fast']:])
        slow_ma = np.mean(closes[-self.params['slow']:])
        
        prev_fast = np.mean(closes[-self.params['fast']-1:-1])
        prev_slow = np.mean(closes[-self.params['slow']-1:-1])
        
        # Detect crossover
        current_price = closes[-1]
        
        # Bullish crossover
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            return Signal(
                symbol=symbol,
                action='buy',
                size=1000,  # Base size, will be sized by risk manager
                price=current_price,
                stop_loss=current_price * 0.99,  # 1% stop
                take_profit=current_price * 1.02,  # 2% target
                strategy=self.name,
                confidence=0.6
            )
        
        # Bearish crossover
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            return Signal(
                symbol=symbol,
                action='sell',
                size=1000,
                price=current_price,
                stop_loss=current_price * 1.01,
                take_profit=current_price * 0.98,
                strategy=self.name,
                confidence=0.6
            )
        
        return None

class RSIStrategy(BaseStrategy):
    """RSI Mean Reversion"""
    
    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        super().__init__("RSI_MeanReversion", {'period': period, 'overbought': overbought, 'oversold': oversold})
    
    def calculate_rsi(self, prices: List[float], period: int) -> float:
        """Calculate RSI"""
        if len(prices) < period + 1:
            return 50
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    async def generate_signal(self, symbol: str, price_engine: Any, regime: str) -> Optional[Signal]:
        # Best in ranging markets
        if regime != 'ranging':
            return None
        
        ohlcv = price_engine.get_ohlcv(symbol, '1h', limit=50)
        if len(ohlcv) < self.params['period'] + 5:
            return None
        
        closes = [c.close for c in ohlcv]
        rsi = self.calculate_rsi(closes, self.params['period'])
        current_price = closes[-1]
        
        # Oversold - buy
        if rsi < self.params['oversold']:
            return Signal(
                symbol=symbol,
                action='buy',
                size=1000,
                price=current_price,
                stop_loss=current_price * 0.995,
                take_profit=current_price * 1.01,
                strategy=self.name,
                confidence=(self.params['oversold'] - rsi) / self.params['oversold']
            )
        
        # Overbought - sell
        elif rsi > self.params['overbought']:
            return Signal(
                symbol=symbol,
                action='sell',
                size=1000,
                price=current_price,
                stop_loss=current_price * 1.005,
                take_profit=current_price * 0.99,
                strategy=self.name,
                confidence=(rsi - self.params['overbought']) / (100 - self.params['overbought'])
            )
        
        return None

class TrendFollowingStrategy(BaseStrategy):
    """Trend following with breakout detection"""
    
    def __init__(self, lookback: int = 20):
        super().__init__("TrendFollow", {'lookback': lookback})
    
    async def generate_signal(self, symbol: str, price_engine: Any, regime: str) -> Optional[Signal]:
        # Only trade trends
        if regime not in ['trending_up', 'trending_down']:
            return None
        
        ohlcv = price_engine.get_ohlcv(symbol, '1h', limit=50)
        if len(ohlcv) < self.params['lookback']:
            return None
        
        highs = [c.high for c in ohlcv[-self.params['lookback']:]]
        lows = [c.low for c in ohlcv[-self.params['lookback']:]]
        closes = [c.close for c in ohlcv]
        
        current_price = closes[-1]
        highest_high = max(highs)
        lowest_low = min(lows)
        
        # Breakout to upside
        if current_price > highest_high * 0.999 and regime == 'trending_up':
            return Signal(
                symbol=symbol,
                action='buy',
                size=2000,  # Larger size for trend
                price=current_price,
                stop_loss=lowest_low,
                take_profit=current_price + (current_price - lowest_low) * 2,  # 2:1 R:R
                strategy=self.name,
                confidence=0.75
            )
        
        # Breakout to downside
        elif current_price < lowest_low * 1.001 and regime == 'trending_down':
            return Signal(
                symbol=symbol,
                action='sell',
                size=2000,
                price=current_price,
                stop_loss=highest_high,
                take_profit=current_price - (highest_high - current_price) * 2,
                strategy=self.name,
                confidence=0.75
            )
        
        return None

class StrategyManager:
    """
    Manages multiple strategies with regime-based allocation
    """
    
    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.regime_allocations = {
            'trending_up': ['MA_Cross', 'TrendFollow'],
            'trending_down': ['MA_Cross', 'TrendFollow'],
            'ranging': ['RSI_MeanReversion'],
            'volatile': [],  # No trading in high volatility
            'unknown': ['MA_Cross']
        }
        self.signal_history: List[Signal] = []
        
        # Register default strategies
        self.register_strategy(MovingAverageCrossover())
        self.register_strategy(RSIStrategy())
        self.register_strategy(TrendFollowingStrategy())
        
        logger.info(f"StrategyManager initialized with {len(self.strategies)} strategies")
    
    def register_strategy(self, strategy: BaseStrategy):
        """Add a strategy"""
        self.strategies[strategy.name] = strategy
        logger.info(f"Registered strategy: {strategy.name}")
    
    async def generate_signals(self, market_regime: Dict[str, str], price_engine: Any) -> List[Dict]:
        """Generate signals from all appropriate strategies"""
        all_signals = []
        
        for symbol, regime in market_regime.items():
            # Get strategies for this regime
            strategy_names = self.regime_allocations.get(regime, [])
            
            for strategy_name in strategy_names:
                strategy = self.strategies.get(strategy_name)
                if not strategy or not strategy.enabled:
                    continue
                
                try:
                    signal = await strategy.generate_signal(symbol, price_engine, regime)
                    if signal:
                        # Convert to dict for compatibility
                        signal_dict = {
                            'symbol': signal.symbol,
                            'action': signal.action,
                            'size': signal.size,
                            'price': signal.price,
                            'stop_loss': signal.stop_loss,
                            'take_profit': signal.take_profit,
                            'strategy': signal.strategy,
                            'confidence': signal.confidence,
                            'regime': regime
                        }
                        all_signals.append(signal_dict)
                        self.signal_history.append(signal)
                        
                        logger.info(f"Signal generated: {signal.strategy} {signal.action} {signal.symbol} @ {signal.price:.5f}")
                        
                except Exception as e:
                    logger.error(f"Strategy error {strategy_name}: {e}")
        
        return all_signals
    
    def get_strategy_performance(self) -> Dict:
        """Get performance report for all strategies"""
        return {
            name: {
                'wins': s.performance['wins'],
                'losses': s.performance['losses'],
                'win_rate': s.performance['wins'] / (s.performance['wins'] + s.performance['losses']) if (s.performance['wins'] + s.performance['losses']) > 0 else 0,
                'total_pnl': s.performance['pnl']
            }
            for name, s in self.strategies.items()
        }
    
    def disable_strategy(self, name: str):
        """Disable a strategy"""
        if name in self.strategies:
            self.strategies[name].enabled = False
            logger.info(f"Disabled strategy: {name}")
    
    def enable_strategy(self, name: str):
        """Enable a strategy"""
        if name in self.strategies:
            self.strategies[name].enabled = True
            logger.info(f"Enabled strategy: {name}")
'''

with open(project_root / "strategies" / "__init__.py", "w") as f:
    f.write(strategy_code)

print("✓ Created strategies/__init__.py with 3 built-in strategies")
