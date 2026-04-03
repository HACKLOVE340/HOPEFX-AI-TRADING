# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Backtesting Module

Comprehensive backtesting framework for trading strategies.
"""

from backtesting.data_handler import DataHandler
from backtesting.data_sources import CSVDataSource, YahooFinanceSource
from backtesting.engine import BacktestEngine
from backtesting.engine_config import (
    BacktestConfig,
    BacktestResult,
    HistoricalDataLoader,
    SimulatedBroker,
    run_backtest,
)

try:
    from backtesting.enhanced_engine import EnhancedBacktestEngine
except Exception:  # optional heavy deps (numba, cupy)
    EnhancedBacktestEngine = None  # type: ignore[assignment,misc]
from backtesting.events import FillEvent, MarketEvent, OrderEvent, SignalEvent
from backtesting.execution import SimulatedExecutionHandler
from backtesting.metrics import PerformanceMetrics
from backtesting.optimizer import ParameterOptimizer
from backtesting.plots import PerformancePlotter
from backtesting.portfolio import Portfolio
from backtesting.reports import ReportGenerator
from backtesting.walk_forward import WalkForwardAnalysis

__all__ = [
    # Config-driven engine (OHLCV bar level, Kelly sizing, Monte Carlo)
    "BacktestConfig",
    # Event-driven engine (tick/bar level)
    "BacktestEngine",
    "BacktestResult",
    "CSVDataSource",
    "DataHandler",
    # Institutional engine (tick-level, Almgren-Chriss, GPU-optional)
    "EnhancedBacktestEngine",
    "FillEvent",
    "HistoricalDataLoader",
    "MarketEvent",
    "OrderEvent",
    "ParameterOptimizer",
    "PerformanceMetrics",
    "PerformancePlotter",
    "Portfolio",
    "ReportGenerator",
    "SignalEvent",
    "SimulatedBroker",
    "SimulatedExecutionHandler",
    "WalkForwardAnalysis",
    "YahooFinanceSource",
    "run_backtest",
]

__version__ = "1.0.0"
