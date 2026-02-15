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
from datetime import datetime
from typing import Dict, Set, Optional, Any, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import weakref

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
    data: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sequence: int = 0

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection."""
    connection_id: str
    connected_at: datetime
    subscriptions: Set[str] = field(default_factory=set)
    user_id: Optional[str] = None
    authenticated: bool = False
    messages_sent: int = 0
    messages_received: int = 0
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)


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

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize WebSocket manager.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Connection storage (using weak references to allow GC)
        self._connections: Dict[str, Any] = {}
        self._connection_info: Dict[str, ConnectionInfo] = {}

        # Channel subscriptions: channel -> set of connection_ids
        self._channels: Dict[str, Set[str]] = {}

        # Message sequence counter
        self._sequence = 0

        # Configuration
        self._heartbeat_interval = self.config.get('heartbeat_interval', 30)
        self._max_subscriptions = self.config.get('max_subscriptions', 100)
        self._rate_limit = self.config.get('rate_limit', 100)  # msgs per second

        # Event callbacks
        self._on_connect_callbacks: List[Callable] = []
        self._on_disconnect_callbacks: List[Callable] = []
        self._on_message_callbacks: List[Callable] = []

        # Statistics
        self._stats = {
            'total_connections': 0,
            'total_messages_sent': 0,
            'total_messages_received': 0,
            'active_channels': 0,
        }

        logger.info("WebSocket Manager initialized")

    # ================================================================
    # CONNECTION MANAGEMENT
    # ================================================================

    def register_connection(
        self,
        websocket: Any,
        connection_id: Optional[str] = None,
        user_id: Optional[str] = None
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
            connection_id = f"ws_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        self._connections[connection_id] = websocket
        self._connection_info[connection_id] = ConnectionInfo(
            connection_id=connection_id,
            connected_at=datetime.utcnow(),
            user_id=user_id,
            authenticated=user_id is not None
        )

        self._stats['total_connections'] += 1

        # Notify callbacks
        for callback in self._on_connect_callbacks:
            try:
                callback(connection_id, self._connection_info[connection_id])
            except Exception as e:
                logger.error(f"Error in connect callback: {e}")

        logger.info(f"WebSocket registered: {connection_id}")
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
                logger.error(f"Error in disconnect callback: {e}")

        logger.info(f"WebSocket unregistered: {connection_id}")

    def get_connection_info(self, connection_id: str) -> Optional[ConnectionInfo]:
        """Get information about a connection."""
        return self._connection_info.get(connection_id)

    def get_active_connections(self) -> List[str]:
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
            logger.warning(f"Connection not found: {connection_id}")
            return False

        info = self._connection_info[connection_id]

        # Check subscription limit
        if len(info.subscriptions) >= self._max_subscriptions:
            logger.warning(f"Max subscriptions reached for {connection_id}")
            return False

        # Add to channel
        if channel not in self._channels:
            self._channels[channel] = set()
            self._stats['active_channels'] += 1

        self._channels[channel].add(connection_id)
        info.subscriptions.add(channel)

        # Send confirmation
        await self._send_to_connection(connection_id, WebSocketMessage(
            event='subscribed',
            channel=channel,
            data={'status': 'success', 'channel': channel}
        ))

        logger.debug(f"Subscribed {connection_id} to {channel}")
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
        await self._send_to_connection(connection_id, WebSocketMessage(
            event='unsubscribed',
            channel=channel,
            data={'status': 'success', 'channel': channel}
        ))

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
            self._stats['active_channels'] -= 1

        # Update connection info
        if connection_id in self._connection_info:
            self._connection_info[connection_id].subscriptions.discard(channel)

        logger.debug(f"Unsubscribed {connection_id} from {channel}")
        return True

    def get_channel_subscribers(self, channel: str) -> Set[str]:
        """Get all subscribers for a channel."""
        return self._channels.get(channel, set()).copy()

    def get_available_channels(self) -> List[str]:
        """Get list of all active channels."""
        return list(self._channels.keys())

    # ================================================================
    # MESSAGE BROADCASTING
    # ================================================================

    async def broadcast(
        self,
        channel: str,
        data: Dict[str, Any],
        event: str = "update",
        exclude: Optional[Set[str]] = None
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
            sequence=self._sequence
        )

        # Send to all subscribers
        for conn_id in self._channels[channel]:
            if conn_id in exclude:
                continue
            await self._send_to_connection(conn_id, message)

    async def broadcast_to_all(
        self,
        data: Dict[str, Any],
        event: str = "broadcast"
    ):
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
            sequence=self._sequence
        )

        for conn_id in self._connections:
            await self._send_to_connection(conn_id, message)

    async def send_to_user(
        self,
        user_id: str,
        data: Dict[str, Any],
        event: str = "message"
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
            sequence=self._sequence
        )

        for conn_id, info in self._connection_info.items():
            if info.user_id == user_id:
                await self._send_to_connection(conn_id, message)

    async def _send_to_connection(
        self,
        connection_id: str,
        message: WebSocketMessage
    ):
        """Send a message to a specific connection."""
        if connection_id not in self._connections:
            return

        websocket = self._connections[connection_id]

        try:
            # Handle different WebSocket implementations
            if hasattr(websocket, 'send_text'):
                # FastAPI/Starlette WebSocket
                await websocket.send_text(message.to_json())
            elif hasattr(websocket, 'send'):
                # Generic async send
                await websocket.send(message.to_json())
            elif hasattr(websocket, 'write_message'):
                # Tornado WebSocket
                websocket.write_message(message.to_json())
            else:
                logger.error(f"Unknown WebSocket type for {connection_id}")
                return

            # Update stats
            self._stats['total_messages_sent'] += 1
            if connection_id in self._connection_info:
                self._connection_info[connection_id].messages_sent += 1

        except Exception as e:
            logger.error(f"Error sending to {connection_id}: {e}")
            # Connection may be dead, unregister it
            self.unregister_connection(connection_id)

    # ================================================================
    # MESSAGE HANDLING
    # ================================================================

    async def handle_message(
        self,
        connection_id: str,
        message: str
    ) -> Optional[Dict]:
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
            logger.warning(f"Invalid JSON from {connection_id}")
            return {'error': 'Invalid JSON'}

        # Update stats
        self._stats['total_messages_received'] += 1
        if connection_id in self._connection_info:
            self._connection_info[connection_id].messages_received += 1

        # Handle different message types
        action = data.get('action')

        if action == 'subscribe':
            channel = data.get('channel')
            if channel:
                await self.subscribe(connection_id, channel)
                return {'status': 'subscribed', 'channel': channel}

        elif action == 'unsubscribe':
            channel = data.get('channel')
            if channel:
                await self.unsubscribe(connection_id, channel)
                return {'status': 'unsubscribed', 'channel': channel}

        elif action == 'ping':
            # Heartbeat response
            if connection_id in self._connection_info:
                self._connection_info[connection_id].last_heartbeat = datetime.utcnow()
            return {'action': 'pong', 'timestamp': datetime.utcnow().isoformat()}

        elif action == 'auth':
            # Handle authentication
            token = data.get('token')
            return await self._handle_auth(connection_id, token)

        # Notify callbacks
        for callback in self._on_message_callbacks:
            try:
                callback(connection_id, data)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")

        return None

    async def _handle_auth(
        self,
        connection_id: str,
        token: Optional[str]
    ) -> Dict:
        """Handle authentication request."""
        if not token:
            return {'error': 'Token required'}

        # TODO: Implement actual token validation
        # For now, accept any non-empty token
        if connection_id in self._connection_info:
            self._connection_info[connection_id].authenticated = True
            # Extract user_id from token (mock)
            self._connection_info[connection_id].user_id = f"user_{token[:8]}"

        return {'status': 'authenticated'}

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

            now = datetime.utcnow()
            timeout = self._heartbeat_interval * 2

            dead_connections = []

            for conn_id, info in self._connection_info.items():
                elapsed = (now - info.last_heartbeat).total_seconds()
                if elapsed > timeout:
                    dead_connections.append(conn_id)
                    logger.warning(f"Connection timeout: {conn_id}")

            # Clean up dead connections
            for conn_id in dead_connections:
                self.unregister_connection(conn_id)

            # Send ping to all active connections
            await self.broadcast_to_all(
                {'type': 'heartbeat', 'timestamp': now.isoformat()},
                event='ping'
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
        timestamp: Optional[datetime] = None
    ):
        """Broadcast price update for a symbol."""
        channel = f"prices:{symbol}"
        await self.broadcast(channel, {
            'symbol': symbol,
            'price': price,
            'bid': bid,
            'ask': ask,
            'spread': round(ask - bid, 5),
            'timestamp': (timestamp or datetime.utcnow()).isoformat()
        }, event='price')

    async def broadcast_orderbook_update(
        self,
        symbol: str,
        bids: List[Dict],
        asks: List[Dict],
        timestamp: Optional[datetime] = None
    ):
        """Broadcast order book update for a symbol."""
        channel = f"orderbook:{symbol}"
        await self.broadcast(channel, {
            'symbol': symbol,
            'bids': bids,
            'asks': asks,
            'timestamp': (timestamp or datetime.utcnow()).isoformat()
        }, event='orderbook')

    async def broadcast_trade(
        self,
        symbol: str,
        price: float,
        quantity: float,
        side: str,
        trade_id: Optional[str] = None
    ):
        """Broadcast trade execution."""
        channel = f"trades:{symbol}"
        await self.broadcast(channel, {
            'symbol': symbol,
            'price': price,
            'quantity': quantity,
            'side': side,
            'trade_id': trade_id,
            'timestamp': datetime.utcnow().isoformat()
        }, event='trade')

    async def broadcast_signal(
        self,
        symbol: str,
        signal_data: Dict[str, Any]
    ):
        """Broadcast trading signal."""
        # Broadcast to symbol-specific channel
        await self.broadcast(f"signals:{symbol}", signal_data, event='signal')
        # Also broadcast to all-signals channel
        await self.broadcast("signals:all", signal_data, event='signal')

    async def broadcast_alert(
        self,
        user_id: Optional[str],
        alert_data: Dict[str, Any]
    ):
        """Broadcast alert notification."""
        if user_id:
            # Send to specific user
            await self.send_to_user(user_id, alert_data, event='alert')
        else:
            # Broadcast to all on alerts channel
            await self.broadcast("alerts", alert_data, event='alert')

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

    def get_stats(self) -> Dict[str, Any]:
        """Get WebSocket server statistics."""
        return {
            **self._stats,
            'active_connections': len(self._connections),
            'active_channels': len(self._channels),
            'channels': {
                channel: len(subscribers)
                for channel, subscribers in self._channels.items()
            }
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

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """Main WebSocket endpoint."""
        await websocket.accept()

        connection_id = manager.register_connection(websocket)

        try:
            # Send welcome message
            await websocket.send_text(json.dumps({
                'event': 'connected',
                'connection_id': connection_id,
                'timestamp': datetime.utcnow().isoformat()
            }))

            # Handle messages
            while True:
                message = await websocket.receive_text()
                response = await manager.handle_message(connection_id, message)

                if response:
                    await websocket.send_text(json.dumps(response))

        except WebSocketDisconnect:
            manager.unregister_connection(connection_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            manager.unregister_connection(connection_id)

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
_ws_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
