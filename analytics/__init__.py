"""
Advanced Analytics Module

Portfolio optimization, options trading, and advanced simulations.
"""

from .portfolio import PortfolioOptimizer
from .options import OptionsAnalyzer
from .simulations import SimulationEngine
from .risk import RiskAnalyzer

portfolio_optimizer = PortfolioOptimizer()
options_analyzer = OptionsAnalyzer()
simulation_engine = SimulationEngine()
risk_analyzer = RiskAnalyzer()

__all__ = [
    'PortfolioOptimizer',
    'OptionsAnalyzer',
    'SimulationEngine',
    'RiskAnalyzer',
    'portfolio_optimizer',
    'options_analyzer',
    'simulation_engine',
    'risk_analyzer',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Advanced analytics with portfolio optimization, options, and simulations'
