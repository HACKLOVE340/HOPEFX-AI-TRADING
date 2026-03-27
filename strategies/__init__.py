# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Strategies package — exports all strategy classes and the StrategyBrain.
"""

from .base import BaseStrategy, Signal, SignalType, StrategyConfig, StrategyStatus
from .bollinger_bands import BollingerBandsStrategy
from .breakout import BreakoutStrategy
from .ema_crossover import EMAcrossoverStrategy
from .its_8_os import ITS8OSStrategy
from .ma_crossover import MovingAverageCrossover
from .macd_strategy import MACDStrategy
from .manager import StrategyManager
from .mean_reversion import MeanReversionStrategy
from .rsi_strategy import RSIStrategy
from .smc_ict import SMCICTStrategy
from .stochastic import StochasticStrategy
from .strategy_brain import StrategyBrain

__all__ = [
    "BaseStrategy",
    "Signal",
    "SignalType",
    "StrategyStatus",
    "StrategyConfig",
    "StrategyManager",
    "StrategyBrain",
    "MovingAverageCrossover",
    "EMAcrossoverStrategy",
    "RSIStrategy",
    "MACDStrategy",
    "BollingerBandsStrategy",
    "MeanReversionStrategy",
    "BreakoutStrategy",
    "StochasticStrategy",
    "SMCICTStrategy",
    "ITS8OSStrategy",
]

__version__ = "1.0.0"
