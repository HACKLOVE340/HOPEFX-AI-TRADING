"""
Trading Strategies Module

This module contains trading strategy implementations.

Strategy types:
- Trend following (MA Crossover, EMA Crossover)
- Mean reversion (Mean Reversion, Bollinger Bands)
- Momentum (RSI, MACD, Stochastic)
- Breakout strategies (Breakout)
- Smart Money Concepts (SMC)
- Market microstructure analysis
- Machine learning-based strategies

Each strategy implements:
- Signal generation
- Entry/exit logic
- Risk management
- Performance tracking
"""

from .base import (
    BaseStrategy,
    Signal,
    SignalType,
    StrategyStatus,
    StrategyConfig,
)
from .manager import StrategyManager
from .ma_crossover import MovingAverageCrossover
from .mean_reversion import MeanReversionStrategy
from .rsi_strategy import RSIStrategy
from .bollinger_bands import BollingerBandsStrategy
from .macd_strategy import MACDStrategy
from .breakout import BreakoutStrategy
from .ema_crossover import EMAcrossoverStrategy
from .stochastic import StochasticStrategy

__all__ = [
    'BaseStrategy',
    'Signal',
    'SignalType',
    'StrategyStatus',
    'StrategyConfig',
    'StrategyManager',
    'MovingAverageCrossover',
    'MeanReversionStrategy',
    'RSIStrategy',
    'BollingerBandsStrategy',
    'MACDStrategy',
    'BreakoutStrategy',
    'EMAcrossoverStrategy',
    'StochasticStrategy',
]
