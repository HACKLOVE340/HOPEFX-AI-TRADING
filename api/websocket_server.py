# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/websocket_server.py — DEPRECATED
=====================================
This module is superseded by ``api/ws_live.py`` (``LiveConnectionManager``),
which is the canonical FastAPI WebSocket implementation used in production.

This file is retained only for backward compatibility with existing tests and
any external code that imports from it.  Do not add new features here.

Migration guide
---------------
- Replace ``from api.websocket_server import WebSocketManager`` with
  ``from api.ws_live import get_live_manager`` (returns ``LiveConnectionManager``).
- Replace ``WebSocketMessage`` usage with plain ``dict`` payloads — the live
  manager serialises dicts directly via ``json.dumps``.
- ``create_websocket_router`` is replaced by the ``router`` in ``api/ws_live.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc

logger = logging.getLogger(__name__)

warnings.warn(
    "api.websocket_server is deprecated and will be removed in a future release. "
    "Use api.ws_live.get_live_manager() instead.",
    DeprecationWarning,
    stacklevel=2,
)


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
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sequence: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class ConnectionInfo:
    """Metadata for a single WebSocket connection."""

    connection_id: str
    user_id: str | None
    subscriptions: set[str] = field(default_factory=set)
    connected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_ping: str | None = None
    message_count: int = 0
    authenticated: bool = False


