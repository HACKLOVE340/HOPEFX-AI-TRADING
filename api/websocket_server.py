# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
WebSocket Server for Real-Time Trading Data

Provides real-time streaming capabilities for:
- Price updates
- Order book (Depth of Market) updates
- Trade execution notifications
- Signal broadcasts
- Alert notifications

Inspired by top platforms: TradingView, cTrader, MT5
"""

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ChannelType(Enum):
    """WebSocket channel types."""

    PRICES = "prices"
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    SIGNALS = "signals"
    ALERTS = "alerts"
    POSITIONS = "positions"
    ACCOUNT = "account"


@dataclass
class WebSocketMessage:
    """Standard WebSocket message format."""

    event: str
    channel: str
    data: dict[str, Any]
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    sequence: int = 0

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection."""

    connection_id: str
    connected_at: datetime
    subscriptions: set[str] = field(default_factory=set)
    user_id: str | None = None
    authenticated: bool = False
    messages_sent: int = 0
    messages_received: int = 0
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(UTC))


class WebSocketManager:
    """
    WebSocket connection manager for real-time data streaming.

    Features:
    - Multi-channel subscription model
    - Connection lifecycle management
    - Heartbeat/ping-pong support
    - Rate limiting
    - Auto-reconnection support (client-side)
    - Message sequencing
    - Authentication support

    Usage:
        manager = WebSocketManager()

        # On client connect
        conn_id = manager.register_connection(websocket)

        # Subscribe to channels
        await manager.subscribe(conn_id, 'prices:XAUUSD')
        await manager.subscribe(conn_id, 'orderbook:XAUUSD')

        # Broadcast updates
        await manager.broadcast('prices:XAUUSD', price_data)

        # On client disconnect
        manager.unregister_connection(conn_id)
    """

    def __init__(self, config: dict | None = None):
        """
        Initialize WebSocket manager.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Connection storage (using weak references to allow GC)
        self._connections: dict[str, Any] = {}
        self._connection_info: dict[str, ConnectionInfo] = {}

        # Channel subscriptions: channel -> set of connection_ids
        self._channels: dict[str, set[str]] = {}

        # Message sequence counter
        self._sequence = 0

        # Configuration
        self._heartbeat_interval = self.config.get("heartbeat_interval", 30)
        self._max_subscriptions = self.config.get("max_subscriptions", 100)
        self._rate_limit = self.config.get("rate_limit", 100)  # msgs per second

        # Event callbacks
        self._on_connect_callbacks: list[Callable] = []
        self._on_disconnect_callbacks: list[Callable] = []
        self._on_message_callbacks: list[Callable] = []

        # Statistics
        self._stats = {
            "total_connections": 0,
            "total_messages_sent": 0,
            "total_messages_received": 0,
            "active_channels": 0,
        }

        logger.info("WebSocket Manager initialized")

    # ================================================================
    # CONNECTION MANAGEMENT
    # ================================================================

    def register_connection(
        self,
        websocket: Any,
        connection_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        Register a new WebSocket connection.

        Args:
            websocket: WebSocket connection object
            connection_id: Optional custom connection ID
            user_id: Optional user ID for authenticated connections

        Returns:
            Connection ID
        """
        if connection_id is None:
            connection_id = f"ws_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"

        self._connections[connection_id] = websocket
        self._connection_info[connection_id] = ConnectionInfo(
            connection_id=connection_id,
            connected_at=datetime.now(UTC),
            user_id=user_id,
            authenticated=user_id is not None,
        )

        self._stats["total_connections"] += 1

        # Notify callbacks
        for callback in self._on_connect_callbacks:
            try:
                callback(connection_id, self._connection_info[connection_id])
            except Exception as e:
                logger.error("Error in connect callback: %s", e)

        logger.info("WebSocket registered: %s", connection_id)

        return connection_id

    def unregister_connection(self, connection_id: str):
        """
        Unregister a WebSocket connection.

        Args:
            connection_id: Connection ID to unregister
        """
        if connection_id not in self._connections:
            return

        # Remove from all channels
        info = self._connection_info.get(connection_id)
        if info:
            for channel in list(info.subscriptions):
                self._unsubscribe_internal(connection_id, channel)

        # Remove connection
        del self._connections[connection_id]
        if connection_id in self._connection_info:
            del self._connection_info[connection_id]

        # Notify callbacks
        for callback in self._on_disconnect_callbacks:
            try:
                callback(connection_id)
            except Exception as e:
                logger.error("Error in disconnect callback: %s", e)

        logger.info("WebSocket unregistered: %s", connection_id)

    def get_connection_info(self, connection_id: str) -> ConnectionInfo | None:
        """Get information about a connection."""
        return self._connection_info.get(connection_id)

    def get_active_connections(self) -> list[str]:
        """Get list of active connection IDs."""
        return list(self._connections.keys())

    # ================================================================
    # SUBSCRIPTION MANAGEMENT
    # ================================================================

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        """
        Subscribe a connection to a channel.

        Args:
            connection_id: Connection ID
            channel: Channel name (e.g., 'prices:XAUUSD', 'orderbook:EURUSD')

        Returns:
            True if subscribed successfully
        """
        if connection_id not in self._connections:
            logger.warning("Connection not found: %s", connection_id)

            return False

        info = self._connection_info[connection_id]

        # Check subscription limit
        if len(info.subscriptions) >= self._max_subscriptions:
            logger.warning("Max subscriptions reached for %s", connection_id)

            return False

        # Add to channel
        if channel not in self._channels:
            self._channels[channel] = set()
            self._stats["active_channels"] += 1

        self._channels[channel].add(connection_id)
        info.subscriptions.add(channel)

        # Send confirmation
        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                event="subscribed",
                channel=channel,
                data={"status": "success", "channel": channel},
            ),
        )

        logger.debug("Subscribed %s to %s", connection_id, channel)

        return True

    async def unsubscribe(self, connection_id: str, channel: str) -> bool:
        """
        Unsubscribe a connection from a channel.

        Args:
            connection_id: Connection ID
            channel: Channel name

        Returns:
            True if unsubscribed successfully
        """
        if not self._unsubscribe_internal(connection_id, channel):
            return False

        # Send confirmation
        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                event="unsubscribed",
                channel=channel,
                data={"status": "success", "channel": channel},
            ),
        )

        return True

    def _unsubscribe_internal(self, connection_id: str, channel: str) -> bool:
        """Internal unsubscribe without sending confirmation."""
        if channel not in self._channels:
            return False

        if connection_id not in self._channels[channel]:
            return False

        self._channels[channel].discard(connection_id)

        # Remove empty channels
        if not self._channels[channel]:
            del self._channels[channel]
            self._stats["active_channels"] -= 1

        # Update connection info
        if connection_id in self._connection_info:
            self._connection_info[connection_id].subscriptions.discard(channel)

        logger.debug("Unsubscribed %s from %s", connection_id, channel)

        return True

    def get_channel_subscribers(self, channel: str) -> set[str]:
        """Get all subscribers for a channel."""
        return self._channels.get(channel, set()).copy()

    def get_available_channels(self) -> list[str]:
        """Get list of all active channels."""
        return list(self._channels.keys())

    # ================================================================
    # MESSAGE BROADCASTING
    # ================================================================

    async def broadcast(
        self,
        channel: str,
        data: dict[str, Any],
        event: str = "update",
        exclude: set[str] | None = None,
    ):
        """
        Broadcast a message to all subscribers of a channel.

        Args:
            channel: Channel to broadcast to
            data: Data to send
            event: Event type
            exclude: Connection IDs to exclude
        """
        if channel not in self._channels:
            return

        exclude = exclude or set()
        self._sequence += 1

        message = WebSocketMessage(
            event=event,
            channel=channel,
            data=data,
            sequence=self._sequence,
        )

        # Send to all subscribers
        for conn_id in self._channels[channel]:
            if conn_id in exclude:
                continue
            await self._send_to_connection(conn_id, message)

    async def broadcast_to_all(self, data: dict[str, Any], event: str = "broadcast"):
        """
        Broadcast a message to all connected clients.

        Args:
            data: Data to send
            event: Event type
        """
        self._sequence += 1

        message = WebSocketMessage(
            event=event,
            channel="global",
            data=data,
            sequence=self._sequence,
        )

        for conn_id in self._connections:
            await self._send_to_connection(conn_id, message)

    async def send_to_user(
        self,
        user_id: str,
        data: dict[str, Any],
        event: str = "message",
    ):
        """
        Send a message to all connections for a specific user.

        Args:
            user_id: User ID
            data: Data to send
            event: Event type
        """
        self._sequence += 1

        message = WebSocketMessage(
            event=event,
            channel=f"user:{user_id}",
            data=data,
            sequence=self._sequence,
        )

        for conn_id, info in self._connection_info.items():
            if info.user_id == user_id:
                await self._send_to_connection(conn_id, message)

    async def _send_to_connection(self, connection_id: str, message: WebSocketMessage):
        """Send a message to a specific connection."""
        if connection_id not in self._connections:
            return

        websocket = self._connections[connection_id]

        try:
            # Handle different WebSocket implementations
            if hasattr(websocket, "send_text"):
                # FastAPI/Starlette WebSocket
                await websocket.send_text(message.to_json())
            elif hasattr(websocket, "send"):
                # Generic async send
                await websocket.send(message.to_json())
            elif hasattr(websocket, "write_message"):
                # Tornado WebSocket
                websocket.write_message(message.to_json())
            else:
                logger.error("Unknown WebSocket type for %s", connection_id)

                return

            # Update stats
            self._stats["total_messages_sent"] += 1
            if connection_id in self._connection_info:
                self._connection_info[connection_id].messages_sent += 1

        except Exception as e:
            logger.error("Error sending to %s: %s", connection_id, e)

            # Connection may be dead, unregister it
            self.unregister_connection(connection_id)

    # ================================================================
    # MESSAGE HANDLING
    # ================================================================

    async def _handle_subscribe(self, connection_id: str, data: dict) -> dict | None:
        channel = data.get("channel")
        if channel:
            await self.subscribe(connection_id, channel)
            return {"status": "subscribed", "channel": channel}
        return None

    async def _handle_unsubscribe(self, connection_id: str, data: dict) -> dict | None:
        channel = data.get("channel")
        if channel:
            await self.unsubscribe(connection_id, channel)
            return {"status": "unsubscribed", "channel": channel}
        return None

    async def _handle_ping(self, connection_id: str, data: dict) -> dict:
        if connection_id in self._connection_info:
            self._connection_info[connection_id].last_heartbeat = datetime.now(UTC)
        return {"action": "pong", "timestamp": datetime.now(UTC).isoformat()}

    async def handle_message(self, connection_id: str, message: str) -> dict | None:
        """
        Handle an incoming WebSocket message.

        Args:
            connection_id: Connection ID
            message: Raw message string

        Returns:
            Response data or None
        """
        if connection_id not in self._connections:
            return None

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from %s", connection_id)

            return {"error": "Invalid JSON"}

        self._stats["total_messages_received"] += 1
        if connection_id in self._connection_info:
            self._connection_info[connection_id].messages_received += 1

        action = data.get("action")
        dispatch = {
            "subscribe": self._handle_subscribe,
            "unsubscribe": self._handle_unsubscribe,
            "ping": self._handle_ping,
        }

        if action in dispatch:
            return await dispatch[action](connection_id, data)

        if action == "auth":
            return await self._handle_auth(connection_id, data.get("token"))

        for callback in self._on_message_callbacks:
            try:
                callback(connection_id, data)
            except Exception as e:
                logger.error("Error in message callback: %s", e)

        return None

    async def _handle_auth(self, connection_id: str, token: str | None) -> dict:
        """Validate JWT bearer token and mark connection authenticated.

        Any JWT decode failure (wrong secret, expired, malformed) is a hard
        rejection — the connection is NOT authenticated.
        """
        if not token:
            return {"error": "Token required"}

        try:
            from api.auth import _decode_token

            payload = _decode_token(token)
            user_id = payload.sub
        except Exception as exc:
            logger.warning(
                "WebSocket auth rejected for connection %s: %s",
                connection_id,
                exc,
            )
            return {"error": "Invalid or expired token"}

        if connection_id in self._connection_info:
            self._connection_info[connection_id].authenticated = True
            self._connection_info[connection_id].user_id = user_id
        return {"status": "authenticated", "user_id": user_id}

    # ================================================================
    # HEARTBEAT & MAINTENANCE
    # ================================================================

    async def heartbeat_loop(self):
        """
        Run heartbeat loop to check connection health.
        Should be run as a background task.
        """
        while True:
            await asyncio.sleep(self._heartbeat_interval)

            now = datetime.now(UTC)
            timeout = self._heartbeat_interval * 2

            dead_connections = []

            for conn_id, info in self._connection_info.items():
                elapsed = (now - info.last_heartbeat).total_seconds()
                if elapsed > timeout:
                    dead_connections.append(conn_id)
                    logger.warning("Connection timeout: %s", conn_id)

            # Clean up dead connections
            for conn_id in dead_connections:
                self.unregister_connection(conn_id)

            # Send ping to all active connections
            await self.broadcast_to_all(
                {"type": "heartbeat", "timestamp": now.isoformat()},
                event="ping",
            )

    # ================================================================
    # SPECIALIZED BROADCASTS
    # ================================================================

    async def broadcast_price_update(
        self,
        symbol: str,
        price: float,
        bid: float,
        ask: float,
        timestamp: datetime | None = None,
    ):
        """Broadcast price update for a symbol."""
        channel = f"prices:{symbol}"
        await self.broadcast(
            channel,
            {
                "symbol": symbol,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread": round(ask - bid, 5),
                "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
            },
            event="price",
        )

    async def broadcast_orderbook_update(
        self,
        symbol: str,
        bids: list[dict],
        asks: list[dict],
        timestamp: datetime | None = None,
    ):
        """Broadcast order book update for a symbol."""
        channel = f"orderbook:{symbol}"
        await self.broadcast(
            channel,
            {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
            },
            event="orderbook",
        )

    async def broadcast_trade(
        self,
        symbol: str,
        price: float,
        quantity: float,
        side: str,
        trade_id: str | None = None,
    ):
        """Broadcast trade execution."""
        channel = f"trades:{symbol}"
        await self.broadcast(
            channel,
            {
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "side": side,
                "trade_id": trade_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            event="trade",
        )

    async def broadcast_signal(self, symbol: str, signal_data: dict[str, Any]):
        """Broadcast trading signal."""
        # Broadcast to symbol-specific channel
        await self.broadcast(f"signals:{symbol}", signal_data, event="signal")
        # Also broadcast to all-signals channel
        await self.broadcast("signals:all", signal_data, event="signal")

    async def broadcast_alert(self, user_id: str | None, alert_data: dict[str, Any]):
        """Broadcast alert notification."""
        if user_id:
            # Send to specific user
            await self.send_to_user(user_id, alert_data, event="alert")
        else:
            # Broadcast to all on alerts channel
            await self.broadcast("alerts", alert_data, event="alert")

    # ================================================================
    # EVENT CALLBACKS
    # ================================================================

    def on_connect(self, callback: Callable):
        """Register callback for new connections."""
        self._on_connect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable):
        """Register callback for disconnections."""
        self._on_disconnect_callbacks.append(callback)

    def on_message(self, callback: Callable):
        """Register callback for incoming messages."""
        self._on_message_callbacks.append(callback)

    # ================================================================
    # STATISTICS
    # ================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get WebSocket server statistics."""
        return {
            **self._stats,
            "active_connections": len(self._connections),
            "active_channels": len(self._channels),
            "channels": {channel: len(subscribers) for channel, subscribers in self._channels.items()},
        }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def create_websocket_router(manager: WebSocketManager):
    """
    Create FastAPI router with WebSocket endpoints.

    Args:
        manager: WebSocketManager instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect

    router = APIRouter(tags=["WebSocket"])

    # JWT auth timeout for the legacy /ws endpoint (seconds)
    _WS_AUTH_TIMEOUT: float = float(os.getenv("WS_AUTH_TIMEOUT", "10"))
    _WS_AUTH_REQUIRED: bool = os.getenv("WS_AUTH_REQUIRED", "true").lower() == "true"

    def _ws_validate_token(token: str) -> dict | None:
        """Validate a Bearer JWT for the legacy /ws endpoint.

        Returns the decoded payload dict on success, None on failure.
        """
        token = token.removeprefix("Bearer ").strip()
        try:
            from auth.jwt import decode_access_token  # type: ignore[import]

            return decode_access_token(token)
        except Exception as exc:
            logger.debug("/ws JWT validation failed: %s", exc)
            return None

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """Legacy WebSocket endpoint with JWT authentication.

        .. deprecated::
            New clients should connect to ``/ws/live`` (api/ws_live.py) which
            provides JWT authentication, rate-limiting, and heartbeat support.

            Migration path: replace ``ws://<host>/ws`` with ``wss://<host>/ws/live``
            and include the ``Authorization: Bearer <token>`` header or send an
            ``{"type":"auth","token":"..."}`` message within 10 seconds of connecting.

        Authentication flow
        -------------------
        1. Server sends ``{"type": "auth_required"}``.
        2. Client sends ``{"type": "auth", "token": "Bearer <jwt>"}`` within
           ``WS_AUTH_TIMEOUT`` seconds (default 10).
        3. On success: server sends ``{"type": "auth_ok"}`` and admits the connection.
        4. On failure or timeout: server sends ``{"type": "auth_failed"}`` and
           closes with code 4001.

        Set ``WS_AUTH_REQUIRED=false`` to bypass auth in dev/demo environments.
        """
        import asyncio as _asyncio

        from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

        limiter = get_ws_limiter()
        client_ip = get_client_ip(websocket)

        logger.warning(
            "DEPRECATED: client %s connected to legacy /ws endpoint. "
            "Migrate to /ws/live which provides JWT auth and heartbeat support.",
            client_ip,
        )

        allowed, reason = await limiter.check_and_register(websocket, client_ip)
        if not allowed:
            return

        await websocket.accept()

        # ── JWT authentication handshake ──────────────────────────────────────
        user_id: str = "anonymous"

        if _WS_AUTH_REQUIRED:
            try:
                await websocket.send_text(json.dumps({"type": "auth_required"}))
            except Exception:
                await limiter.release(client_ip)
                return

            try:
                raw = await _asyncio.wait_for(websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT)
            except TimeoutError:
                logger.warning("/ws auth timeout for %s — closing", client_ip)
                try:
                    await websocket.send_text(json.dumps({"type": "auth_failed", "reason": "auth_timeout"}))
                    await websocket.close(code=4001)
                except Exception as _exc:
                    logger.debug("/ws auth_timeout teardown error (socket already closed): %s", _exc)
                await limiter.release(client_ip)
                return

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                msg = {}

            token = msg.get("token", "") if msg.get("type") == "auth" else ""
            payload = _ws_validate_token(token) if token else None

            if payload is None:
                logger.warning("/ws auth failed for %s — invalid token", client_ip)
                try:
                    await websocket.send_text(json.dumps({"type": "auth_failed", "reason": "invalid_token"}))
                    await websocket.close(code=4001)
                except Exception as _exc:
                    logger.debug("/ws invalid_token teardown error (socket already closed): %s", _exc)
                await limiter.release(client_ip)
                return

            user_id = str(payload.get("sub", payload.get("user_id", "unknown")))
            try:
                await websocket.send_text(json.dumps({"type": "auth_ok", "user_id": user_id}))
            except Exception:
                await limiter.release(client_ip)
                return

            logger.info("/ws authenticated user=%s ip=%s", user_id, client_ip)
        else:
            logger.debug("/ws auth bypassed (WS_AUTH_REQUIRED=false) ip=%s", client_ip)

        # ── Admit to connection pool ──────────────────────────────────────────
        connection_id = manager.register_connection(websocket)

        try:
            # Send welcome message
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "connected",
                        "connection_id": connection_id,
                        "user_id": user_id,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                ),
            )

            # Handle messages
            while True:
                message = await websocket.receive_text()
                response = await manager.handle_message(connection_id, message)

                if response:
                    await websocket.send_text(json.dumps(response))

        except WebSocketDisconnect:
            manager.unregister_connection(connection_id)
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            manager.unregister_connection(connection_id)
        finally:
            await limiter.release(client_ip)

    @router.get("/ws/stats")
    async def websocket_stats():
        """Get WebSocket server statistics."""
        return manager.get_stats()

    @router.get("/ws/channels")
    async def websocket_channels():
        """Get available channels."""
        return {"channels": manager.get_available_channels()}

    return router


# Global instance for easy access
_ws_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
