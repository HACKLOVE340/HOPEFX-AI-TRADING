"""
API Endpoints Module

This module provides REST API endpoints for the trading framework.

Endpoint categories:
- Trading operations (orders, positions, trades)
- Market data (OHLCV, ticks, orderbook)
- Portfolio management
- Backtesting
- System status and health
- Configuration management
- Performance metrics
- Admin dashboard
- Real-time trading signals

Uses FastAPI for modern async API development.
"""

from . import trading, admin
from .signals import (
    RealTimeSignalService,
    TradingSignal,
    SignalAlert,
    SignalAnalytics,
    SignalStrength,
    SignalDirection,
)

__all__ = [
    'trading',
    'admin',
    'RealTimeSignalService',
    'TradingSignal',
    'SignalAlert',
    'SignalAnalytics',
    'SignalStrength',
    'SignalDirection',
]

# Module metadata
__version__ = '2.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'REST API endpoints for trading operations and real-time signals'
