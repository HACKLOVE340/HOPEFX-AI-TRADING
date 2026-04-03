# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced Analytics Module

Portfolio optimization, options trading, advanced simulations,
and performance analytics.
"""

from .options import OptionsAnalyzer
from .performance import (
    EquityPoint,
    MetricPeriod,
    PerformanceAnalytics,
    PerformanceReport,
    StrategyPerformance,
    TradeRecord,
)
from .portfolio import PortfolioAnalytics as PortfolioOptimizer
from .risk import RiskAnalyzer
from .simulations import SimulationEngine

portfolio_optimizer = PortfolioOptimizer()
options_analyzer = OptionsAnalyzer()
simulation_engine = SimulationEngine()
risk_analyzer = RiskAnalyzer()

__all__ = [
    "EquityPoint",
    "MetricPeriod",
    "OptionsAnalyzer",
    "PerformanceAnalytics",
    "PerformanceReport",
    "PortfolioOptimizer",
    "RiskAnalyzer",
    "SimulationEngine",
    "StrategyPerformance",
    "TradeRecord",
    "options_analyzer",
    "portfolio_optimizer",
    "risk_analyzer",
    "simulation_engine",
]

# Module metadata
__version__ = "2.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Advanced analytics with portfolio optimization, options, simulations, and performance tracking"
