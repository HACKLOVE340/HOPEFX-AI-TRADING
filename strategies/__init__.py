"""
Trading Strategies Module

This module contains trading strategy implementations.

Strategy types:
- Trend following (MA Crossover, EMA Crossover)
- Mean reversion (Mean Reversion, Bollinger Bands)
- Momentum (RSI, MACD, Stochastic)
- Breakout strategies (Breakout)
- Smart Money Concepts (SMC ICT)
- ICT Trading System 8 Optimal Setups (ITS-8-OS)
- Market microstructure analysis
- Machine learning-based strategies

Advanced Features:
- Strategy Brain: Multi-strategy joint analysis and consensus
- Performance-weighted signal aggregation
- Correlation analysis between strategies

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
from .smc_ict import SMCICTStrategy
from .its_8_os import ITS8OSStrategy
from .strategy_brain import StrategyBrain

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
    'SMCICTStrategy',
    'ITS8OSStrategy',
    'StrategyBrain',
]
