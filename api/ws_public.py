# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/ws_public.py
================
Unauthenticated public WebSocket endpoint at /ws/public.

Used by the landing page ticker and any public-facing price display.
No auth required — only price ticks for a fixed set of public symbols
are broadcast.  No account, position, or signal data is exposed.

Message format (server → client):
  { "type": "price_tick", "data": { "symbol": str, "bid": float,
                                     "ask": float, "mid": float,
                                     "change_pct": float,
                                     "timestamp": str } }
  { "type": "heartbeat" }
  { "type": "subscribed", "channels": ["prices"] }

Message format (client → server):
  { "type": "subscribe", "channels": ["prices"] }
  { "type": "ping" }

Rate limiting
-------------
Each connection receives ticks at most every TICK_INTERVAL_SECONDS.
Max concurrent public connections is capped at MAX_PUBLIC_CONNECTIONS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Public"])

UTC = timezone.utc

# ── Config ────────────────────────────────────────────────────────────────────
TICK_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_TICK_INTERVAL", "2.0"))
HEARTBEAT_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_HEARTBEAT_INTERVAL", "30.0"))
MAX_PUBLIC_CONNECTIONS: int = int(os.getenv("WS_PUBLIC_MAX_CONNECTIONS", "500"))

PUBLIC_SYMBOLS = [
    "XAU_USD",
    "EUR_USD",
    "GBP_USD",
    "USD_JPY",
    "XAG_USD",
    "BTC_USD",
    "USD_CHF",
    "AUD_USD",
]

# ── Connection registry ───────────────────────────────────────────────────────
_active_connections: set[WebSocket] = set()
_last_mid: dict[str, float] = {}


async def _get_price_tick(symbol: str) -> dict | None:
    """
    Fetch the latest price tick for a symbol.

    Priority:
      1. Live data-layer tick (real broker price)
      2. Redis cache
      3. None — caller skips this symbol
    """
    try:
        from data_layer import get_latest_tick

        tick = await get_latest_tick(symbol)
        if tick:
            mid = (tick.bid + tick.ask) / 2.0
            prev = _last_mid.get(symbol, mid)
            change_pct = ((mid - prev) / prev * 100.0) if prev else 0.0
            _last_mid[symbol] = mid
            return {
                "symbol": symbol,
                "bid": round(tick.bid, 5),
                "ask": round(tick.ask, 5),
                "mid": round(mid, 5),
                "change_pct": round(change_pct, 4),
                "timestamp": datetime.now(UTC).isoformat(),
            }
    except Exception as _exc:  # nosec B110 — fallback to Redis cache below
        logger.debug("ws_public: live tick unavailable for %s: %s", symbol, _exc)

    # Redis cache fallback
    try:
        from cache.redis_client import get_redis

        redis = await get_redis()
        if redis:
            raw = await redis.get(f"tick:{symbol}")
            if raw:
                data = json.loads(raw)
                bid = float(data.get("bid", 0))
                ask = float(data.get("ask", 0))
                mid = (bid + ask) / 2.0
                prev = _last_mid.get(symbol, mid)
                change_pct = ((mid - prev) / prev * 100.0) if prev else 0.0
                _last_mid[symbol] = mid
                return {
                    "symbol": symbol,
                    "bid": round(bid, 5),
                    "ask": round(ask, 5),
                    "mid": round(mid, 5),
                    "change_pct": round(change_pct, 4),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
    except Exception as _exc:  # nosec B110 — returns None, caller skips symbol
        logger.debug("ws_public: Redis tick unavailable for %s: %s", symbol, _exc)

    return None


async def _broadcast_ticks(ws: WebSocket) -> None:
    """Continuously push price ticks to a single connection."""
    heartbeat_counter = 0
    heartbeat_every = max(1, int(HEARTBEAT_INTERVAL_SECONDS / TICK_INTERVAL_SECONDS))

    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)

        # Heartbeat
        heartbeat_counter += 1
        if heartbeat_counter >= heartbeat_every:
            heartbeat_counter = 0
            try:
                await ws.send_json({"type": "heartbeat"})
            except Exception:
                return

        # Price ticks
        for symbol in PUBLIC_SYMBOLS:
            tick = await _get_price_tick(symbol)
            if tick is None:
                continue
            try:
                await ws.send_json({"type": "price_tick", "data": tick})
            except Exception:
                return


@router.websocket("/ws/public")
async def ws_public(ws: WebSocket) -> None:
    """
    Public WebSocket endpoint — no authentication required.

    Broadcasts price ticks for PUBLIC_SYMBOLS at TICK_INTERVAL_SECONDS.
    """
    if len(_active_connections) >= MAX_PUBLIC_CONNECTIONS:
        await ws.close(code=1013, reason="Server at capacity")
        return

    await ws.accept()
    _active_connections.add(ws)
    logger.debug("ws/public: new connection (total=%d)", len(_active_connections))

    broadcast_task: asyncio.Task | None = None  # initialised before try so finally can always reference it
    try:
        # Confirm subscription
        await ws.send_json({"type": "subscribed", "channels": ["prices"]})

        # Start tick broadcast in background
        broadcast_task = asyncio.create_task(_broadcast_ticks(ws))

        # Handle incoming messages (ping / subscribe)
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                # subscribe messages are accepted but ignored — we always
                # broadcast all public symbols
            except (json.JSONDecodeError, Exception) as _exc:
                logger.debug("ws/public: ignoring malformed client message: %s", _exc)

    except WebSocketDisconnect:
        logger.debug("ws/public: client disconnected normally")
    except Exception as exc:
        logger.debug("ws/public: connection error: %s", exc)
    finally:
        if broadcast_task is not None:
            broadcast_task.cancel()
        _active_connections.discard(ws)
        logger.debug("ws/public: disconnected (total=%d)", len(_active_connections))
