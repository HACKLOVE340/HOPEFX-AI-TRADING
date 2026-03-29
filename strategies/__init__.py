# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
strategies/ — Backtestable strategy classes (NOT the live signal engine)
========================================================================
This package contains all BaseStrategy subclasses used by the backtesting
engine and paper trading simulator. Each class implements generate_signal()
against historical OHLCV bars.

DO NOT add live event-loop code here.
The live ML signal producer lives in strategy/ (singular) → engine.py.

Package map
-----------
  strategies/base.py          — BaseStrategy ABC, Signal, SignalType
  strategies/manager.py       — StrategyManager (loads/runs strategies)
  strategies/strategy_brain.py — StrategyBrain (regime-aware router)
  strategies/<name>.py        — individual strategy implementations
  strategy/engine.py          — StrategyEngine (live signal producer, separate package)
  backtesting/                — canonical backtest engine
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
from .pullback_strategy import PullbackStrategy
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
    "PullbackStrategy",
]

__version__ = "1.0.0"
