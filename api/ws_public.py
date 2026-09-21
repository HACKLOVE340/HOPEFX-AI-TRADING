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
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Public"])

UTC = timezone.utc

# ── Config ────────────────────────────────────────────────────────────────────
TICK_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_TICK_INTERVAL", "2.0"))
HEARTBEAT_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_HEARTBEAT_INTERVAL", "30.0"))
MAX_PUBLIC_CONNECTIONS: int = int(os.getenv("WS_PUBLIC_MAX_CONNECTIONS", "500"))

# Per-IP rate limiting
# Max concurrent open connections from a single IP address. Raised from 10 →
# a single user opens several sockets per page (ticker/live/chat) across tabs,
# and behind a NAT/proxy many users share one IP, so 10 was far too low.
WS_MAX_CONNECTIONS_PER_IP: int = int(os.getenv("WS_MAX_CONNECTIONS_PER_IP", "50"))
# Max new connections per IP per minute (sliding window).
WS_MAX_CONNECTIONS_PER_MINUTE: int = int(os.getenv("WS_MAX_CONNECTIONS_PER_MINUTE", "120"))

# Loopback addresses are never rate-limited: in local dev every connection comes
# from 127.0.0.1, so the per-IP cap would otherwise drop WS on some pages.
_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "localhost"})

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

# Per-IP tracking: ip → count of open connections
_ip_open_count: Counter[str] = Counter()
# Per-IP rate window: ip → deque of connect timestamps (monotonic seconds)
_ip_rate_window: dict[str, deque] = defaultdict(deque)
_ip_lock = asyncio.Lock()


def _get_client_ip(ws: WebSocket) -> str:
    """Extract the real client IP, honouring X-Forwarded-For when present."""
    forwarded = ws.headers.get("x-forwarded-for", "")
    if forwarded:
        # Take the first (leftmost) address — the original client.
        return forwarded.split(",")[0].strip()
    client = ws.client
    return client.host if client else "unknown"


async def _check_ip_rate_limit(ip: str) -> tuple[bool, str]:
    """
    Check per-IP rate limits.

    Returns (allowed: bool, reason: str).
    Cleans up stale rate-window entries on each call.
    """
    # Never rate-limit loopback (local development).
    if ip in _LOOPBACK_IPS:
        return True, ""
    async with _ip_lock:
        now = time.monotonic()
        window = _ip_rate_window[ip]

        # Evict entries older than 60 seconds.
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()

        # Check concurrent connection cap.
        if _ip_open_count[ip] >= WS_MAX_CONNECTIONS_PER_IP:
            return False, f"Too many concurrent connections from this IP (max {WS_MAX_CONNECTIONS_PER_IP})"

        # Check per-minute rate.
        if len(window) >= WS_MAX_CONNECTIONS_PER_MINUTE:
            return False, f"Connection rate limit exceeded (max {WS_MAX_CONNECTIONS_PER_MINUTE}/min)"

        # Admit the connection.
        window.append(now)
        _ip_open_count[ip] += 1
        return True, ""


async def _release_ip_slot(ip: str) -> None:
    """Decrement the open-connection counter for an IP on disconnect."""
    async with _ip_lock:
        if _ip_open_count[ip] > 0:
            _ip_open_count[ip] -= 1
        if _ip_open_count[ip] == 0:
            _ip_open_count.pop(ip, None)


# ── Shared price cache + refresher ──────────────────────────────────────────────
# One background task refreshes prices for ALL public symbols and every
# connection (plus the /api/public/prices REST endpoint) reads from this shared
# cache. This avoids hammering the upstream once per connection and guarantees
# the landing ticker is populated the moment a client connects.
_price_cache: dict[str, dict] = {}
_refresher_task: asyncio.Task | None = None
_refresher_lock = asyncio.Lock()
_yf_last_fetch: dict[str, float] = {}

REFRESH_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_REFRESH_INTERVAL", "3.0"))
# yfinance is a slow external call — rate-limit it per symbol so we never spam it.
YF_MIN_INTERVAL_SECONDS: float = float(os.getenv("WS_PUBLIC_YF_INTERVAL", "15.0"))

# Symbol → yfinance ticker. Used only as a last-resort fallback so the public
# ticker still shows indicative (delayed) prices when no broker feed / Redis is
# configured (e.g. a fresh install with no API keys).
_YF_TICKER_MAP: dict[str, str] = {
    "XAU_USD": "GC=F",
    "XAG_USD": "SI=F",
    "EUR_USD": "EURUSD=X",
    "GBP_USD": "GBPUSD=X",
    "USD_JPY": "JPY=X",
    "USD_CHF": "CHF=X",
    "AUD_USD": "AUDUSD=X",
    "BTC_USD": "BTC-USD",
}


def _make_tick(symbol: str, bid: float, ask: float, source: str) -> dict | None:
    """Build a normalised tick dict and update the change-percentage baseline."""
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    prev = _last_mid.get(symbol, mid)
    change_pct = ((mid - prev) / prev * 100.0) if prev > 0 else 0.0
    _last_mid[symbol] = mid
    return {
        "symbol": symbol,
        "bid": round(bid, 5),
        "ask": round(ask, 5),
        "mid": round(mid, 5),
        "change_pct": round(change_pct, 4),
        "source": source,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _fetch_orchestrator_tick(symbol: str) -> dict | None:
    """Latest tick from the live data-layer orchestrator (sync, in-memory/Redis)."""
    try:
        from data_layer import orchestrator

        tick = orchestrator.get_latest_tick(symbol)
        if tick:
            return _make_tick(symbol, float(tick.bid), float(tick.ask), "live")
    except Exception as exc:  # nosec B110 — fall through to next source
        logger.debug("ws_public: orchestrator tick unavailable for %s: %s", symbol, exc)
    return None


async def _fetch_redis_tick(symbol: str) -> dict | None:
    """Latest tick from the Redis price cache (tick:{symbol})."""
    try:
        from cache.redis_client import get_redis

        redis = await get_redis()
        if redis:
            raw = await redis.get(f"tick:{symbol}")
            if raw:
                data = json.loads(raw)
                return _make_tick(symbol, float(data.get("bid", 0)), float(data.get("ask", 0)), "cache")
    except Exception as exc:  # nosec B110 — fall through to next source
        logger.debug("ws_public: Redis tick unavailable for %s: %s", symbol, exc)
    return None


def _fetch_yf_sync(symbol: str) -> dict | None:
    """Blocking yfinance fallback — must be called via a thread executor."""
    try:
        import yfinance as _yf

        yticker = _YF_TICKER_MAP.get(symbol)
        if not yticker:
            return None
        info = _yf.Ticker(yticker).fast_info
        last = float(info.last_price) if getattr(info, "last_price", None) else None
        if last and last > 0:
            spread = max(last * 0.0001, 1e-5)  # ~1 bp indicative spread
            return _make_tick(symbol, last - spread, last + spread, "delayed")
    except Exception as exc:  # nosec B110 — returns None, symbol simply has no price
        logger.debug("ws_public: yfinance fallback failed for %s: %s", symbol, exc)
    return None


async def _refresh_symbol(symbol: str) -> None:
    """Refresh one symbol in the shared cache: live → Redis → yfinance."""
    tick = _fetch_orchestrator_tick(symbol)
    if tick is None:
        tick = await _fetch_redis_tick(symbol)
    if tick is None:
        # yfinance is slow + rate-limited per symbol, and runs off the event loop.
        now = time.monotonic()
        if now - _yf_last_fetch.get(symbol, 0.0) >= YF_MIN_INTERVAL_SECONDS:
            _yf_last_fetch[symbol] = now
            loop = asyncio.get_event_loop()
            tick = await loop.run_in_executor(None, _fetch_yf_sync, symbol)
    if tick is not None:
        _price_cache[symbol] = tick


async def _refresh_loop() -> None:
    """Continuously refresh all public symbols into the shared cache."""
    while True:
        for symbol in PUBLIC_SYMBOLS:
            try:
                await _refresh_symbol(symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let one symbol kill the loop
                logger.debug("ws_public: refresh error for %s: %s", symbol, exc)
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


async def _ensure_refresher() -> None:
    """Start the shared price refresher once (idempotent)."""
    global _refresher_task
    async with _refresher_lock:
        if _refresher_task is None or _refresher_task.done():
            _refresher_task = asyncio.create_task(_refresh_loop())
            logger.info("ws_public: shared price refresher started")


async def _broadcast_ticks(ws: WebSocket) -> None:
    """Continuously push cached price ticks to a single connection."""
    heartbeat_counter = 0
    heartbeat_every = max(1, int(HEARTBEAT_INTERVAL_SECONDS / TICK_INTERVAL_SECONDS))

    # Send whatever is already cached immediately so the client isn't blank.
    for symbol in PUBLIC_SYMBOLS:
        tick = _price_cache.get(symbol)
        if tick is not None:
            try:
                await ws.send_json({"type": "price_tick", "data": tick})
            except Exception:
                return

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

        # Price ticks (read from the shared cache)
        for symbol in PUBLIC_SYMBOLS:
            tick = _price_cache.get(symbol)
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

    Rate limiting (per-IP):
      - Max WS_MAX_CONNECTIONS_PER_IP concurrent connections (default 10).
      - Max WS_MAX_CONNECTIONS_PER_MINUTE new connections per minute (default 30).
      - Global cap: WS_PUBLIC_MAX_CONNECTIONS total concurrent connections.
    """
    # ── Global capacity check (before accept to avoid wasting a handshake) ──
    if len(_active_connections) >= MAX_PUBLIC_CONNECTIONS:
        await ws.close(code=1013, reason="Server at capacity")
        return

    # ── Per-IP rate limit check ───────────────────────────────────────────────
    client_ip = _get_client_ip(ws)
    allowed, reason = await _check_ip_rate_limit(client_ip)
    if not allowed:
        logger.warning("ws/public: rate-limited IP=%s reason=%r", client_ip, reason)
        await ws.close(code=1008, reason=reason)
        return

    await ws.accept()
    _active_connections.add(ws)
    logger.debug(
        "ws/public: new connection ip=%s total=%d",
        client_ip,
        len(_active_connections),
    )

    # Make sure the shared price refresher is running so ticks actually flow.
    await _ensure_refresher()

    broadcast_task: asyncio.Task | None = None
    try:
        # Confirm subscription (echo back the public symbols so the client can
        # render the subscribed set even before the first tick arrives).
        await ws.send_json({"type": "subscribed", "channels": ["prices"], "symbols": PUBLIC_SYMBOLS})

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
        logger.debug("ws/public: client disconnected normally ip=%s", client_ip)
    except Exception as exc:
        logger.debug("ws/public: connection error ip=%s: %s", client_ip, exc)
    finally:
        if broadcast_task is not None:
            broadcast_task.cancel()
        _active_connections.discard(ws)
        await _release_ip_slot(client_ip)
        logger.debug(
            "ws/public: disconnected ip=%s total=%d",
            client_ip,
            len(_active_connections),
        )


@router.get("/api/public/prices")
async def public_prices() -> dict:
    """
    Public (no-auth) snapshot of the landing-page ticker prices.

    Polling fallback for clients where the WebSocket is blocked (corporate
    proxies, etc.). Reads the same shared cache the WS broadcasts from, so it
    never hits the upstream once per request. Starts the refresher on first call.
    """
    await _ensure_refresher()
    return {
        "symbols": PUBLIC_SYMBOLS,
        "prices": list(_price_cache.values()),
        "count": len(_price_cache),
    }


@router.get("/api/public/signals")
async def public_signals(limit: int = 8) -> dict:
    """
    Public (no-auth) teaser of the latest signals for the landing page.

    Sanitised on purpose: only symbol/direction/confidence/strength/timeframe and
    timestamp are exposed — the actionable trade levels (entry, stop-loss,
    take-profit) are withheld so they remain a sign-up incentive. Returns an
    empty list (never an error) when the signal service isn't ready.
    """
    try:
        from api.signals import _get_signal_service

        svc = _get_signal_service()
        recent = svc.get_signal_history(symbol=None, hours=24)[: max(1, min(limit, 25))]
        out = []
        for s in recent:
            d = s.to_dict()
            strategies = d.get("strategies_agreeing") or []
            out.append(
                {
                    "symbol": d.get("symbol"),
                    "direction": str(d.get("direction", "neutral")).lower(),
                    "confidence": d.get("confidence", 0),
                    "strength": d.get("strength"),
                    "timeframe": d.get("timeframe"),
                    "strategy": (strategies[0] if strategies else d.get("regime")) or "HOPEFX",
                    "timestamp": d.get("timestamp"),
                }
            )
        return {"signals": out, "count": len(out)}
    except Exception as exc:  # nosec B110 — teaser only, never surface an error
        logger.debug("ws_public: public signals unavailable: %s", exc)
        return {"signals": [], "count": 0}
