"""
api/ws_live.py
==============
Live WebSocket endpoint at /ws/live — matches the frontend protocol.

Message format (server → client):
  { "type": "price_tick",      "data": PriceTick }
  { "type": "position_update", "data": Position  }
  { "type": "position_close",  "data": {"id": str} }
  { "type": "signal",          "data": Signal    }
  { "type": "account_update",  "data": AccountMetrics }
  { "type": "heartbeat" }

Message format (client → server):
  { "type": "subscribe",   "channels": ["prices", "signals", ...] }
  { "type": "ping" }
  { "type": "unsubscribe", "channels": [...] }
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import math
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Live"])

# ─── Connection registry ──────────────────────────────────────────────────────

class LiveConnectionManager:
    """Manages all active /ws/live connections."""

    def __init__(self) -> None:
        # connection_id → WebSocket
        self._connections: Dict[str, WebSocket] = {}
        # connection_id → subscribed channels
        self._subscriptions: Dict[str, Set[str]] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"conn_{self._counter}"

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        cid = self._new_id()
        self._connections[cid] = ws
        self._subscriptions[cid] = set()
        logger.info("WS connected: %s  total=%d", cid, len(self._connections))
        return cid

    def disconnect(self, cid: str) -> None:
        self._connections.pop(cid, None)
        self._subscriptions.pop(cid, None)
        logger.info("WS disconnected: %s  total=%d", cid, len(self._connections))

    def subscribe(self, cid: str, channels: list[str]) -> None:
        if cid in self._subscriptions:
            self._subscriptions[cid].update(channels)

    def unsubscribe(self, cid: str, channels: list[str]) -> None:
        if cid in self._subscriptions:
            self._subscriptions[cid].difference_update(channels)

    async def send(self, cid: str, msg: dict) -> None:
        ws = self._connections.get(cid)
        if ws:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                self.disconnect(cid)

    async def broadcast(self, channel: str, msg: dict) -> None:
        """Send to all connections subscribed to channel."""
        dead: list[str] = []
        for cid, subs in list(self._subscriptions.items()):
            if channel in subs or not subs:  # empty subs = subscribed to all
                ws = self._connections.get(cid)
                if ws:
                    try:
                        await ws.send_text(json.dumps(msg))
                    except Exception:
                        dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton
_manager = LiveConnectionManager()


def get_live_manager() -> LiveConnectionManager:
    return _manager


# ─── Price simulator (server-side GBM) ───────────────────────────────────────

_SYMBOLS: Dict[str, Dict[str, float]] = {
    "XAU/USD": {"price": 2340.0, "vol": 0.012, "spread": 0.30},
    "EUR/USD": {"price": 1.0850, "vol": 0.006, "spread": 0.0001},
    "GBP/USD": {"price": 1.2700, "vol": 0.007, "spread": 0.0002},
    "USD/JPY": {"price": 149.50, "vol": 0.006, "spread": 0.02},
    "BTC/USD": {"price": 67000.0, "vol": 0.025, "spread": 10.0},
}

_open_prices: Dict[str, float] = {sym: cfg["price"] for sym, cfg in _SYMBOLS.items()}


def _gbm_step(price: float, vol: float, dt: float) -> float:
    """One GBM step using Box-Muller normal sample."""
    u1, u2 = random.random(), random.random()
    z = math.sqrt(-2 * math.log(max(u1, 1e-10))) * math.cos(2 * math.pi * u2)
    return price * math.exp(-0.5 * vol * vol * dt + vol * math.sqrt(dt) * z)


def _make_tick(symbol: str) -> dict:
    cfg = _SYMBOLS[symbol]
    dt  = 1.0 / (24 * 60 * 60)  # 1-second step as fraction of day
    cfg["price"] = _gbm_step(cfg["price"], cfg["vol"], dt)
    mid    = cfg["price"]
    half   = cfg["spread"] / 2
    change = (mid - _open_prices[symbol]) / _open_prices[symbol] * 100
    return {
        "type": "price_tick",
        "data": {
            "symbol":     symbol,
            "bid":        round(mid - half, 5),
            "ask":        round(mid + half, 5),
            "mid":        round(mid, 5),
            "spread":     cfg["spread"],
            "timestamp":  int(datetime.now(timezone.utc).timestamp() * 1000),
            "change_pct": round(change, 3),
        },
    }


# ─── Background broadcaster ───────────────────────────────────────────────────

_broadcast_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]


async def _price_broadcaster() -> None:
    """Broadcast price ticks every second while connections exist."""
    while True:
        await asyncio.sleep(1)
        if _manager.connection_count == 0:
            continue
        for symbol in _SYMBOLS:
            tick = _make_tick(symbol)
            await _manager.broadcast("prices", tick)


async def _heartbeat_broadcaster() -> None:
    """Send heartbeat every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        if _manager.connection_count > 0:
            await _manager.broadcast("", {"type": "heartbeat"})


def start_broadcasters() -> None:
    """Start background tasks (call once from app lifespan)."""
    global _broadcast_task
    loop = asyncio.get_event_loop()
    loop.create_task(_price_broadcaster())
    loop.create_task(_heartbeat_broadcaster())
    logger.info("WS live broadcasters started")


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """
    Main live WebSocket endpoint.
    Streams price ticks, positions, signals, account updates.
    """
    cid = await _manager.connect(websocket)

    # Send connection ack
    await _manager.send(cid, {
        "type": "connected",
        "connection_id": cid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "subscribe":
                channels = msg.get("channels", [])
                _manager.subscribe(cid, channels)
                await _manager.send(cid, {
                    "type": "subscribed",
                    "channels": channels,
                })

            elif msg_type == "unsubscribe":
                channels = msg.get("channels", [])
                _manager.unsubscribe(cid, channels)

            elif msg_type == "ping":
                await _manager.send(cid, {"type": "pong"})

    except WebSocketDisconnect:
        _manager.disconnect(cid)
    except Exception as exc:
        logger.error("WS live error [%s]: %s", cid, exc)
        _manager.disconnect(cid)


# ─── REST helpers ─────────────────────────────────────────────────────────────

@router.get("/ws/live/stats")
async def ws_live_stats() -> dict:
    """Current WebSocket connection stats."""
    return {
        "connections": _manager.connection_count,
        "symbols":     list(_SYMBOLS.keys()),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


# ─── Push helpers (called from trading/signal routers) ───────────────────────

async def push_position_update(position: dict) -> None:
    await _manager.broadcast("positions", {"type": "position_update", "data": position})


async def push_position_close(position_id: str) -> None:
    await _manager.broadcast("positions", {"type": "position_close", "data": {"id": position_id}})


async def push_signal(signal: dict) -> None:
    await _manager.broadcast("signals", {"type": "signal", "data": signal})


async def push_account_update(account: dict) -> None:
    await _manager.broadcast("account", {"type": "account_update", "data": account})
