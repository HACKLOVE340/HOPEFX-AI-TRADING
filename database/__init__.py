# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
    Account,
    # Signal Models
    AISignal,
    Base,
    # Market Data Models
    MarketData,  # OHLCV data
    # News & Sentiment
    NewsData,
    Order,
    OrderBook,
    # Backtest Models - using generic PerformanceMetrics
    PerformanceMetrics,
    Position,
    Prediction,
    TickData,
    # Trading Models
    Trade,
)

__all__ = [
    # Signals
    "AISignal",
    "Account",
    "Base",
    # Market Data
    "MarketData",
    # News
    "NewsData",
    "Order",
    "OrderBook",
    # Backtesting
    "PerformanceMetrics",
    "Position",
    "Prediction",
    "TickData",
    # Trading
    "Trade",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "SQLAlchemy ORM models for trading data"
