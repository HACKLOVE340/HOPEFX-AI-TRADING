"""
Trading Strategies Module

This module contains trading strategy implementations.

Strategy types:
- Trend following
- Mean reversion
- Breakout strategies
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

__all__ = [
    'BaseStrategy',
    'Signal',
    'SignalType',
    'StrategyStatus',
    'StrategyConfig',
    'StrategyManager',
    'MovingAverageCrossover',
]
