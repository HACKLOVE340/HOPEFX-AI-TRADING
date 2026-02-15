"""
Database Module

This module provides SQLAlchemy ORM models for the HOPEFX AI Trading framework.

Main components:
- Base: SQLAlchemy declarative base
- Database models for:
  - Market data (OHLCV, TickData, OrderBook)
  - Trading (Trade, Order, Position, Portfolio, Account)
  - Signals and predictions
  - News and sentiment analysis
  - Backtesting and performance metrics
"""

from .models import (
    Base,
    # Market Data Models
    MarketData,  # OHLCV data
    TickData,
    OrderBook,
    # Trading Models
    Trade,
    Order,
    Position,
    Account,
    # Signal Models
    AISignal,
    Prediction,
    # News & Sentiment
    NewsData,
    # Backtest Models - using generic PerformanceMetrics
    PerformanceMetrics,
)

__all__ = [
    'Base',
    # Market Data
    'MarketData',
    'TickData',
    'OrderBook',
    # Trading
    'Trade',
    'Order',
    'Position',
    'Account',
    # Signals
    'AISignal',
    'Prediction',
    # News
    'NewsData',
    # Backtesting
    'PerformanceMetrics',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'SQLAlchemy ORM models for trading data'
