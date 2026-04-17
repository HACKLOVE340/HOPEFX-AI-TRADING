# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
websocket — WebSocket connection manager for real-time data streaming.

Public API
----------
    WebSocketManager    Manages all active WebSocket connections with
                        per-channel subscriptions, heartbeat monitoring,
                        and graceful disconnect handling.
    get_ws_manager()    Returns the singleton WebSocketManager instance.

Usage
-----
    from websocket import get_ws_manager
    ws_manager = get_ws_manager()
    await ws_manager.broadcast("prices", {"symbol": "XAU_USD", "bid": 3200.0})
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from websocket.manager import WebSocketManager, get_ws_manager  # noqa: F401
except Exception as _exc:
    logger.debug("websocket.manager unavailable: %s", _exc)
    WebSocketManager = None  # type: ignore[assignment,misc]
    get_ws_manager = None  # type: ignore[assignment]

__all__ = ["WebSocketManager", "get_ws_manager"]
