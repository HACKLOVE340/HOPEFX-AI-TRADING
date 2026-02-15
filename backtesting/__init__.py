"""
Backtesting Module

Comprehensive backtesting framework for trading strategies.
"""

from backtesting.data_handler import DataHandler
from backtesting.data_sources import YahooFinanceSource, CSVDataSource
from backtesting.engine import BacktestEngine
from backtesting.events import MarketEvent, SignalEvent, OrderEvent, FillEvent
from backtesting.execution import SimulatedExecutionHandler
from backtesting.metrics import PerformanceMetrics
from backtesting.portfolio import Portfolio
from backtesting.optimizer import ParameterOptimizer
from backtesting.walk_forward import WalkForwardAnalysis
from backtesting.reports import ReportGenerator
from backtesting.plots import PerformancePlotter

__all__ = [
    'DataHandler',
    'YahooFinanceSource',
    'CSVDataSource',
    'BacktestEngine',
    'MarketEvent',
    'SignalEvent',
    'OrderEvent',
    'FillEvent',
    'SimulatedExecutionHandler',
    'PerformanceMetrics',
    'Portfolio',
    'ParameterOptimizer',
    'WalkForwardAnalysis',
    'ReportGenerator',
    'PerformancePlotter',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Comprehensive backtesting engine with optimization and walk-forward analysis'
