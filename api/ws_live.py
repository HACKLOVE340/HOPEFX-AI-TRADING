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
  { "type": "error",           "code": str, "message": str }

Message format (client → server):
  { "type": "auth",        "token": "Bearer <jwt>" }
  { "type": "subscribe",   "channels": ["prices", "signals", ...] }
  { "type": "ping" }
  { "type": "unsubscribe", "channels": [...] }

Authentication
--------------
Clients MUST send an auth message within AUTH_TIMEOUT_SECONDS of connecting,
or the connection is closed with code 4001.

  { "type": "auth", "token": "Bearer eyJ..." }

After successful auth, the connection is associated with a user_id so
per-user channels (e.g. "account", "positions") only deliver that user's data.

Heartbeat
---------
Server sends { "type": "heartbeat" } every HEARTBEAT_INTERVAL_SECONDS.
Clients should respond with { "type": "ping" } to confirm liveness.
Connections that miss HEARTBEAT_MISS_LIMIT consecutive heartbeats are closed.

Reconnection
------------
On disconnect the client should reconnect with exponential back-off.
The server assigns a new connection_id on each reconnect — no session state
is preserved server-side (stateless design).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Live"])

# Tracks last mid price per symbol for change_pct calculation
_last_mid: dict[str, float] = {}

# ── Auth / heartbeat config ───────────────────────────────────────────────────
AUTH_TIMEOUT_SECONDS: float = float(os.getenv("WS_AUTH_TIMEOUT", "10"))
HEARTBEAT_INTERVAL_SECONDS: float = float(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
HEARTBEAT_MISS_LIMIT: int = int(os.getenv("WS_HEARTBEAT_MISS_LIMIT", "3"))
# Set to "false" to allow unauthenticated connections (dev/demo mode)
WS_AUTH_REQUIRED: bool = os.getenv("WS_AUTH_REQUIRED", "true").lower() == "true"


def _validate_ws_token(token: str) -> Optional[dict]:
    """Validate a Bearer token from a WS auth message. Returns payload or None."""
    if token.startswith("Bearer "):
        token = token[7:]
    try:
        from auth.jwt import decode_access_token
        return decode_access_token(token)
    except Exception as exc:
        logger.debug("WS token validation failed: %s", exc)
        return None


# ─── Connection registry ──────────────────────────────────────────────────────


class LiveConnectionManager:
    """
    Manages all active /ws/live connections.

    Per-connection state:
      - WebSocket object
      - Subscribed channels (set of strings)
      - Authenticated user_id (None = unauthenticated)
      - Heartbeat miss counter
    """

    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}
        self._subscriptions: Dict[str, Set[str]] = {}
        # connection_id → user_id (None until auth message received)
        self._user_ids: Dict[str, Optional[str]] = {}
        # connection_id → heartbeat miss count
        self._hb_misses: Dict[str, int] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"conn_{self._counter}"

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        cid = self._new_id()
        self._connections[cid] = ws
        self._subscriptions[cid] = set()
        self._user_ids[cid] = None
        self._hb_misses[cid] = 0
        logger.info("WS connected: %s  total=%d", cid, len(self._connections))
        return cid

    def authenticate(self, cid: str, user_id: str) -> None:
        """Associate a connection with an authenticated user."""
        self._user_ids[cid] = user_id
        logger.info("WS authenticated: %s  user=%s", cid, user_id)

    def is_authenticated(self, cid: str) -> bool:
        return self._user_ids.get(cid) is not None

    def get_user_id(self, cid: str) -> Optional[str]:
        return self._user_ids.get(cid)

    def disconnect(self, cid: str) -> None:
        self._connections.pop(cid, None)
        self._subscriptions.pop(cid, None)
        self._user_ids.pop(cid, None)
        self._hb_misses.pop(cid, None)
        logger.info("WS disconnected: %s  total=%d", cid, len(self._connections))

    def subscribe(self, cid: str, channels: list[str]) -> None:
        if cid in self._subscriptions:
            self._subscriptions[cid].update(channels)

    def unsubscribe(self, cid: str, channels: list[str]) -> None:
        if cid in self._subscriptions:
            self._subscriptions[cid].difference_update(channels)

    def record_pong(self, cid: str) -> None:
        """Reset heartbeat miss counter when client responds."""
        self._hb_misses[cid] = 0

    def record_hb_miss(self, cid: str) -> int:
        """Increment miss counter. Returns new count."""
        self._hb_misses[cid] = self._hb_misses.get(cid, 0) + 1
        return self._hb_misses[cid]

    async def send(self, cid: str, msg: dict) -> None:
        ws = self._connections.get(cid)
        if ws:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception as exc:
                logger.debug("WS send failed for %s: %s", cid, exc)
                self.disconnect(cid)

    async def broadcast(self, channel: str, msg: dict) -> None:
        """
        Send to all connections subscribed to channel.
        Empty subscription set = subscribed to all channels.
        """
        dead: list[str] = []
        for cid, subs in list(self._subscriptions.items()):
            if channel in subs or not subs:
                ws = self._connections.get(cid)
                if ws:
                    try:
                        await ws.send_text(json.dumps(msg))
                    except Exception as exc:
                        logger.debug("WS broadcast failed for %s: %s", cid, exc)
                        dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def send_to_user(self, user_id: str, channel: str, msg: dict) -> None:
        """
        Send a message only to connections belonging to a specific user.
        Used for per-user channels: account updates, position fills, alerts.
        """
        dead: list[str] = []
        for cid, uid in list(self._user_ids.items()):
            if uid != user_id:
                continue
            subs = self._subscriptions.get(cid, set())
            if channel in subs or not subs:
                ws = self._connections.get(cid)
                if ws:
                    try:
                        await ws.send_text(json.dumps(msg))
                    except Exception as exc:
                        logger.debug("WS user-send failed for %s: %s", cid, exc)
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
            # Normalise to frontend PriceTick schema:
            # { type: "price_tick", data: PriceTick }
            symbol = msg.get("symbol", "XAU/USD")
            mid    = float(msg.get("mid") or 0)
            # Track previous mid for change_pct calculation
            prev   = _last_mid.get(symbol, mid)
            change = ((mid - prev) / prev * 100) if prev else 0.0
            _last_mid[symbol] = mid

            tick = {
                "type": "price_tick",
                "data": {
                    "symbol":     symbol,
                    "bid":        msg.get("bid"),
                    "ask":        msg.get("ask"),
                    "mid":        mid,
                    "spread":     msg.get("spread"),
                    "timestamp":  msg.get("timestamp"),
                    "change_pct": round(change, 4),
                },
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
            # Normalise to the frontend WsMessage schema:
            # { type: "signal", data: Signal }
            direction_raw = (msg.get("direction") or "neutral").lower()
            direction_fe  = (
                "long"  if direction_raw == "buy"  else
                "short" if direction_raw == "sell" else
                "neutral"
            )
            mid = msg.get("mid", 0.0)
            signal = {
                "type": "signal",
                "data": {
                    "id":           f"sig_{msg.get('tick_seq', 0)}",
                    "symbol":       msg.get("symbol", "XAU/USD"),
                    "direction":    direction_fe,
                    "confidence":   msg.get("confidence", 0.0),
                    "model":        "advanced_oos",
                    "entry_price":  mid,
                    "stop_loss":    round(mid * 0.998, 5),   # 0.2% SL placeholder
                    "take_profit":  round(mid * 1.004, 5),   # 0.4% TP placeholder
                    "generated_at": msg.get("timestamp", ""),
                    "status":       "active",
                },
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
    """
    Send heartbeat every HEARTBEAT_INTERVAL_SECONDS to all connections.
    Connections that miss HEARTBEAT_MISS_LIMIT consecutive heartbeats are closed.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        if _manager.connection_count == 0:
            continue
        dead: list[str] = []
        for cid in list(_manager._connections.keys()):
            misses = _manager.record_hb_miss(cid)
            if misses > HEARTBEAT_MISS_LIMIT:
                logger.info(
                    "WS closing stale connection %s (missed %d heartbeats)", cid, misses
                )
                dead.append(cid)
            else:
                await _manager.send(cid, {"type": "heartbeat"})
        for cid in dead:
            ws = _manager._connections.get(cid)
            if ws:
                try:
                    await ws.close(code=1001, reason="heartbeat timeout")
                except Exception:
                    pass
            _manager.disconnect(cid)


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

    Auth flow:
      1. Server accepts connection and sends { "type": "connected" }
      2. Client sends { "type": "auth", "token": "Bearer <jwt>" }
         within AUTH_TIMEOUT_SECONDS, or connection is closed (4001).
      3. Server sends { "type": "auth_ok", "user_id": "..." }
      4. Client subscribes to channels and receives live data.

    Heartbeat:
      Server sends { "type": "heartbeat" } every HEARTBEAT_INTERVAL_SECONDS.
      Client should respond with { "type": "ping" } to reset the miss counter.
      After HEARTBEAT_MISS_LIMIT missed heartbeats the connection is closed (1001).
    """
    cid = await _manager.connect(websocket)

    await _manager.send(cid, {
        "type": "connected",
        "connection_id": cid,
        "auth_required": WS_AUTH_REQUIRED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # ── Auth gate ─────────────────────────────────────────────────────────────
    if WS_AUTH_REQUIRED:
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
            )
            msg = json.loads(raw)
            if msg.get("type") != "auth":
                await _manager.send(cid, {
                    "type": "error",
                    "code": "AUTH_REQUIRED",
                    "message": "First message must be {type: auth, token: ...}",
                })
                await websocket.close(code=4001)
                _manager.disconnect(cid)
                return

            payload = _validate_ws_token(msg.get("token", ""))
            if payload is None:
                await _manager.send(cid, {
                    "type": "error",
                    "code": "AUTH_FAILED",
                    "message": "Invalid or expired token",
                })
                await websocket.close(code=4001)
                _manager.disconnect(cid)
                return

            user_id = str(payload.get("sub", payload.get("user_id", "unknown")))
            _manager.authenticate(cid, user_id)
            await _manager.send(cid, {
                "type": "auth_ok",
                "user_id": user_id,
                "role": payload.get("role", "trader"),
            })

        except asyncio.TimeoutError:
            await _manager.send(cid, {
                "type": "error",
                "code": "AUTH_TIMEOUT",
                "message": f"Auth required within {AUTH_TIMEOUT_SECONDS}s",
            })
            await websocket.close(code=4001)
            _manager.disconnect(cid)
            return
        except (WebSocketDisconnect, Exception) as exc:
            logger.debug("WS auth phase error [%s]: %s", cid, exc)
            _manager.disconnect(cid)
            return

    # ── Main message loop ─────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _manager.send(cid, {
                    "type": "error",
                    "code": "INVALID_JSON",
                    "message": "Message must be valid JSON",
                })
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
                await _manager.send(cid, {
                    "type": "unsubscribed",
                    "channels": channels,
                })

            elif msg_type == "ping":
                # Client responding to heartbeat — reset miss counter
                _manager.record_pong(cid)
                await _manager.send(cid, {"type": "pong"})

            elif msg_type == "auth":
                # Re-auth (token refresh) — validate new token
                payload = _validate_ws_token(msg.get("token", ""))
                if payload:
                    user_id = str(payload.get("sub", "unknown"))
                    _manager.authenticate(cid, user_id)
                    await _manager.send(cid, {
                        "type": "auth_ok",
                        "user_id": user_id,
                    })
                else:
                    await _manager.send(cid, {
                        "type": "error",
                        "code": "AUTH_FAILED",
                        "message": "Invalid or expired token",
                    })

            else:
                await _manager.send(cid, {
                    "type": "error",
                    "code": "UNKNOWN_MESSAGE_TYPE",
                    "message": f"Unknown message type: {msg_type}",
                })

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


async def push_position_update(position: dict, user_id: Optional[str] = None) -> None:
    """Push a position update. If user_id is given, only that user receives it."""
    msg = {"type": "position_update", "data": position}
    if user_id:
        await _manager.send_to_user(user_id, "positions", msg)
    else:
        await _manager.broadcast("positions", msg)


async def push_position_close(position_id: str, user_id: Optional[str] = None) -> None:
    msg = {"type": "position_close", "data": {"id": position_id}}
    if user_id:
        await _manager.send_to_user(user_id, "positions", msg)
    else:
        await _manager.broadcast("positions", msg)


async def push_signal(signal: dict) -> None:
    """Signals are broadcast to all subscribers (not user-specific)."""
    await _manager.broadcast("signals", {"type": "signal", "data": signal})


async def push_account_update(account: dict, user_id: Optional[str] = None) -> None:
    """Account updates are per-user — equity/balance is private."""
    msg = {"type": "account_update", "data": account}
    if user_id:
        await _manager.send_to_user(user_id, "account", msg)
    else:
        await _manager.broadcast("account", msg)


async def push_alert(alert: dict, user_id: str) -> None:
    """Price alerts are always per-user."""
    await _manager.send_to_user(user_id, "alerts", {
        "type": "alert_triggered", "data": alert,
    })
