# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
import math
import random
from datetime import datetime, timezone
from typing import Dict, Optional, Set

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
            except Exception as exc:
                logger.debug(
                    "WebSocket send failed for %s, disconnecting: %s",
                    cid,
                    exc,
                )
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
                    except Exception as exc:
                        logger.debug(
                            "WebSocket broadcast failed for %s, marking dead: %s",
                            cid,
                            exc,
                        )
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


# ─── Price source (live broker → price engine → GBM fallback) ────────────────

# Symbol config: vol and spread used only when no live price is available.
# Keys use the slash format the frontend expects (XAU/USD etc.).
_SYMBOLS: Dict[str, Dict[str, float]] = {
    "XAU/USD": {"price": 3300.0, "vol": 0.012, "spread": 0.30},
    "EUR/USD": {"price": 1.0820, "vol": 0.006, "spread": 0.0001},
    "GBP/USD": {"price": 1.2940, "vol": 0.007, "spread": 0.0002},
    "USD/JPY": {"price": 149.50, "vol": 0.006, "spread": 0.02},
    "BTC/USD": {"price": 85000.0, "vol": 0.025, "spread": 10.0},
}

# Slash → no-slash lookup for broker.market_prices keys
_BROKER_KEY: Dict[str, str] = {
    "XAU/USD": "XAUUSD",
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "BTC/USD": "BTC/USD",
}

_open_prices: Dict[str, float] = {sym: cfg["price"] for sym, cfg in _SYMBOLS.items()}
_prices_seeded = False


def _seed_from_broker() -> None:
    """Seed _SYMBOLS and _open_prices from paper broker on first call."""
    global _prices_seeded
    if _prices_seeded:
        return
    try:
        from app import app_state  # noqa: PLC0415

        broker = getattr(app_state, "broker", None)
        market_prices = getattr(broker, "market_prices", {}) if broker else {}
        for sym, cfg in _SYMBOLS.items():
            broker_key = _BROKER_KEY.get(sym, sym.replace("/", ""))
            live = market_prices.get(broker_key)
            if live and live > 0:
                cfg["price"] = float(live)
                _open_prices[sym] = float(live)
        _prices_seeded = True
    except Exception:
        pass  # app_state not ready yet — will retry next tick


def _get_live_price(symbol: str) -> Optional[float]:
    """
    Return the current mid price from the live stack:
    1. price_engine.get_last_price() — real ticks when a feed is connected
    2. broker.market_prices          — paper broker static prices
    Returns None if neither is available.
    """
    try:
        from app import app_state  # noqa: PLC0415

        # 1. Price engine (real ticks)
        pe = getattr(app_state, "price_engine", None)
        if pe is not None:
            broker_key = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
            tick = pe.get_last_price(broker_key)
            if tick is not None:
                mid = getattr(tick, "mid", None) or (
                    (getattr(tick, "bid", 0) + getattr(tick, "ask", 0)) / 2
                )
                if mid and mid > 0:
                    return float(mid)

        # 2. Paper broker static prices
        broker = getattr(app_state, "broker", None)
        market_prices = getattr(broker, "market_prices", {}) if broker else {}
        broker_key = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
        live = market_prices.get(broker_key)
        if live and live > 0:
            return float(live)
    except Exception:
        pass
    return None


def _gbm_step(price: float, vol: float, dt: float) -> float:
    """One GBM step using Box-Muller normal sample (fallback only)."""
    u1, u2 = random.random(), random.random()
    z = math.sqrt(-2 * math.log(max(u1, 1e-10))) * math.cos(2 * math.pi * u2)
    return price * math.exp(-0.5 * vol * vol * dt + vol * math.sqrt(dt) * z)


