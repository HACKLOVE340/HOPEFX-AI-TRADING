from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from hopefx.config.settings import settings
from hopefx.events.bus import event_bus
from hopefx.events.schemas import Event, EventType

logger = structlog.get_logger()


class ConnectionManager:
    """WebSocket connection manager with broadcasting."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info("ws.client_connected", total=len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info("ws.client_disconnected", total=len(self.active_connections))

    async def broadcast(self, message: dict) -> None:
        """Broadcast to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up dead connections
        for conn in disconnected:
            await self.disconnect(conn)


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)

    # Subscribe to events
    async def event_handler(event: Event) -> None:
        await manager.broadcast({
            "type": event.type.value,
            "timestamp": event.timestamp.isoformat(),
            "data": event.payload.model_dump() if hasattr(event.payload, "model_dump") else event.payload,
        })

    # Subscribe to relevant events
    unsub_tick = event_bus.subscribe(EventType.TICK, event_handler)
    unsub_fill = event_bus.subscribe(EventType.ORDER_FILL, event_handler)
    unsub_pred = event_bus.subscribe(EventType.PREDICTION, event_handler)

    try:
        while True:
            # Heartbeat/ping-pong
            data = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=settings.ws_heartbeat_interval,
            )
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg.get("type") == "subscribe":
                # Handle subscription requests
                pass

    except WebSocketDisconnect:
        logger.info("ws.disconnected")
    except asyncio.TimeoutError:
        logger.warning("ws.heartbeat_timeout")
    finally:
        unsub_tick()
        unsub_fill()
        unsub_pred()
        await manager.disconnect(websocket)
