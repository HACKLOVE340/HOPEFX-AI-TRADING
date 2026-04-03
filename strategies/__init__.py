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

Purpose
-------
These strategies are designed for:
  - Offline backtesting via backtesting/engine_config.py (BacktestEngine)
  - Paper trading via brokers/paper_trading.py (PaperTradingBroker)
  - Walk-forward optimisation via backtesting/walk_forward.py
  - A/B testing via api/advanced_trading.py

They are NOT wired into the live Redis event loop. The live signal producer
is strategy/engine.py (StrategyEngine), which uses an ML model, not these
rule-based classes.

Data flow (backtesting)
-----------------------
  OHLCV DataFrame
      │
      ▼
  BaseStrategy.generate_signal(bar)   → Signal(type, confidence, …)
      │
      ▼
  BacktestEngine._process_signal()    → SimulatedBroker.place_market_order()
      │
      ▼
  BacktestResult                      → metrics, equity curve, trade log

Data flow (paper trading)
-------------------------
  Market data feed (data/scheduler.py)
      │
      ▼
  StrategyManager.run_all(bar)        → aggregated Signal
      │
      ▼
  StrategyBrain.combine_signals()     → consensus Signal (weighted vote)
      │
      ▼
  PaperTradingBroker.place_order()

Adding a new strategy
---------------------
1. Create strategies/<name>.py inheriting from BaseStrategy.
2. Implement generate_signal(bar: pd.Series) -> Optional[Signal].
3. Import and add to __all__ below.
4. Register in strategies/manager.py STRATEGY_REGISTRY.

Package map
-----------
  strategies/base.py              BaseStrategy ABC, Signal, SignalType, StrategyConfig
  strategies/manager.py           StrategyManager — loads/runs all registered strategies
  strategies/strategy_brain.py    StrategyBrain — regime-aware multi-strategy router
  strategies/regime_router.py     RegimeRouter — market regime detection
  strategies/base_enhanced.py     EnhancedBaseStrategy — extended ABC with ML hooks
  strategies/<name>.py            individual strategy implementations (13 strategies)
  strategy/engine.py              StrategyEngine — live ML signal producer (separate package)
  backtesting/engine_config.py    BacktestEngine — runs strategies against historical data
  backtesting/walk_forward.py     WalkForwardAnalysis — OOS validation

DO NOT add live event-loop code here.
The live ML signal producer lives in strategy/ (singular) → engine.py.

Strategies registered in this package
--------------------------------------
  MovingAverageCrossover   — dual SMA crossover
  EMAcrossoverStrategy     — dual EMA crossover
  RSIStrategy              — RSI overbought/oversold
  MACDStrategy             — MACD signal line crossover
  BollingerBandsStrategy   — Bollinger Band mean reversion
  MeanReversionStrategy    — z-score mean reversion
  BreakoutStrategy         — range breakout
  StochasticStrategy       — stochastic oscillator
  SMCICTStrategy           — Smart Money Concepts / ICT
  ITS8OSStrategy           — ITS-8 oscillator system
  PullbackStrategy         — trend pullback entry
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
    # ABC and data types
    "BaseStrategy",
    "BollingerBandsStrategy",
    "BreakoutStrategy",
    "EMAcrossoverStrategy",
    "ITS8OSStrategy",
    "MACDStrategy",
    "MeanReversionStrategy",
    # Trend-following
    "MovingAverageCrossover",
    "PullbackStrategy",
    # Mean-reversion
    "RSIStrategy",
    # Pattern / institutional
    "SMCICTStrategy",
    "Signal",
    "SignalType",
    "StochasticStrategy",
    "StrategyBrain",
    "StrategyConfig",
    # Orchestration
    "StrategyManager",
    "StrategyStatus",
]

__version__ = "1.0.0"
