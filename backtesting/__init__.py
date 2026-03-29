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
from backtesting.data_sources import YahooFinanceSource, CSVDataSource
from backtesting.engine import BacktestEngine
from backtesting.engine_config import (
    BacktestConfig,
    BacktestResult,
    SimulatedBroker,
    HistoricalDataLoader,
    run_backtest,
)
try:
    from backtesting.enhanced_engine import EnhancedBacktestEngine
except Exception:  # optional heavy deps (numba, cupy)
    EnhancedBacktestEngine = None  # type: ignore[assignment,misc]
from backtesting.events import MarketEvent, SignalEvent, OrderEvent, FillEvent
from backtesting.execution import SimulatedExecutionHandler
from backtesting.metrics import PerformanceMetrics
from backtesting.portfolio import Portfolio
from backtesting.optimizer import ParameterOptimizer
from backtesting.walk_forward import WalkForwardAnalysis
from backtesting.reports import ReportGenerator
from backtesting.plots import PerformancePlotter

__all__ = [
    # Event-driven engine (tick/bar level)
    "BacktestEngine",
    "DataHandler",
    "YahooFinanceSource",
    "CSVDataSource",
    "MarketEvent",
    "SignalEvent",
    "OrderEvent",
    "FillEvent",
    "SimulatedExecutionHandler",
    "PerformanceMetrics",
    "Portfolio",
    "ParameterOptimizer",
    "WalkForwardAnalysis",
    "ReportGenerator",
    "PerformancePlotter",
    # Config-driven engine (OHLCV bar level, Kelly sizing, Monte Carlo)
    "BacktestConfig",
    "BacktestResult",
    "SimulatedBroker",
    "HistoricalDataLoader",
    "run_backtest",
    # Institutional engine (tick-level, Almgren-Chriss, GPU-optional)
    "EnhancedBacktestEngine",
]

__version__ = "1.0.0"