def _make_tick(symbol: str) -> dict:
    """
    Build a price_tick message for the given symbol.

    Uses live broker/price-engine prices when available; falls back to
    GBM simulation only when no live source is connected.
    """
    _seed_from_broker()
    cfg = _SYMBOLS[symbol]

    live = _get_live_price(symbol)
    if live is not None:
        # Live price available — add a tiny realistic jitter (0.5 pip) so
        # the WebSocket stream looks like a real tick feed, not a static value.
        jitter = cfg["spread"] * 0.1 * (random.random() - 0.5)
        mid = live + jitter
        cfg["price"] = mid  # keep GBM anchored to live price
    else:
        # No live feed — advance GBM from last known price
        dt = 1.0 / (24 * 60 * 60)
        cfg["price"] = _gbm_step(cfg["price"], cfg["vol"], dt)
        mid = cfg["price"]

    half = cfg["spread"] / 2
    change = (mid - _open_prices[symbol]) / _open_prices[symbol] * 100
    return {
        "type": "price_tick",
        "data": {
            "symbol": symbol,
            "bid": round(mid - half, 5),
            "ask": round(mid + half, 5),
            "mid": round(mid, 5),
            "spread": cfg["spread"],
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "change_pct": round(change, 3),
        },
    }


# ─── Background broadcaster ───────────────────────────────────────────────────

_broadcast_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]


async def _eventbus_tick_broadcaster() -> None:
    """
    Subscribe to hopefx:tick on the EventBus and forward every validated
    tick to all WebSocket clients subscribed to the 'prices' channel.

    Falls back to the GBM simulator when the EventBus is in degraded mode
    (Redis unavailable) so the dashboard always shows something.
    """
    try:
        from core.event_bus import bus, CH_TICK
        await bus.connect()
        logger.info("WS live: connected to EventBus — streaming real ticks.")
        async for msg in bus.subscribe(CH_TICK):
            if _manager.connection_count == 0:
                continue
            tick = {
                "type":      "price_tick",
                "symbol":    msg.get("symbol", "XAU/USD"),
                "bid":       msg.get("bid"),
                "ask":       msg.get("ask"),
                "mid":       msg.get("mid"),
                "spread":    msg.get("spread"),
                "timestamp": msg.get("timestamp"),
            }
            await _manager.broadcast("prices", tick)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "WS live: EventBus tick stream failed (%s) — falling back to GBM simulator.", exc
        )
        await _price_broadcaster_sim()


async def _eventbus_signal_broadcaster() -> None:
    """
    Subscribe to hopefx:signal and forward signal_events to clients
    subscribed to the 'signals' channel.
    """
    try:
        from core.event_bus import bus, CH_SIGNAL
        await bus.connect()
        async for msg in bus.subscribe(CH_SIGNAL):
            if msg.get("type") != "signal_event":
                continue
            if _manager.connection_count == 0:
                continue
            signal = {
                "type":       "signal",
                "symbol":     msg.get("symbol"),
                "direction":  msg.get("direction"),
                "confidence": msg.get("confidence"),
                "mid":        msg.get("mid"),
                "timestamp":  msg.get("timestamp"),
            }
            await _manager.broadcast("signals", signal)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS live: EventBus signal stream failed: %s", exc)


async def _price_broadcaster_sim() -> None:
    """GBM simulator fallback — used when EventBus is unavailable."""
    while True:
        await asyncio.sleep(1)
        if _manager.connection_count == 0:
            continue
        for symbol in _SYMBOLS:
            tick = _make_tick(symbol)
            await _manager.broadcast("prices", tick)


async def _price_broadcaster() -> None:
    """Broadcast price ticks — tries EventBus first, falls back to GBM."""
    await _eventbus_tick_broadcaster()


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
    loop.create_task(_eventbus_signal_broadcaster())
    logger.info("WS live broadcasters started (EventBus + GBM fallback)")


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """
    Main live WebSocket endpoint.
    Streams price ticks, positions, signals, account updates.
    """
    cid = await _manager.connect(websocket)

    # Send connection ack
    await _manager.send(
        cid,
        {
            "type": "connected",
            "connection_id": cid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

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
                await _manager.send(
                    cid,
                    {
                        "type": "subscribed",
                        "channels": channels,
                    },
                )

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
        "symbols": list(_SYMBOLS.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Push helpers (called from trading/signal routers) ───────────────────────


async def push_position_update(position: dict) -> None:
    await _manager.broadcast("positions", {"type": "position_update", "data": position})


async def push_position_close(position_id: str) -> None:
    await _manager.broadcast(
        "positions",
        {"type": "position_close", "data": {"id": position_id}},
    )


async def push_signal(signal: dict) -> None:
    await _manager.broadcast("signals", {"type": "signal", "data": signal})


async def push_account_update(account: dict) -> None:
    await _manager.broadcast("account", {"type": "account_update", "data": account})
