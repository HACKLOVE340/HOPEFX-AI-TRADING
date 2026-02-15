"""
Risk Management Module

This module provides risk management and position sizing.

Components:
- Position sizing (Kelly Criterion, Fixed Fractional, etc.)
- Portfolio risk calculation
- Drawdown monitoring
- Stop loss management
- Risk-adjusted returns
- Value at Risk (VaR)
- Maximum Drawdown tracking
- Monte Carlo simulations
- Stress testing
"""

from .manager import (
    RiskManager,
    RiskConfig,
    PositionSize,
    PositionSizeMethod,
)
from .advanced_analytics import (
    AdvancedRiskAnalytics,
    VaRResult,
    MonteCarloResult,
    StressTestResult,
    DrawdownAnalysis,
    RiskMetricType,
)

__all__ = [
    'RiskManager',
    'RiskConfig',
    'PositionSize',
    'PositionSizeMethod',
    'AdvancedRiskAnalytics',
    'VaRResult',
    'MonteCarloResult',
    'StressTestResult',
    'DrawdownAnalysis',
    'RiskMetricType',
]

# Module metadata
__version__ = '2.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Advanced risk management with VaR, Monte Carlo, and stress testing'
