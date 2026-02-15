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
"""

from .manager import (
    RiskManager,
    RiskConfig,
    PositionSize,
    PositionSizeMethod,
)

__all__ = [
    'RiskManager',
    'RiskConfig',
    'PositionSize',
    'PositionSizeMethod',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Risk management with position sizing and drawdown monitoring'
