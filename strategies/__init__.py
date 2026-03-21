"""
Strategies package — exports all strategy classes and the StrategyBrain.
"""

from .base import BaseStrategy, Signal, SignalType, StrategyStatus, StrategyConfig
from .manager import StrategyManager
from .strategy_brain import StrategyBrain
from .ma_crossover import MovingAverageCrossover
from .ema_crossover import EMAcrossoverStrategy
from .rsi_strategy import RSIStrategy
from .macd_strategy import MACDStrategy
from .bollinger_bands import BollingerBandsStrategy
from .mean_reversion import MeanReversionStrategy
from .breakout import BreakoutStrategy
from .stochastic import StochasticStrategy
from .smc_ict import SMCICTStrategy
from .its_8_os import ITS8OSStrategy

__all__ = [
    "BaseStrategy", "Signal", "SignalType", "StrategyStatus", "StrategyConfig",
    "StrategyManager", "StrategyBrain",
    "MovingAverageCrossover", "EMAcrossoverStrategy", "RSIStrategy",
    "MACDStrategy", "BollingerBandsStrategy", "MeanReversionStrategy",
    "BreakoutStrategy", "StochasticStrategy", "SMCICTStrategy", "ITS8OSStrategy",
]
