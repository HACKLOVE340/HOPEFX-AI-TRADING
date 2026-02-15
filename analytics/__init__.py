"""
Advanced Analytics Module

Portfolio optimization, options trading, advanced simulations,
and performance analytics.
"""

from .portfolio import PortfolioOptimizer
from .options import OptionsAnalyzer
from .simulations import SimulationEngine
from .risk import RiskAnalyzer
from .performance import (
    PerformanceAnalytics,
    PerformanceReport,
    StrategyPerformance,
    TradeRecord,
    EquityPoint,
    MetricPeriod,
)

portfolio_optimizer = PortfolioOptimizer()
options_analyzer = OptionsAnalyzer()
simulation_engine = SimulationEngine()
risk_analyzer = RiskAnalyzer()

__all__ = [
    'PortfolioOptimizer',
    'OptionsAnalyzer',
    'SimulationEngine',
    'RiskAnalyzer',
    'PerformanceAnalytics',
    'PerformanceReport',
    'StrategyPerformance',
    'TradeRecord',
    'EquityPoint',
    'MetricPeriod',
    'portfolio_optimizer',
    'options_analyzer',
    'simulation_engine',
    'risk_analyzer',
]

# Module metadata
__version__ = '2.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Advanced analytics with portfolio optimization, options, simulations, and performance tracking'