class WebSocketManager:
    """
    Legacy WebSocket manager — kept for test compatibility only.

    In production the application uses ``LiveConnectionManager`` from
    ``api/ws_live.py``.  This class mirrors the original interface so
    existing unit tests continue to pass without modification.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._connections: dict[str, Any] = {}
        self._connection_info: dict[str, ConnectionInfo] = {}
        self._subscriptions: dict[str, set[str]] = {}
        self._channel_subscribers: dict[str, set[str]] = {}
        self._callbacks: dict[str, list[Callable]] = {
            "connect": [],
            "disconnect": [],
            "message": [],
        }
        self._counter = 0
        self._max_subscriptions: int = int(self._config.get("max_subscriptions", 50))

        # Pre-populate default channels
        for ch in ChannelType:
            self._channel_subscribers[ch.value] = set()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def _new_id(self) -> str:
        self._counter += 1
        return f"conn_{self._counter}"

    def register_connection(
        self,
        websocket: Any,
        user_id: str | None = None,
        connection_id: str | None = None,
    ) -> str:
        cid = connection_id or self._new_id()
        self._connections[cid] = websocket
        self._subscriptions[cid] = set()
        self._connection_info[cid] = ConnectionInfo(
            connection_id=cid,
            user_id=user_id,
            authenticated=user_id is not None,
        )
        for cb in self._callbacks["connect"]:
            try:
                cb(cid, user_id)
            except Exception:  # nosec B110
                pass
        return cid

    def unregister_connection(self, connection_id: str) -> None:
        info = self._connection_info.get(connection_id)
        for subs in self._channel_subscribers.values():
            subs.discard(connection_id)
        self._connections.pop(connection_id, None)
        self._subscriptions.pop(connection_id, None)
        self._connection_info.pop(connection_id, None)
        for cb in self._callbacks["disconnect"]:
            try:
                cb(connection_id, info.user_id if info else None)
            except Exception:  # nosec B110
                pass

    def get_connection_info(self, connection_id: str) -> ConnectionInfo | None:
        return self._connection_info.get(connection_id)

    def get_active_connections(self) -> list[str]:
        return list(self._connections.keys())

    # ── Subscriptions ─────────────────────────────────────────────────────────

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        if connection_id not in self._connections:
            return False
        subs = self._subscriptions.get(connection_id, set())
        if len(subs) >= self._max_subscriptions:
            return False
        subs.add(channel)
        self._subscriptions[connection_id] = subs
        self._channel_subscribers.setdefault(channel, set()).add(connection_id)
        info = self._connection_info.get(connection_id)
        if info:
            info.subscriptions.add(channel)
        return True

    async def unsubscribe(self, connection_id: str, channel: str) -> bool:
        if connection_id not in self._connections:
            return False
        self._subscriptions.get(connection_id, set()).discard(channel)
        self._channel_subscribers.get(channel, set()).discard(connection_id)
        info = self._connection_info.get(connection_id)
        if info:
            info.subscriptions.discard(channel)
        return True

    def _unsubscribe_internal(self, connection_id: str, channel: str) -> bool:
        self._subscriptions.get(connection_id, set()).discard(channel)
        self._channel_subscribers.get(channel, set()).discard(connection_id)
        return True

    def get_channel_subscribers(self, channel: str) -> set[str]:
        return set(self._channel_subscribers.get(channel, set()))

    def get_available_channels(self) -> list[str]:
        return list(self._channel_subscribers.keys())

    # ── Messaging ─────────────────────────────────────────────────────────────

    async def broadcast(
        self,
        channel: str,
        data: dict[str, Any],
        event: str = "update",
        exclude: set[str] | None = None,
    ) -> int:
        msg = WebSocketMessage(event=event, channel=channel, data=data)
        payload = msg.to_json()
        sent = 0
        exclude = exclude or set()
        for cid in list(self._channel_subscribers.get(channel, set())):
            if cid in exclude:
                continue
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                send = getattr(ws, "send_text", None) or getattr(ws, "send", None)
                if send:
                    result = send(payload)
                    if asyncio.iscoroutine(result):
                        await result
                    sent += 1
            except Exception as exc:
                logger.debug("WebSocketManager.broadcast: send failed for %s: %s", cid, exc)
        return sent

    async def broadcast_to_all(self, data: dict[str, Any], event: str = "broadcast") -> int:
        msg = WebSocketMessage(event=event, channel="*", data=data)
        payload = msg.to_json()
        sent = 0
        for cid, ws in list(self._connections.items()):
            try:
                send = getattr(ws, "send_text", None) or getattr(ws, "send", None)
                if send:
                    result = send(payload)
                    if asyncio.iscoroutine(result):
                        await result
                    sent += 1
            except Exception as exc:
                logger.debug("WebSocketManager.broadcast_to_all: %s: %s", cid, exc)
        return sent

    async def send_to_user(
        self,
        user_id: str,
        channel: str,
        data: dict[str, Any],
        event: str = "update",
    ) -> bool:
        msg = WebSocketMessage(event=event, channel=channel, data=data)
        payload = msg.to_json()
        sent = False
        for cid, info in list(self._connection_info.items()):
            if info.user_id != user_id:
                continue
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                send = getattr(ws, "send_text", None) or getattr(ws, "send", None)
                if send:
                    result = send(payload)
                    if asyncio.iscoroutine(result):
                        await result
                    sent = True
            except Exception as exc:
                logger.debug("WebSocketManager.send_to_user: %s: %s", cid, exc)
        return sent

    async def _send_to_connection(self, connection_id: str, message: WebSocketMessage) -> None:
        ws = self._connections.get(connection_id)
        if ws is None:
            return
        payload = message.to_json()
        send = getattr(ws, "send_text", None) or getattr(ws, "send", None)
        if send:
            result = send(payload)
            if asyncio.iscoroutine(result):
                await result
        info = self._connection_info.get(connection_id)
        if info:
            info.message_count += 1

    # ── Message handling ──────────────────────────────────────────────────────

    async def _handle_subscribe(self, connection_id: str, data: dict) -> dict | None:
        channel = data.get("channel", "")
        ok = await self.subscribe(connection_id, channel)
        return {"status": "subscribed" if ok else "error", "channel": channel}

    async def _handle_unsubscribe(self, connection_id: str, data: dict) -> dict | None:
        channel = data.get("channel", "")
        await self.unsubscribe(connection_id, channel)
        return {"status": "unsubscribed", "channel": channel}

    async def _handle_ping(self, connection_id: str, data: dict) -> dict:
        info = self._connection_info.get(connection_id)
        if info:
            info.last_ping = datetime.now(UTC).isoformat()
        return {"type": "pong", "timestamp": datetime.now(UTC).isoformat()}

    async def handle_message(self, connection_id: str, message: str) -> dict | None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return {"error": "invalid_json"}

        msg_type = data.get("type", "")
        info = self._connection_info.get(connection_id)
        if info:
            info.message_count += 1

        for cb in self._callbacks["message"]:
            try:
                cb(connection_id, data)
            except Exception:  # nosec B110
                pass

        if msg_type == "subscribe":
            return await self._handle_subscribe(connection_id, data)
        if msg_type == "unsubscribe":
            return await self._handle_unsubscribe(connection_id, data)
        if msg_type == "ping":
            return await self._handle_ping(connection_id, data)
        if msg_type == "auth":
            return await self._handle_auth(connection_id, data.get("token"))
        return None

    async def _handle_auth(self, connection_id: str, token: str | None) -> dict:
        if not token:
            return {"type": "auth_failed", "reason": "no_token"}
        try:
            from auth.jwt import decode_access_token  # type: ignore[import]

            payload = decode_access_token(token.removeprefix("Bearer ").strip())
            user_id = str(payload.get("sub", ""))
            info = self._connection_info.get(connection_id)
            if info:
                info.user_id = user_id
                info.authenticated = True
            return {"type": "auth_ok", "user_id": user_id}
        except Exception as exc:
            logger.debug("WebSocketManager auth failed: %s", exc)
            return {"type": "auth_failed", "reason": "invalid_token"}

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def heartbeat_loop(self) -> None:
        interval = float(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
        while True:
            await asyncio.sleep(interval)
            await self.broadcast_to_all(
                {"timestamp": datetime.now(UTC).isoformat()},
                event="heartbeat",
            )

    # ── Convenience broadcast helpers ─────────────────────────────────────────

    async def broadcast_price_update(self, symbol: str, price_data: dict[str, Any]) -> int:
        return await self.broadcast(
            ChannelType.PRICES.value,
            {"symbol": symbol, **price_data},
            event="price_update",
        )

    async def broadcast_orderbook_update(self, symbol: str, orderbook_data: dict[str, Any]) -> int:
        return await self.broadcast(
            ChannelType.ORDERBOOK.value,
            {"symbol": symbol, **orderbook_data},
            event="orderbook_update",
        )

    async def broadcast_trade(self, trade_data: dict[str, Any], user_id: str | None = None) -> bool | int:
        if user_id:
            return await self.send_to_user(user_id, ChannelType.TRADES.value, trade_data, event="trade")
        return await self.broadcast(ChannelType.TRADES.value, trade_data, event="trade")

    async def broadcast_signal(self, symbol: str, signal_data: dict[str, Any]) -> int:
        return await self.broadcast(
            ChannelType.SIGNALS.value,
            {"symbol": symbol, **signal_data},
            event="signal",
        )

    async def broadcast_alert(self, user_id: str | None, alert_data: dict[str, Any]) -> bool | int:
        if user_id:
            return await self.send_to_user(user_id, ChannelType.ALERTS.value, alert_data, event="alert")
        return await self.broadcast(ChannelType.ALERTS.value, alert_data, event="alert")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_connect(self, callback: Callable) -> None:
        self._callbacks["connect"].append(callback)

    def on_disconnect(self, callback: Callable) -> None:
        self._callbacks["disconnect"].append(callback)

    def on_message(self, callback: Callable) -> None:
        self._callbacks["message"].append(callback)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        total_msgs = sum(i.message_count for i in self._connection_info.values())
        return {
            "active_connections": len(self._connections),
            "total_messages": total_msgs,
            "channels": {ch: len(subs) for ch, subs in self._channel_subscribers.items()},
            "authenticated": sum(1 for i in self._connection_info.values() if i.authenticated),
        }


def create_websocket_router(manager: WebSocketManager):  # type: ignore[return]
    """Deprecated — use the ``router`` from ``api/ws_live.py`` instead."""
    try:
        from fastapi import APIRouter, WebSocket

        router = APIRouter()

        @router.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            cid = manager.register_connection(websocket)
            try:
                while True:
                    text = await websocket.receive_text()
                    response = await manager.handle_message(cid, text)
                    if response:
                        await websocket.send_text(json.dumps(response))
            except Exception:  # nosec B110
                pass
            finally:
                manager.unregister_connection(cid)

        return router
    except ImportError:
        return None


_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """Return the module-level WebSocketManager singleton."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager
