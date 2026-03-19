"""
HOPEFX Strategy Manager
Multi-strategy system with regime detection and performance tracking
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    ARBITRAGE = "arbitrage"


@dataclass
class Signal:
    """Trading signal"""
    symbol: str
    action: str  # buy, sell, close
    strength: float  # 0.0 to 1.0
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    timeframe: str
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'action': self.action,
            'strength': self.strength,
            'strategy': self.strategy,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'timeframe': self.timeframe,
            'timestamp': self.timestamp,
            'metadata': self.metadata
        }


class BaseStrategy:
    """Base strategy class"""
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.enabled = True
        self.performance = {
            'signals_generated': 0,
            'trades_taken': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0
        }
    
    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str
    ) -> List[Signal]:
        """Generate trading signals - implement in subclass"""
        raise NotImplementedError
    
    def update_performance(self, trade_result: Dict):
        """Update strategy performance metrics"""
        self.performance['trades_taken'] += 1
        # Update win rate, profit factor, etc.


class TrendFollowingStrategy(BaseStrategy):
    """Trend following strategy using moving averages"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("TrendFollowing", config)
        self.fast_period = config.get('fast_period', 20)
        self.slow_period = config.get('slow_period', 50)
        self.trend_strength_threshold = config.get('trend_strength_threshold', 0.3)
    
    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str
    ) -> List[Signal]:
        """Generate trend following signals"""
        if market_regime not in ['trending_up', 'trending_down']:
            return []
        
        try:
            closes = np.array([c.close for c in price_data])
            if len(closes) < self.slow_period:
                return []
            
            # Calculate moving averages
            fast_ma = np.mean(closes[-self.fast_period:])
            slow_ma = np.mean(closes[-self.slow_period:])
            
            # Calculate trend strength (ADX-like)
            high_low_range = np.mean([c.high - c.low for c in price_data[-14:]])
            directional_movement = abs(fast_ma - slow_ma)
            trend_strength = directional_movement / high_low_range if high_low_range > 0 else 0
            
            if trend_strength < self.trend_strength_threshold:
                return []
            
            current_price = closes[-1]
            
            # Generate signal
            if fast_ma > slow_ma and market_regime == 'trending_up':
                return [Signal(
                    symbol=symbol,
                    action='buy',
                    strength=min(trend_strength * 2, 1.0),
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=current_price * 0.98,  # 2% stop
                    take_profit=current_price * 1.06,  # 6% target (3:1 R/R)
                    timeframe='1h',
                    metadata={
                        'fast_ma': fast_ma,
                        'slow_ma': slow_ma,
                        'trend_strength': trend_strength
                    }
                )]
            
            elif fast_ma < slow_ma and market_regime == 'trending_down':
                return [Signal(
                    symbol=symbol,
                    action='sell',
                    strength=min(trend_strength * 2, 1.0),
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=current_price * 1.02,
                    take_profit=current_price * 0.94,
                    timeframe='1h',
                    metadata={
                        'fast_ma': fast_ma,
                        'slow_ma': slow_ma,
                        'trend_strength': trend_strength
                    }
                )]
            
            return []
            
        except Exception as e:
            logger.error(f"Error in trend strategy for {symbol}: {e}")
            return []


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy using Bollinger Bands"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("MeanReversion", config)
        self.period = config.get('period', 20)
        self.std_dev = config.get('std_dev', 2.0)
        self.oversold_threshold = config.get('oversold_threshold', -2.0)
        self.overbought_threshold = config.get('overbought_threshold', 2.0)
    
    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str
    ) -> List[Signal]:
        """Generate mean reversion signals"""
        if market_regime != 'ranging':
            return []
        
        try:
            closes = np.array([c.close for c in price_data])
            if len(closes) < self.period:
                return []
            
            # Calculate Bollinger Bands
            sma = np.mean(closes[-self.period:])
            std = np.std(closes[-self.period:])
            
            upper_band = sma + (std * self.std_dev)
            lower_band = sma - (std * self.std_dev)
            
            current_price = closes[-1]
            
            # Z-score
            z_score = (current_price - sma) / std if std > 0 else 0
            
            signals = []
            
            # Oversold - buy signal
            if z_score < self.oversold_threshold and current_price < lower_band:
                signals.append(Signal(
                    symbol=symbol,
                    action='buy',
                    strength=min(abs(z_score) / 3, 1.0),
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=lower_band * 0.99,
                    take_profit=sma,
                    timeframe='1h',
                    metadata={
                        'z_score': z_score,
                        'lower_band': lower_band,
                        'upper_band': upper_band,
                        'sma': sma
                    }
                ))
            
            # Overbought - sell signal
            elif z_score > self.overbought_threshold and current_price > upper_band:
                signals.append(Signal(
                    symbol=symbol,
                    action='sell',
                    strength=min(abs(z_score) / 3, 1.0),
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=upper_band * 1.01,
                    take_profit=sma,
                    timeframe='1h',
                    metadata={
                        'z_score': z_score,
                        'lower_band': lower_band,
                        'upper_band': upper_band,
                        'sma': sma
                    }
                ))
            
            return signals
            
        except Exception as e:
            logger.error(f"Error in mean reversion strategy for {symbol}: {e}")
            return []


