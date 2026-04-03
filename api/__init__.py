# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
- WebSocket real-time streaming

Uses FastAPI for modern async API development.
"""

from . import admin, trading
from .signals import (
    RealTimeSignalService,
    SignalAlert,
    SignalAnalytics,
    SignalDirection,
    SignalStrength,
    TradingSignal,
)
from .websocket_server import (
    ChannelType,
    ConnectionInfo,
    WebSocketManager,
    WebSocketMessage,
    create_websocket_router,
    get_websocket_manager,
)

__all__ = [
    "ChannelType",
    "ConnectionInfo",
    "RealTimeSignalService",
    "SignalAlert",
    "SignalAnalytics",
    "SignalDirection",
    "SignalStrength",
    "TradingSignal",
    # WebSocket
    "WebSocketManager",
    "WebSocketMessage",
    "admin",
    "create_websocket_router",
    "get_websocket_manager",
    "trading",
]

# Module metadata
__version__ = "2.1.0"
__author__ = "HOPEFX Development Team"
__description__ = "REST API endpoints for trading operations, real-time signals, and WebSocket streaming"
