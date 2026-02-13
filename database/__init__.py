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
    OHLCV,
    TickData,
    OrderBook,
    # Trading Models
    Trade,
    Order,
    Position,
    Portfolio,
    Account,
    # Signal Models
    Signal,
    Prediction,
    # News & Sentiment
    NewsArticle,
    SentimentAnalysis,
    EconomicEvent,
    # Backtest Models
    BacktestRun,
    BacktestTrade,
    PerformanceMetrics,
)

__all__ = [
    'Base',
    # Market Data
    'OHLCV',
    'TickData',
    'OrderBook',
    # Trading
    'Trade',
    'Order',
    'Position',
    'Portfolio',
    'Account',
    # Signals
    'Signal',
    'Prediction',
    # News
    'NewsArticle',
    'SentimentAnalysis',
    'EconomicEvent',
    # Backtesting
    'BacktestRun',
    'BacktestTrade',
    'PerformanceMetrics',
]