class BreakoutStrategy(BaseStrategy):
    """Breakout strategy using support/resistance levels"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Breakout", config)
        self.lookback_period = config.get('lookback_period', 20)
        self.breakout_threshold = config.get('breakout_threshold', 0.001)
    
    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str
    ) -> List[Signal]:
        """Generate breakout signals"""
        if market_regime != 'ranging':
            return []
        
        try:
            highs = np.array([c.high for c in price_data[-self.lookback_period:]])
            lows = np.array([c.low for c in price_data[-self.lookback_period:]])
            
            if len(highs) < self.lookback_period:
                return []
            
            resistance = np.max(highs)
            support = np.min(lows)
            
            current_price = price_data[-1].close
            
            # Check for breakout
            if current_price > resistance * (1 + self.breakout_threshold):
                return [Signal(
                    symbol=symbol,
                    action='buy',
                    strength=0.7,
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=support,
                    take_profit=current_price + (current_price - support) * 2,
                    timeframe='1h',
                    metadata={
                        'resistance': resistance,
                        'support': support,
                        'breakout_type': 'resistance'
                    }
                )]
            
            elif current_price < support * (1 - self.breakout_threshold):
                return [Signal(
                    symbol=symbol,
                    action='sell',
                    strength=0.7,
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=resistance,
                    take_profit=current_price - (resistance - current_price) * 2,
                    timeframe='1h',
                    metadata={
                        'resistance': resistance,
                        'support': support,
                        'breakout_type': 'support'
                    }
                )]
            
            return []
            
        except Exception as e:
            logger.error(f"Error in breakout strategy for {symbol}: {e}")
            return []


class StrategyManager:
    """
    Central strategy management system
    
    Features:
    - Multiple strategy registration
    - Regime-based strategy selection
    - Signal aggregation and deduplication
    - Performance tracking per strategy
    """
    
    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self._initialize_default_strategies()
    
    def _initialize_default_strategies(self):
        """Initialize default strategies"""
        self.register_strategy(TrendFollowingStrategy({
            'fast_period': 20,
            'slow_period': 50
        }))
        
        self.register_strategy(MeanReversionStrategy({
            'period': 20,
            'std_dev': 2.0
        }))
        
        self.register_strategy(BreakoutStrategy({
            'lookback_period': 20
        }))
    
    def register_strategy(self, strategy: BaseStrategy):
        """Register a strategy"""
        self.strategies[strategy.name] = strategy
        logger.info(f"Registered strategy: {strategy.name}")
    
    def enable_strategy(self, name: str):
        """Enable a strategy"""
        if name in self.strategies:
            self.strategies[name].enabled = True
            logger.info(f"Enabled strategy: {name}")
    
    def disable_strategy(self, name: str):
        """Disable a strategy"""
        if name in self.strategies:
            self.strategies[name].enabled = False
            logger.info(f"Disabled strategy: {name}")
    
    async def generate_signals(
        self,
        market_regimes: Dict[str, Any],
        price_engine: Any
    ) -> List[Dict]:
        """
        Generate signals from all enabled strategies
        
        Args:
            market_regimes: Dict of symbol -> MarketRegime
            price_engine: Price data source
        """
        all_signals = []
        
        for symbol, regime in market_regimes.items():
            regime_value = regime.value if hasattr(regime, 'value') else str(regime)
            
            # Get price data
            try:
                ohlcv = price_engine.get_ohlcv(symbol, '1h', limit=100)
                if not ohlcv or len(ohlcv) < 50:
                    continue
            except Exception as e:
                logger.warning(f"Could not get data for {symbol}: {e}")
                continue
            
            # Generate signals from each strategy
            for strategy in self.strategies.values():
                if not strategy.enabled:
                    continue
                
                try:
                    signals = await strategy.generate_signals(
                        symbol=symbol,
                        price_data=ohlcv,
                        market_regime=regime_value
                    )
                    
                    for signal in signals:
                        all_signals.append(signal.to_dict())
                        strategy.performance['signals_generated'] += 1
                        
                except Exception as e:
                    logger.error(f"Strategy {strategy.name} error for {symbol}: {e}")
        
        # Deduplicate signals (same symbol and action)
        deduplicated = self._deduplicate_signals(all_signals)
        
        # Sort by strength
        deduplicated.sort(key=lambda x: x['strength'], reverse=True)
        
        return deduplicated
    
    def _deduplicate_signals(self, signals: List[Dict]) -> List[Dict]:
        """Remove duplicate signals, keeping strongest"""
        seen = {}
        
        for signal in signals:
            key = (signal['symbol'], signal['action'])
            
            if key not in seen or signal['strength'] > seen[key]['strength']:
                seen[key] = signal
        
        return list(seen.values())
    
    def get_strategy_performance(self) -> Dict[str, Dict]:
        """Get performance metrics for all strategies"""
        return {
            name: {
                'enabled': strat.enabled,
                **strat.performance
            }
            for name, strat in self.strategies.items()
        }
    
    def update_strategy_performance(self, strategy_name: str, trade_result: Dict):
        """Update performance for a strategy"""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].update_performance(trade_result)
