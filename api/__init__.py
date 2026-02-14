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

Uses FastAPI for modern async API development.
"""

from . import trading, admin

__all__ = ['trading', 'admin']
