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
  { "type": "microstructure",  "data": MicrostructureSnapshot }  — chart-bot channel
  { "type": "volume_delta",    "data": VolumeDeltaBar }          — chart-bot channel
  { "type": "sentiment_update","data": { "signal": SentimentSignal, "recent_articles": NewsArticle[] } }  — chart-bot channel
  { "type": "risk_update",     "data": RiskSnapshot }            — chart-bot channel
  { "type": "equity_update",   "data": EquitySnapshot }          — chart-bot channel
  { "type": "news_item",       "data": NewsItem }                — chart-bot channel

Message format (client → server):
  { "type": "auth",        "token": "Bearer <jwt>" }
  { "type": "subscribe",   "channels": ["prices", "signals", ...] }
  { "type": "ping" }
  { "type": "unsubscribe", "channels": [...] }

Authentication
--------------
Clients MUST send an auth message within AUTH_TIMEOUT_SECONDS (default 5 s)
of connecting, or the connection is closed with code 4001.

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
import itertools
import json
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Live"])

# Tracks last mid price per symbol for change_pct calculation
import threading as _threading

_last_mid: dict[str, float] = {}
_last_mid_lock = _threading.Lock()

# ── Auth / heartbeat config ───────────────────────────────────────────────────
# 5 s is sufficient for any legitimate client on a normal connection.
# 30 s was too long — it allowed unauthenticated connections to hold a slot
# for half a minute, enabling trivial resource exhaustion.
AUTH_TIMEOUT_SECONDS: float = float(os.getenv("WS_AUTH_TIMEOUT", "5"))
HEARTBEAT_INTERVAL_SECONDS: float = float(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
HEARTBEAT_MISS_LIMIT: int = int(os.getenv("WS_HEARTBEAT_MISS_LIMIT", "3"))
# Set to "false" to allow unauthenticated connections (dev/demo mode only).
# In production this MUST be true — all WS data (prices, signals, account
# updates) would otherwise be broadcast to unauthenticated connections.
WS_AUTH_REQUIRED: bool = os.getenv("WS_AUTH_REQUIRED", "true").lower() == "true"

_APP_ENV: str = os.getenv("APP_ENV", "development").lower()
if _APP_ENV == "production" and not WS_AUTH_REQUIRED:
    raise RuntimeError(
        "WS_AUTH_REQUIRED=false is not permitted in production (APP_ENV=production). "
        "Set WS_AUTH_REQUIRED=true or remove the override."
    )


async def _safe_ws_close(websocket: Any, code: int = 1000, reason: str = "") -> None:
    """Close a WebSocket, ignoring errors when it is already closed."""
    import contextlib

    with contextlib.suppress(RuntimeError):
        await websocket.close(code=code, reason=reason)


def _validate_ws_token(token: str) -> dict | None:
    """Validate a Bearer token from a WS auth message. Returns payload or None."""
    token = token.removeprefix("Bearer ")
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
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = {}
        # connection_id → user_id (None until auth message received)
        self._user_ids: dict[str, str | None] = {}
        # connection_id → heartbeat miss count
        self._hb_misses: dict[str, int] = {}
        # itertools.count is thread-safe in CPython (C-level increment) and
        # produces unique IDs even when multiple coroutines call connect()
        # concurrently — no lock needed for ID generation.
        self._counter = itertools.count(1)

    def _new_id(self) -> str:
        return f"conn_{next(self._counter)}"

    async def connect(self, ws: WebSocket) -> str:
        # Generate the ID before the await so the counter advances atomically
        # relative to other synchronous code. The await in ws.accept() is a
        # suspension point; generating the ID first ensures no two connections
        # share the same ID even if accept() yields to another coroutine.
        cid = self._new_id()
        await ws.accept()
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

    def get_user_id(self, cid: str) -> str | None:
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
        """Send to all connections subscribed to channel.

        JSON serialization is performed once before the loop so the cost is
        O(1) regardless of the number of connected clients. Previously the
        message was serialized inside the loop — O(n) allocations per tick.

        Empty subscription set = subscribed to all channels (pre-subscribe
        state while the client is still sending its subscribe message).
        """
        # Serialize once — reuse the string for every send.
        payload = json.dumps(msg)
        dead: list[str] = []
        for cid, subs in list(self._subscriptions.items()):
            if channel in subs or not subs:
                ws = self._connections.get(cid)
                if ws:
                    try:
                        await ws.send_text(payload)
                    except Exception as exc:
                        logger.debug("WS broadcast failed for %s: %s", cid, exc)
                        dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def broadcast_signal(self, symbol: str, signal: dict) -> None:
        """Called by signal_engine.py to push a signal to all 'signals' subscribers."""
        await self.broadcast("signals", {"type": "signal", "data": signal})
        try:
            from api.social_feed import _social_feed_broadcast as _sf_broadcast

            await _sf_broadcast(signal)
        except Exception:  # nosec B110
            pass

    async def send_to_user(self, user_id: str, channel: str, msg: dict) -> None:
        """Send a message only to connections belonging to a specific user.

        Used for per-user channels: account updates, position fills, alerts.
        JSON is serialized once before the loop (same rationale as broadcast).
        """
        payload = json.dumps(msg)
        dead: list[str] = []
        for cid, uid in list(self._user_ids.items()):
            if uid != user_id:
                continue
            subs = self._subscriptions.get(cid, set())
            if channel in subs or not subs:
                ws = self._connections.get(cid)
                if ws:
                    try:
                        await ws.send_text(payload)
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
_SYMBOLS: dict[str, dict[str, float]] = {
    "XAU/USD": {"price": 3300.0, "vol": 0.012, "spread": 0.30},
    "XAG/USD": {"price": 33.0,   "vol": 0.018, "spread": 0.03},
    "EUR/USD": {"price": 1.0820, "vol": 0.006, "spread": 0.0001},
    "GBP/USD": {"price": 1.2940, "vol": 0.007, "spread": 0.0002},
    "USD/JPY": {"price": 149.50, "vol": 0.006, "spread": 0.02},
    "BTC/USD": {"price": 85000.0, "vol": 0.025, "spread": 10.0},
}

# Slash → no-slash lookup for broker.market_prices keys
_BROKER_KEY: dict[str, str] = {
    "XAU/USD": "XAUUSD",
    "XAG/USD": "XAGUSD",
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "BTC/USD": "BTC/USD",
}

# Reverse map: broker/no-slash symbol → frontend slash format
_SLASH_SYMBOL: dict[str, str] = {v: k for k, v in _BROKER_KEY.items()}
# Extra aliases that may arrive from various publishers
_SLASH_SYMBOL.update(
    {
        "XAUUSD": "XAU/USD",
        "XAGUSD": "XAG/USD",
        "SI=F":   "XAG/USD",
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "BTCUSD": "BTC/USD",
        "ETHUSD": "ETH/USD",
        "GC=F": "XAU/USD",
        "EURUSD=X": "EUR/USD",
        "GBPUSD=X": "GBP/USD",
        "USDJPY=X": "USD/JPY",
    }
)

_open_prices: dict[str, float] = {sym: cfg["price"] for sym, cfg in _SYMBOLS.items()}
_prices_seeded = False


def _seed_from_broker() -> None:
    """Seed _SYMBOLS and _open_prices from paper broker on first call."""
    global _prices_seeded
    if _prices_seeded:
        return
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        market_prices = getattr(broker, "market_prices", {}) if broker else {}
        for sym, cfg in _SYMBOLS.items():
            broker_key = _BROKER_KEY.get(sym, sym.replace("/", ""))
            live = market_prices.get(broker_key)
            if live and live > 0:
                cfg["price"] = float(live)
                _open_prices[sym] = float(live)
        _prices_seeded = True
    except Exception as exc:
        logger.debug(
            "_seed_prices_from_broker: app_state not ready yet, will retry next tick: %s",
            exc,
        )


def _get_live_price(symbol: str) -> float | None:
    """
    Return the current mid price from the 4-level live price chain.

    Level 1 — price_engine.get_last_price()
        Real ticks from the connected data feed (NuclearStreamer / ProductionDataEngine).
    Level 2 — broker.market_prices
        Paper broker static prices (always available when broker is connected).
    Level 3 — Redis tick cache
        Most recent tick stored by the data feed writer (hopefx:tick_cache:{symbol}).
    Level 4 — EventBus last-known price
        Last price published on CH_TICK, held in the module-level _last_mid dict
        by the _eventbus_tick_broadcaster coroutine.

    Returns None only when all four levels fail, which triggers a no_live_feed
    status message to the client instead of fabricating a price.
    """
    broker_key = _BROKER_KEY.get(symbol, symbol.replace("/", ""))

    # ── Level 1: price engine ─────────────────────────────────────────────────
    try:
        from core.app_state import app_state

        pe = getattr(app_state, "price_engine", None)
        if pe is not None:
            tick = pe.get_last_price(broker_key)
            if tick is not None:
                mid = getattr(tick, "mid", None) or ((getattr(tick, "bid", 0) + getattr(tick, "ask", 0)) / 2)
                if mid and mid > 0:
                    return float(mid)
    except Exception as exc:
        logger.debug("_get_live_price L1 (%s): %s", symbol, exc)

    # ── Level 2: broker market prices ─────────────────────────────────────────
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        market_prices = getattr(broker, "market_prices", {}) if broker else {}
        live = market_prices.get(broker_key)
        if live and float(live) > 0:
            return float(live)
    except Exception as exc:
        logger.debug("_get_live_price L2 (%s): %s", symbol, exc)

    # ── Level 3: Redis tick cache ─────────────────────────────────────────────
    try:
        from market_data.redis_cache import MarketDataCache
        from cache.redis_pool import get_sync_client

        rc = MarketDataCache(get_sync_client())
        tick_data = rc.get_latest_tick(broker_key) or rc.get_latest_tick(symbol)
        if tick_data:
            bid = float(tick_data.get("bid", 0))
            ask = float(tick_data.get("ask", 0))
            mid = (bid + ask) / 2.0
            if mid > 0:
                return mid
    except Exception as exc:
        logger.debug("_get_live_price L3 (%s): %s", symbol, exc)

    # ── Level 4: EventBus last-known price (module-level _last_mid) ───────────
    # _last_mid is populated by _eventbus_tick_broadcaster as ticks arrive on
    # CH_TICK.  It is the last resort — stale but better than nothing.
    cached_mid = _last_mid.get(symbol) or _last_mid.get(broker_key)
    if cached_mid and cached_mid > 0:
        logger.debug("_get_live_price L4 (%s): using last-known mid=%.5f", symbol, cached_mid)
        return float(cached_mid)

    return None


def _make_tick(symbol: str) -> dict | None:
    """
    Build a price_tick message for the given symbol from live sources only.

    Returns None when no live price is available — callers must send a
    no_live_feed status message instead of fabricating prices.
    """
    _seed_from_broker()
    cfg = _SYMBOLS[symbol]

    live = _get_live_price(symbol)
    if live is None:
        return None

    mid = live
    cfg["price"] = mid

    half = cfg["spread"] / 2
    prev = _open_prices.get(symbol, mid)
    change = (mid - prev) / prev * 100 if prev > 0 else 0.0
    return {
        "type": "price_tick",
        "data": {
            "symbol": symbol,
            "bid": round(mid - half, 5),
            "ask": round(mid + half, 5),
            "mid": round(mid, 5),
            "spread": cfg["spread"],
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "change_pct": round(change, 3),
        },
    }


# ─── Background broadcaster ───────────────────────────────────────────────────

_broadcast_task: asyncio.Task | None = None  # type: ignore[type-arg]


async def _eventbus_tick_broadcaster() -> None:
    """
    Subscribe to hopefx:tick on the EventBus and forward every validated
    tick to all WebSocket clients subscribed to the 'prices' channel.

    Reconnects automatically with exponential backoff so a Redis blip does
    not leave the feed permanently dead until the process is restarted.

    If no tick arrives within _EVENTBUS_STALE_TIMEOUT_S seconds the broadcaster
    raises RuntimeError so _price_broadcaster falls through to the yfinance
    fallback — preventing a silent dead feed when the multi-source feed is not
    publishing to Redis.
    """
    _EVENTBUS_STALE_TIMEOUT_S = 30  # seconds without a tick before giving up

    _retry_delays = [5, 10, 20, 30, 60]
    attempt = 0
    while True:
        try:
            from core.event_bus import CH_TICK, bus

            await bus.connect()
            logger.info("WS live: connected to EventBus — streaming real ticks.")
            attempt = 0  # successful connect resets backoff counter

            # Wrap each message receive with a timeout so we detect a silent
            # dead channel (connected but no publishers) within 30 s.
            _stale_deadline = asyncio.get_event_loop().time() + _EVENTBUS_STALE_TIMEOUT_S
            async for msg in bus.subscribe(CH_TICK):
                _stale_deadline = asyncio.get_event_loop().time() + _EVENTBUS_STALE_TIMEOUT_S
                if _manager.connection_count == 0:
                    continue
                # Normalise to frontend PriceTick schema:
                # { type: "price_tick", data: PriceTick }

                # 1. Normalise symbol to slash format (XAU/USD, EUR/USD …)
                raw_symbol = msg.get("symbol", "XAU/USD")
                symbol = _SLASH_SYMBOL.get(raw_symbol, raw_symbol)

                # 2. Resolve mid from bid+ask or price field
                raw_bid = msg.get("bid")
                raw_ask = msg.get("ask")
                raw_price = msg.get("price") or msg.get("mid")

                if raw_bid is not None and raw_ask is not None:
                    bid = float(raw_bid)
                    ask = float(raw_ask)
                    mid = (bid + ask) / 2.0
                elif raw_price is not None:
                    # Derive bid/ask from price using per-symbol spread config
                    mid = float(raw_price)
                    cfg = _SYMBOLS.get(symbol, {})
                    half_spread = cfg.get("spread", mid * 0.0002) / 2
                    bid = round(mid - half_spread, 5)
                    ask = round(mid + half_spread, 5)
                else:
                    # No usable price — skip this message
                    logger.debug("_eventbus_tick_broadcaster: no price in msg for %s, skipping", symbol)
                    continue

                if mid <= 0:
                    continue

                spread = round(ask - bid, 5)

                # 3. Normalise timestamp to integer milliseconds
                raw_ts = msg.get("timestamp") or msg.get("ts")
                if raw_ts is None:
                    ts_ms = int(datetime.now(UTC).timestamp() * 1000)
                elif isinstance(raw_ts, str):
                    # ISO string → ms
                    try:
                        from datetime import datetime as _dt

                        ts_ms = int(_dt.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp() * 1000)
                    except Exception:
                        ts_ms = int(datetime.now(UTC).timestamp() * 1000)
                elif isinstance(raw_ts, float) and raw_ts < 1e12:
                    # Unix seconds → ms
                    ts_ms = int(raw_ts * 1000)
                else:
                    ts_ms = int(raw_ts)

                # 4. Track previous mid for change_pct calculation (lock prevents
                #    concurrent broadcaster tasks racing on the same symbol dict)
                with _last_mid_lock:
                    prev = _last_mid.get(symbol, mid)
                    _last_mid[symbol] = mid
                change = ((mid - prev) / prev * 100) if prev else 0.0

                tick_data = {
                    "symbol": symbol,
                    "bid": round(bid, 5),
                    "ask": round(ask, 5),
                    "mid": round(mid, 5),
                    "spread": spread,
                    "timestamp": ts_ms,
                    "change_pct": round(change, 4),
                }
                tick = {"type": "price_tick", "data": tick_data}
                await _manager.broadcast("prices", tick)
                # Also write tick:{symbol} so ws_public.py Redis fallback chain is populated.
                try:
                    from cache.redis_client import get_redis as _get_redis

                    _rc = await _get_redis()
                    if _rc is not None:
                        await _rc.setex(f"tick:{symbol}", 60, json.dumps(tick_data))
                except Exception:  # nosec B110 — non-fatal, fallback chain degrades gracefully
                    pass
        except Exception as exc:
            delay = _retry_delays[min(attempt, len(_retry_delays) - 1)]
            logger.warning(
                "WS live: EventBus tick stream failed (%s) — retrying in %ds (attempt %d).",
                exc,
                delay,
                attempt + 1,
            )
            attempt += 1
            await asyncio.sleep(delay)


def _atr_from_buffer(symbol: str) -> float | None:
    """Compute ATR(14) from the signal engine data buffer. Returns None on failure."""
    try:
        from core.signal_engine import _data_buffers  # type: ignore[attr-defined]
        import numpy as _np

        broker_sym = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
        buf = _data_buffers.get(broker_sym) or _data_buffers.get(symbol)
        if buf is not None and len(buf) >= 15:
            bars = list(buf)[-15:]
            highs = _np.array([b["high"] for b in bars], dtype=float)
            lows = _np.array([b["low"] for b in bars], dtype=float)
            closes = _np.array([b["close"] for b in bars], dtype=float)
            tr = _np.maximum(
                highs[1:] - lows[1:], _np.maximum(_np.abs(highs[1:] - closes[:-1]), _np.abs(lows[1:] - closes[:-1]))
            )
            if len(tr) >= 14:
                return float(_np.mean(tr[-14:]))
    except Exception as exc:
        logger.debug("_atr_from_buffer failed: %s", exc)
    return None


def _atr_from_csv(symbol: str) -> float | None:
    """Compute ATR(14) from H1 CSV file. Returns None on failure."""
    try:
        import pathlib
        import numpy as _np
        import pandas as _pd

        broker_sym = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
        csv_path = pathlib.Path(f"data/{broker_sym}_H1.csv")
        if not csv_path.exists():
            csv_path = pathlib.Path(f"data/{symbol.replace('/', '')}_H1.csv")
        if csv_path.exists():
            df = _pd.read_csv(csv_path, usecols=["high", "low", "close"]).tail(20)
            if len(df) >= 15:
                highs = df["high"].to_numpy(dtype=float)
                lows = df["low"].to_numpy(dtype=float)
                closes = df["close"].to_numpy(dtype=float)
                tr = _np.maximum(
                    highs[1:] - lows[1:], _np.maximum(_np.abs(highs[1:] - closes[:-1]), _np.abs(lows[1:] - closes[:-1]))
                )
                return float(_np.mean(tr[-14:]))
    except Exception as exc:
        logger.debug("_atr_from_csv failed: %s", exc)
    return None


def _compute_atr_sl_tp(
    symbol: str,
    mid: float,
    direction: str,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
) -> tuple[float | None, float | None]:
    """
    Compute ATR(14)-based stop-loss and take-profit prices.

    Resolution order:
    1. Recent H1 OHLCV from the signal engine data buffer
    2. Recent H1 CSV from data/<symbol>_H1.csv
    3. Percentage fallback (1.5% SL / 3.0% TP) when no price history available

    Returns (stop_loss, take_profit) rounded to 5 decimal places.
    sl_atr_mult and tp_atr_mult are read from env vars SL_ATR_MULT / TP_ATR_MULT
    at call time so they can be tuned without a restart.
    """
    sl_mult = float(os.getenv("SL_ATR_MULT", str(sl_atr_mult)))
    tp_mult = float(os.getenv("TP_ATR_MULT", str(tp_atr_mult)))

    atr: float | None = None

    # ── 1. Signal engine data buffer ─────────────────────────────────────────
    try:
        from core.signal_engine import _data_buffers  # type: ignore[attr-defined]  # pylint: disable=no-name-in-module

        broker_sym = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
        buf = _data_buffers.get(broker_sym) or _data_buffers.get(symbol)
        if buf is not None and len(buf) >= 15:
            import numpy as _np

            highs = _np.array([b["high"] for b in list(buf)[-15:]], dtype=float)
            lows = _np.array([b["low"] for b in list(buf)[-15:]], dtype=float)
            closes = _np.array([b["close"] for b in list(buf)[-15:]], dtype=float)
            tr = _np.maximum(
                highs[1:] - lows[1:],
                _np.maximum(
                    _np.abs(highs[1:] - closes[:-1]),
                    _np.abs(lows[1:] - closes[:-1]),
                ),
            )
            if len(tr) >= 14:
                atr = float(_np.mean(tr[-14:]))
    except Exception as exc:
        logger.debug(
            "_compute_sl_tp: signal engine ATR calc failed, trying CSV fallback: %s",
            exc,
        )

    # ── 2. CSV fallback ───────────────────────────────────────────────────────
    if atr is None:
        try:
            import pathlib

            import pandas as _pd

            broker_sym = _BROKER_KEY.get(symbol, symbol.replace("/", ""))
            csv_path = pathlib.Path(f"data/{broker_sym}_H1.csv")
            if not csv_path.exists():
                csv_path = pathlib.Path(f"data/{symbol.replace('/', '')}_H1.csv")
            if csv_path.exists():
                df = _pd.read_csv(csv_path, usecols=["high", "low", "close"]).tail(20)
                if len(df) >= 15:
                    highs = df["high"].to_numpy(dtype=float)
                    lows = df["low"].to_numpy(dtype=float)
                    closes = df["close"].to_numpy(dtype=float)
                    import numpy as _np

                    tr = _np.maximum(
                        highs[1:] - lows[1:],
                        _np.maximum(
                            _np.abs(highs[1:] - closes[:-1]),
                            _np.abs(lows[1:] - closes[:-1]),
                        ),
                    )
                    atr = float(_np.mean(tr[-14:]))
        except Exception as exc:
            logger.debug(
                "_compute_sl_tp: CSV ATR calc failed, using percentage fallback: %s",
                exc,
            )

    # ── 3. Percentage fallback ────────────────────────────────────────────────
    if atr is None or atr <= 0:
        atr = mid * 0.01  # 1% percentage fallback

    is_long = direction in ("long", "buy")
    if is_long:
        return round(mid - atr * sl_mult, 5), round(mid + atr * tp_mult, 5)
    return round(mid + atr * sl_mult, 5), round(mid - atr * tp_mult, 5)


async def _eventbus_signal_broadcaster() -> None:
    """
    Subscribe to hopefx:signal and forward signal_events to clients
    subscribed to the 'signals' channel.
    """
    try:
        from core.event_bus import CH_SIGNAL, bus

        await bus.connect()
        async for msg in bus.subscribe(CH_SIGNAL):
            if msg.get("type") != "signal_event":
                continue
            if _manager.connection_count == 0:
                continue
            # Normalise to the frontend WsMessage schema:
            # { type: "signal", data: Signal }
            direction_raw = (msg.get("direction") or "neutral").lower()
            direction_fe = "long" if direction_raw == "buy" else "short" if direction_raw == "sell" else "neutral"
            mid = msg.get("mid", 0.0)
            symbol = msg.get("symbol", "XAU/USD")

            # Use signal-engine-provided SL/TP when present; compute ATR-based
            # levels only when the upstream signal did not supply them.
            sl = msg.get("stop_loss")
            tp = msg.get("take_profit")
            if (sl is None or tp is None) and mid > 0 and direction_fe != "neutral":
                computed_sl, computed_tp = _compute_atr_sl_tp(symbol, mid, direction_fe)
                sl = sl if sl is not None else computed_sl
                tp = tp if tp is not None else computed_tp

            signal = {
                "type": "signal",
                "data": {
                    "id": f"sig_{msg.get('tick_seq', 0)}",
                    "symbol": symbol,
                    "direction": direction_fe,
                    "confidence": msg.get("confidence", 0.0),
                    "model": msg.get("model_version", "advanced_oos"),
                    "entry_price": mid,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "generated_at": msg.get("timestamp", ""),
                    "status": "active",
                },
            }
            await _manager.broadcast("signals", signal)
    except Exception as exc:
        logger.warning("WS live: EventBus signal stream failed: %s", exc)


async def _broadcast_no_live_feed() -> None:
    """
    Notify all connected clients that no live price feed is available.

    Sends a single status message then polls every 30 s, re-sending only
    while the feed remains disconnected.  When a live price becomes
    available the EventBus broadcaster will take over on the next restart.
    """
    _NO_FEED_INTERVAL = 30  # seconds between repeat notifications
    logger.warning("WS live: no live broker feed — GBM simulation disabled.")
    while True:
        if _manager.connection_count > 0:
            await _manager.broadcast(
                "prices",
                {
                    "type": "no_live_feed",
                    "message": ("No live broker connection. Connect a broker in Settings to receive real-time prices."),
                    "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                },
            )
        await asyncio.sleep(_NO_FEED_INTERVAL)


async def _price_broadcaster_live_only() -> None:
    """
    Poll live broker prices every second and broadcast real ticks.

    Used as a direct-poll fallback when the EventBus is unavailable but
    a broker is connected (e.g. paper broker with market_prices populated).

    Before sending no_live_feed for a symbol, checks _yf_last_prices — if
    yfinance has already fetched a price for that symbol we synthesize a tick
    from it rather than triggering the banner.  no_live_feed is only sent when
    both the broker AND yfinance have no price for a symbol.
    """
    _no_feed_warned: set[str] = set()
    # Give yfinance time to complete its first fetch before we start warning.
    # _yfinance_price_broadcaster runs concurrently and fetches immediately on
    # startup; 20 s is enough headroom even on a slow connection.
    _startup_grace_until = asyncio.get_running_loop().time() + 20
    while True:
        await asyncio.sleep(1)
        if _manager.connection_count == 0:
            continue
        # Re-seed from broker on every cycle until we have prices
        if not _prices_seeded:
            _seed_from_broker()
        any_live = False
        for symbol in _SYMBOLS:
            tick = _make_tick(symbol)
            if tick is not None:
                any_live = True
                _no_feed_warned.discard(symbol)
                await _manager.broadcast("prices", tick)
            else:
                # Level 5: use yfinance cache to synthesize a tick so the
                # no_live_feed banner is not shown when yfinance is working.
                yf_price = _yf_last_prices.get(symbol)
                if yf_price and yf_price > 0:
                    any_live = True
                    _no_feed_warned.discard(symbol)
                    cfg = _SYMBOLS.get(symbol, {})
                    spread = cfg.get("spread", yf_price * 0.0002)
                    prev = _open_prices.get(symbol, yf_price)
                    change_pct = ((yf_price - prev) / prev * 100) if prev > 0 else 0.0
                    await _manager.broadcast(
                        "prices",
                        {
                            "type": "price_tick",
                            "data": {
                                "symbol": symbol,
                                "bid": round(yf_price - spread / 2, 5),
                                "ask": round(yf_price + spread / 2, 5),
                                "mid": round(yf_price, 5),
                                "spread": spread,
                                "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                                "change_pct": round(change_pct, 4),
                            },
                        },
                    )
                elif symbol not in _no_feed_warned and asyncio.get_running_loop().time() > _startup_grace_until:
                    # Only warn after the grace period so we don't flash the
                    # banner during the initial yfinance fetch.
                    _no_feed_warned.add(symbol)
                    await _manager.broadcast(
                        "prices",
                        {
                            "type": "no_live_feed",
                            "symbol": symbol,
                            "message": (f"No live price for {symbol}. Connect a broker in Settings."),
                            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                        },
                    )
        if not any_live:
            # All symbols missing — slow down polling to avoid log spam
            await asyncio.sleep(9)


_YF_SYMBOL_MAP: dict[str, str] = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "BTC/USD": "BTC-USD",
}

# Cache last yfinance prices so we can broadcast change_pct correctly
_yf_last_prices: dict[str, float] = {}


async def _yfinance_price_broadcaster() -> None:
    """
    Broadcast real market prices fetched from yfinance every 15 seconds.

    Used when no broker or EventBus is available (API-only / dev mode).
    Sends genuine price_tick messages — no synthetic or mock data.

    Fetches immediately on startup (no initial sleep) so _yf_last_prices is
    populated before _price_broadcaster_live_only's grace period expires.
    """
    import time as _time

    _POLL_INTERVAL = 15  # seconds between yfinance fetches
    first_run = True

    while True:
        if first_run:
            first_run = False
            # Small yield so the event loop can start other tasks, then fetch.
            await asyncio.sleep(0.5)
        else:
            await asyncio.sleep(_POLL_INTERVAL)
        if _manager.connection_count == 0:
            continue
        try:
            import yfinance as _yf

            tickers = list(_YF_SYMBOL_MAP.values())
            data = await asyncio.wait_for(
                asyncio.to_thread(
                    _yf.download,
                    tickers,
                    period="1d",
                    interval="1m",
                    progress=False,
                    auto_adjust=True,
                ),
                timeout=12.0,
            )
            now_ms = int(_time.time() * 1000)
            for ws_sym, yf_ticker in _YF_SYMBOL_MAP.items():
                try:
                    if hasattr(data.columns, "levels"):
                        col = ("Close", yf_ticker)
                        if col not in data.columns:
                            continue
                        series = data[col].dropna()
                    else:
                        series = data["Close"].dropna()
                    if series.empty:
                        continue
                    price = float(series.iloc[-1])
                    if price <= 0:
                        continue
                    cfg = _SYMBOLS.get(ws_sym, {"spread": price * 0.0002})
                    spread = cfg.get("spread", price * 0.0002)
                    prev = _yf_last_prices.get(ws_sym, price)
                    change_pct = ((price - prev) / prev * 100) if prev > 0 else 0.0
                    _yf_last_prices[ws_sym] = price
                    tick = {
                        "type": "price_tick",
                        "data": {
                            "symbol": ws_sym,
                            "bid": round(price - spread / 2, 5),
                            "ask": round(price + spread / 2, 5),
                            "mid": round(price, 5),
                            "spread": spread,
                            "timestamp": now_ms,
                            "change_pct": round(change_pct, 4),
                        },
                    }
                    await _manager.broadcast("prices", tick)
                except Exception as _sym_exc:
                    logger.debug("yfinance tick for %s failed: %s", ws_sym, _sym_exc)
        except Exception as exc:
            logger.warning("yfinance price broadcaster error: %s", exc)


async def _price_broadcaster() -> None:
    """
    Broadcast price ticks.

    Runs three concurrent tasks:
    1. EventBus (hopefx:tick) — forwards real ticks from the multi-source feed
       when Redis pub/sub is active.  Silently idle when no publisher is present.
    2. yfinance poller        — fetches real market prices every 15 s and
       broadcasts ticks for all symbols.  Ensures the dashboard always has live
       prices even when the EventBus feed is silent (no API keys configured).
    3. Direct broker poll     — polls paper broker market_prices every second
       and broadcasts ticks; sends no_live_feed per-symbol only when both the
       broker AND yfinance have no price.

    All three run concurrently so yfinance prices are always flowing regardless
    of EventBus state.
    """
    await asyncio.gather(
        _eventbus_tick_broadcaster(),
        _price_broadcaster_live_only(),
        _yfinance_price_broadcaster(),
        return_exceptions=True,
    )


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
            await _manager.send(cid, {"type": "heartbeat"})
            if cid not in _manager._connections:
                # send() already called disconnect() on failure — skip
                continue
            misses = _manager.record_hb_miss(cid)
            if misses > HEARTBEAT_MISS_LIMIT:
                logger.info("WS closing stale connection %s (missed %d heartbeats)", cid, misses)
                dead.append(cid)
        for cid in dead:
            ws = _manager._connections.get(cid)
            if ws:
                try:
                    await ws.close(code=1001, reason="heartbeat timeout")
                except Exception as exc:
                    logger.debug(
                        "_heartbeat_broadcaster: error closing stale connection %s: %s",
                        cid,
                        exc,
                    )
            _manager.disconnect(cid)


_CHARTBOT_POLL_INTERVAL: float = float(os.getenv("WS_CHARTBOT_POLL_INTERVAL", "5"))


async def _chartbot_broadcaster() -> None:
    """
    Poll data-layer endpoints every WS_CHARTBOT_POLL_INTERVAL seconds and
    broadcast chart-bot specific message types to subscribed clients.

    Channels served:
      microstructure  → { type: "microstructure",   data: MicrostructureSnapshot }
      volume_delta    → { type: "volume_delta",      data: VolumeDeltaBar }
      sentiment       → { type: "sentiment_update",  data: { signal: SentimentSignal, recent_articles: NewsArticle[] } }
      risk            → { type: "risk_update",       data: RiskSnapshot }
      equity          → { type: "equity_update",     data: EquitySnapshot }
      news            → { type: "news_item",         data: NewsArticle }

    SentimentSignal fields (from data_layer.sentiment.engine):
      news_sentiment_score    : float  — EMA of article sentiment scores [-1, 1]
      news_sentiment_momentum : float  — rate of change of sentiment EMA
      news_article_count_1h   : float  — gold-relevant articles in last hour
      news_bullish_ratio      : float  — fraction of recent articles that are bullish [0, 1]
    """
    while True:
        await asyncio.sleep(_CHARTBOT_POLL_INTERVAL)
        try:
            from data_layer.orchestrator import orchestrator as _orch

            # ── microstructure + volume_delta ─────────────────────────────────
            try:
                snap = _orch.get_microstructure_snapshot()
                if snap is not None:
                    micro_data = {
                        "timestamp": snap.timestamp.isoformat(),
                        "bid": snap.bid,
                        "ask": snap.ask,
                        "spread": snap.spread,
                        "spread_pct": snap.spread_pct,
                        "volume_delta": snap.volume_delta,
                        "cumulative_delta": snap.cumulative_delta,
                        "buy_pressure": snap.buy_pressure,
                        "sell_pressure": snap.sell_pressure,
                        "order_flow_imbalance": snap.order_flow_imbalance,
                        "trade_pressure": snap.trade_pressure,
                        "vwap": snap.vwap,
                        "tick_count": snap.tick_count,
                    }
                    await _manager.broadcast("microstructure", {"type": "microstructure", "data": micro_data})
                    await _manager.broadcast(
                        "volume_delta",
                        {
                            "type": "volume_delta",
                            "data": {
                                "volume_delta": snap.volume_delta,
                                "cumulative_delta": snap.cumulative_delta,
                                "timestamp": snap.timestamp.isoformat(),
                            },
                        },
                    )
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: microstructure error: %s", _exc)

            # ── sentiment ─────────────────────────────────────────────────────
            try:
                sentiment_snap = _orch.get_sentiment_snapshot()
                if sentiment_snap is not None:
                    await _manager.broadcast(
                        "sentiment",
                        {"type": "sentiment_update", "data": sentiment_snap},
                    )
                    for article in (sentiment_snap.get("recent_articles") or [])[:3]:
                        await _manager.broadcast("news", {"type": "news_item", "data": article})
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: sentiment error: %s", _exc)

            # ── risk snapshot ─────────────────────────────────────────────────
            try:
                from core.app_state import app_state as _app_state

                rm = getattr(_app_state, "risk_manager", None) if _app_state else None
                if rm is not None:
                    risk_data: dict = {}
                    for attr in ("daily_loss_pct", "max_drawdown_pct", "open_risk_pct", "kill_switch_active"):
                        val = getattr(rm, attr, None)
                        if val is not None:
                            risk_data[attr] = val
                    if risk_data:
                        await _manager.broadcast("risk", {"type": "risk_update", "data": risk_data})
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: risk error: %s", _exc)

            # ── equity snapshot ───────────────────────────────────────────────
            try:
                from core.app_state import app_state as _app_state

                broker = getattr(_app_state, "broker", None) if _app_state else None
                if broker is not None:
                    _acct_coro = broker.get_account_info()
                    acct = await _acct_coro if asyncio.iscoroutine(_acct_coro) else _acct_coro
                    if acct:
                        await _manager.broadcast(
                            "equity",
                            {
                                "type": "equity_update",
                                "data": {
                                    "balance": acct.get("balance", 0.0),
                                    "equity": acct.get("equity", 0.0),
                                    "unrealized_pnl": acct.get("unrealized_pnl", 0.0),
                                    "margin_used": acct.get("margin_used", 0.0),
                                    "timestamp": datetime.now(UTC).isoformat(),
                                },
                            },
                        )
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: equity error: %s", _exc)

            # ── AI analysis broadcast (from Redis cache) ──────────────────────
            # The /trading/ai-analysis REST endpoint caches its result in Redis
            # under "ai_analysis:{symbol}". We broadcast it so chart-bot clients
            # receive updates without polling.
            try:
                from cache.redis_client import get_sync_redis_client as _get_rc
                import json as _json

                _rc = _get_rc()
                if _rc:
                    for _sym in ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD"):
                        _raw = _rc.get(f"ai_analysis:{_sym}")
                        if _raw:
                            _analysis = _json.loads(_raw)
                            await _manager.broadcast(
                                "prices",
                                {"type": "ai_analysis", "data": _analysis},
                            )
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: ai_analysis error: %s", _exc)

            # ── Pattern detection broadcast ───────────────────────────────────
            try:
                from cache.redis_client import get_sync_redis_client as _get_rc2
                import json as _json2

                _rc2 = _get_rc2()
                if _rc2:
                    _praw = _rc2.get("chart_patterns:latest")
                    if _praw:
                        _patterns = _json2.loads(_praw)
                        for _pat in (_patterns if isinstance(_patterns, list) else [_patterns])[:3]:
                            await _manager.broadcast(
                                "patterns",
                                {"type": "pattern_detected", "data": _pat},
                            )
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: patterns error: %s", _exc)

            # ── Support/resistance level updates ──────────────────────────────
            try:
                from cache.redis_client import get_sync_redis_client as _get_rc3
                import json as _json3

                _rc3 = _get_rc3()
                if _rc3:
                    _lraw = _rc3.get("sr_levels:latest")
                    if _lraw:
                        _levels = _json3.loads(_lraw)
                        await _manager.broadcast(
                            "levels",
                            {"type": "level_update", "data": _levels},
                        )
            except Exception as _exc:
                logger.debug("chartbot_broadcaster: levels error: %s", _exc)

        except Exception as exc:
            logger.debug("chartbot_broadcaster: outer error: %s", exc)


async def _account_update_broadcaster() -> None:
    """
    Push account_update messages to clients subscribed to the 'account' channel.

    Polls the broker every 5 seconds and broadcasts the full AccountMetrics
    shape that the frontend store expects. Falls back gracefully when the
    broker is not yet initialised.
    """
    _POLL_INTERVAL = 5  # seconds
    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        if _manager.connection_count == 0:
            continue
        try:
            from core.app_state import app_state as _app_state  # type: ignore[import]

            broker = getattr(_app_state, "broker", None) if _app_state else None
            if broker is None:
                continue

            _acct_coro = broker.get_account_info()
            acct_raw = await _acct_coro if asyncio.iscoroutine(_acct_coro) else _acct_coro
            if not acct_raw:
                continue

            # Normalise to the AccountMetrics shape the frontend store expects.
            # acct_raw may be an AccountInfo dataclass or a dict — handle both.
            def _acct_get(key: str, default=0.0):
                if hasattr(acct_raw, key):
                    return getattr(acct_raw, key) or default
                if isinstance(acct_raw, dict):
                    return acct_raw.get(key, default) or default
                return default

            balance = float(_acct_get("balance", 0.0))
            equity = float(_acct_get("equity", balance))
            margin_used = float(_acct_get("margin_used", 0.0))
            margin_free = float(_acct_get("margin_free", equity - margin_used))
            # When margin_used == 0 there are no open positions, so margin level
            # is effectively infinite (no risk). Use 9999.0 as a sentinel so the
            # frontend RiskDashboard does not interpret 0.0 as a margin call.
            # This is the canonical fix for the original bug report (margin_level=0.0).
            margin_level = (equity / margin_used * 100) if margin_used > 0 else 9999.0
            daily_pnl = float(_acct_get("daily_pnl", _acct_get("unrealized_pnl", 0.0)))
            daily_pnl_pct = (daily_pnl / balance * 100) if balance > 0 else 0.0
            total_pnl = float(_acct_get("total_pnl", _acct_get("realized_pnl", 0.0)))

            # Risk manager stats (optional)
            rm = getattr(_app_state, "risk_manager", None) if _app_state else None
            win_rate = float(getattr(rm, "win_rate", 0.0) or 0.0)
            sharpe = float(getattr(rm, "sharpe_ratio", 0.0) or 0.0)
            max_dd = float(getattr(rm, "max_drawdown_pct", 0.0) or 0.0)

            # Open trade count from positions
            _pos_coro = broker.get_positions() if hasattr(broker, "get_positions") else []
            positions = await _pos_coro if asyncio.iscoroutine(_pos_coro) else _pos_coro
            open_trades = len(positions) if positions else int(_acct_get("open_trades", 0))

            account_msg = {
                "type": "account_update",
                "data": {
                    "balance": balance,
                    "equity": equity,
                    "margin_used": margin_used,
                    "margin_free": margin_free,
                    "margin_level": round(margin_level, 2),
                    "daily_pnl": round(daily_pnl, 2),
                    "daily_pnl_pct": round(daily_pnl_pct, 4),
                    "total_pnl": round(total_pnl, 2),
                    "win_rate": round(win_rate, 2),
                    "sharpe_ratio": round(sharpe, 4),
                    "max_drawdown": round(max_dd, 4),
                    "open_trades": open_trades,
                },
            }
            await _manager.broadcast("account", account_msg)
        except Exception as exc:
            logger.debug("account_update_broadcaster: %s", exc)


# Broadcaster specs at module level so the restart callback can look them up.
_BROADCASTER_SPECS: list[tuple[str, Any]] = []

# Strong references to broadcaster tasks so they are not garbage-collected.
_broadcaster_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]


def _broadcaster_done_callback(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Restart any broadcaster that exits unexpectedly."""
    name = task.get_name()
    if task.cancelled():
        logger.debug("WS broadcaster task %r was cancelled", name)
        return

    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("WS broadcaster task %r crashed: %s — restarting", name, exc, exc_info=exc)
    else:
        logger.warning("WS broadcaster task %r exited cleanly — restarting", name)

    for spec_name, coro_fn in _BROADCASTER_SPECS:
        if spec_name == name:
            try:
                loop = asyncio.get_running_loop()
                new_task = loop.create_task(coro_fn(), name=spec_name)
                new_task.add_done_callback(_broadcaster_done_callback)
                _broadcaster_tasks[:] = [t for t in _broadcaster_tasks if t.get_name() != spec_name]
                _broadcaster_tasks.append(new_task)
                logger.info("WS broadcaster %r restarted successfully", spec_name)
            except Exception as restart_exc:
                logger.error("WS broadcaster %r restart failed: %s", spec_name, restart_exc)
            break


def start_broadcasters() -> None:
    """Start background tasks (call once from app lifespan)."""
    global _broadcaster_tasks, _BROADCASTER_SPECS
    loop = asyncio.get_running_loop()

    _BROADCASTER_SPECS = [
        ("price_broadcaster", _price_broadcaster),
        ("heartbeat_broadcaster", _heartbeat_broadcaster),
        ("signal_broadcaster", _eventbus_signal_broadcaster),
        ("chartbot_broadcaster", _chartbot_broadcaster),
        ("account_update_broadcaster", _account_update_broadcaster),
    ]

    _broadcaster_tasks = []
    for name, coro_fn in _BROADCASTER_SPECS:
        task = loop.create_task(coro_fn(), name=name)
        task.add_done_callback(_broadcaster_done_callback)
        _broadcaster_tasks.append(task)

    logger.info("WS live broadcasters started (price → account → signal → heartbeat → chart-bot)")


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """
        Main live WebSocket endpoint.

        Auth flow:
          1. Server accepts connection and sends { "type": "connected" }
    async def _ws_auth_gate(cid: str, websocket: WebSocket) -> bool:
             within AUTH_TIMEOUT_SECONDS, or connection is closed (4001).
          3. Server sends { "type": "auth_ok", "user_id": "..." }
          4. Client subscribes to channels and receives live data.

        Heartbeat:
          Server sends { "type": "heartbeat" } every HEARTBEAT_INTERVAL_SECONDS.
          Client should respond with { "type": "ping" } to reset the miss counter.
          After HEARTBEAT_MISS_LIMIT missed heartbeats the connection is closed (1001).

        Rate limiting:
          Max WS_MAX_CONNECTIONS_PER_IP concurrent connections per IP (default 10).
          Max WS_MAX_CONNECTIONS_PER_MINUTE new connections per IP per minute (default 20).
          Excess connections are rejected with close code 1008 before accept().
    """
    from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

    limiter = get_ws_limiter()
    client_ip = get_client_ip(websocket)

    allowed, reason = await limiter.check_and_register(websocket, client_ip)
    if not allowed:
        return

    cid = await _manager.connect(websocket)

    await _manager.send(
        cid,
        {
            "type": "connected",
            "connection_id": cid,
            "auth_required": WS_AUTH_REQUIRED,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    if WS_AUTH_REQUIRED:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
            msg = json.loads(raw)
            if msg.get("type") != "auth":
                await _manager.send(
                    cid,
                    {
                        "type": "error",
                        "code": "AUTH_REQUIRED",
                        "message": "First message must be {type: auth, token: ...}",
                    },
                )
                await _safe_ws_close(websocket, code=4001)
                _manager.disconnect(cid)
                return

            payload = _validate_ws_token(msg.get("token", ""))
            if payload is None:
                await _manager.send(
                    cid,
                    {
                        "type": "error",
                        "code": "AUTH_FAILED",
                        "message": "Invalid or expired token",
                    },
                )
                await _safe_ws_close(websocket, code=4001)
                _manager.disconnect(cid)
                return

            # Register the authenticated user and notify the client.
            user_id = str(payload.get("sub", payload.get("user_id", "unknown")))
            _manager.authenticate(cid, user_id)
            await _manager.send(
                cid,
                {
                    "type": "auth_ok",
                    "user_id": user_id,
                    "role": payload.get("role", "trader"),
                },
            )
        except TimeoutError:
            await _manager.send(
                cid,
                {
                    "type": "error",
                    "code": "AUTH_TIMEOUT",
                    "message": f"Auth required within {AUTH_TIMEOUT_SECONDS}s",
                },
            )
            await _safe_ws_close(websocket, code=4001)
            _manager.disconnect(cid)
            return
        except Exception:
            _manager.disconnect(cid)
            return
    else:
        # Auth not required — mark connection as authenticated with a dev user_id
        # so broadcast() delivers messages to this connection on all channels.
        _manager.authenticate(cid, "dev_anonymous")

    try:
        await _ws_message_loop(cid, websocket)
    finally:
        from rate_limiting.websocket_limiter import get_ws_limiter, get_client_ip

        await get_ws_limiter().release(get_client_ip(websocket))


async def _ws_auth_gate(cid: str, websocket: Any) -> bool:
    """Perform the initial auth handshake. Returns True if authenticated."""
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        msg = json.loads(raw)
        if msg.get("type") != "auth":
            await _manager.send(
                cid,
                {"type": "error", "code": "AUTH_REQUIRED", "message": "First message must be {type: auth, token: ...}"},
            )
            await _safe_ws_close(websocket, code=4001)
            _manager.disconnect(cid)
            return False
        payload = _validate_ws_token(msg.get("token", ""))
        if payload is None:
            await _manager.send(cid, {"type": "error", "code": "AUTH_FAILED", "message": "Invalid or expired token"})
            await _safe_ws_close(websocket, code=4001)
            _manager.disconnect(cid)
            return False
        user_id = str(payload.get("sub", payload.get("user_id", "unknown")))
        _manager.authenticate(cid, user_id)
        await _manager.send(cid, {"type": "auth_ok", "user_id": user_id, "role": payload.get("role", "trader")})
        return True
    except TimeoutError:
        await _manager.send(
            cid, {"type": "error", "code": "AUTH_TIMEOUT", "message": f"Auth required within {AUTH_TIMEOUT_SECONDS}s"}
        )
        await _safe_ws_close(websocket, code=4001)
        _manager.disconnect(cid)
        return False
    except (WebSocketDisconnect, Exception) as exc:
        logger.debug("WS auth phase error [%s]: %s", cid, exc)
        _manager.disconnect(cid)
        return False


async def _ws_handle_message(cid: str, msg: dict) -> None:
    """Dispatch a single parsed WebSocket message."""
    msg_type = msg.get("type", "")
    if msg_type == "subscribe":
        channels = msg.get("channels", [])
        _manager.subscribe(cid, channels)
        await _manager.send(cid, {"type": "subscribed", "channels": channels})
    elif msg_type == "unsubscribe":
        channels = msg.get("channels", [])
        _manager.unsubscribe(cid, channels)
        await _manager.send(cid, {"type": "unsubscribed", "channels": channels})
    elif msg_type == "ping":
        _manager.record_pong(cid)
        await _manager.send(cid, {"type": "pong"})
    elif msg_type == "auth":
        # FIX: block re-authentication after the connection is already authenticated.
        # Allowing re-auth mid-session lets a connected user escalate to a different
        # user_id by sending a second auth message with a different token.
        if _manager.is_authenticated(cid):
            await _manager.send(
                cid,
                {
                    "type": "error",
                    "code": "ALREADY_AUTHENTICATED",
                    "message": "Connection is already authenticated; re-auth is not permitted",
                },
            )
        else:
            payload = _validate_ws_token(msg.get("token", ""))
            if payload:
                user_id = str(payload.get("sub", "unknown"))
                _manager.authenticate(cid, user_id)
                await _manager.send(cid, {"type": "auth_ok", "user_id": user_id})
            else:
                await _manager.send(
                    cid, {"type": "error", "code": "AUTH_FAILED", "message": "Invalid or expired token"}
                )
    else:
        await _manager.send(
            cid, {"type": "error", "code": "UNKNOWN_MESSAGE_TYPE", "message": f"Unknown message type: {msg_type}"}
        )


async def _ws_message_loop(cid: str, websocket: Any) -> None:
    """Run the main receive loop for a WebSocket connection."""
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _manager.send(
                    cid, {"type": "error", "code": "INVALID_JSON", "message": "Message must be valid JSON"}
                )
                continue
            await _ws_handle_message(cid, msg)
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
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ─── Push helpers (called from trading/signal routers) ───────────────────────


async def push_position_update(position: dict, user_id: str | None = None) -> None:
    """Push a position update. If user_id is given, only that user receives it."""
    msg = {"type": "position_update", "data": position}
    if user_id:
        await _manager.send_to_user(user_id, "positions", msg)
    else:
        await _manager.broadcast("positions", msg)


async def push_position_close(position_id: str, user_id: str | None = None) -> None:
    msg = {"type": "position_close", "data": {"id": position_id}}
    if user_id:
        await _manager.send_to_user(user_id, "positions", msg)
    else:
        await _manager.broadcast("positions", msg)


async def push_signal(signal: dict) -> None:
    """Signals are broadcast to all subscribers (not user-specific)."""
    await _manager.broadcast("signals", {"type": "signal", "data": signal})
    # Also forward to /ws/social-feed subscribers
    try:
        from api.social_feed import _social_feed_broadcast as _sf_broadcast

        await _sf_broadcast(signal)
    except Exception:  # nosec B110
        pass


async def push_account_update(account: dict, user_id: str | None = None) -> None:
    """Account updates are per-user — equity/balance is private."""
    msg = {"type": "account_update", "data": account}
    if user_id:
        await _manager.send_to_user(user_id, "account", msg)
    else:
        await _manager.broadcast("account", msg)


async def push_alert(alert: dict, user_id: str) -> None:
    """Price alerts are always per-user."""
    await _manager.send_to_user(
        user_id,
        "alerts",
        {
            "type": "alert_triggered",
            "data": alert,
        },
    )


# ─── /ws/nuclear ─────────────────────────────────────────────────────────────
# Nuclear dashboard WebSocket endpoint.
# Frontend useNuclearWS hook connects here and expects:
#   nuclear_chart_update  — periodic NuclearState snapshot
#   nuclear_alert         — severity >= 7 event
#   nuclear_resume        — trading resumed after halt
#   heartbeat             — 30s keepalive

_NUCLEAR_HEARTBEAT_INTERVAL = 30  # seconds
_NUCLEAR_POLL_INTERVAL = 2  # seconds between state snapshots


@router.websocket("/ws/nuclear")
async def ws_nuclear(websocket: WebSocket) -> None:
    """
    Nuclear dashboard real-time feed.

    Auth: JWT bearer token sent as { type: 'auth', token: 'Bearer <jwt>' }
    immediately after connect, matching the same handshake as /ws/live.

    Outbound message types:
      connected            — initial handshake
      auth_ok              — auth accepted
      nuclear_chart_update — NuclearState snapshot every 2s
      nuclear_alert        — severity >= 7 event
      nuclear_resume       — trading resumed
      heartbeat            — 30s keepalive
      error                — auth failure or server error
    """
    await websocket.accept()
    await websocket.send_text(json.dumps({"type": "connected", "auth_required": True}))

    # ── Auth gate ─────────────────────────────────────────────────────────────
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError):
        await _safe_ws_close(websocket, code=4001, reason="auth_timeout")
        return
    except WebSocketDisconnect:
        return

    if msg.get("type") != "auth":
        await websocket.send_text(json.dumps({"type": "error", "code": "AUTH_REQUIRED"}))
        await _safe_ws_close(websocket, code=4001)
        return

    payload = _validate_ws_token(msg.get("token", ""))
    if not payload:
        await websocket.send_text(
            json.dumps({"type": "error", "code": "AUTH_FAILED", "message": "Invalid or expired token"})
        )
        await _safe_ws_close(websocket, code=4001)
        return

    user_id = str(payload.get("sub", "unknown"))
    await websocket.send_text(json.dumps({"type": "auth_ok", "user_id": user_id}))

    # ── Nuclear availability check ────────────────────────────────────────────
    # If the charting engine failed to load at startup, tell the client
    # immediately instead of silently streaming null state every 2 seconds.
    try:
        from app import app as _app

        _nuclear_ok = getattr(_app.state, "nuclear_available", True)
    except Exception:
        _nuclear_ok = True  # assume available if we can't check

    if not _nuclear_ok:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "nuclear_unavailable",
                    "message": "Nuclear engine did not load at startup — check server logs.",
                }
            )
        )
        await _safe_ws_close(websocket, code=1001)
        return

    # ── Stream loop ───────────────────────────────────────────────────────────
    last_heartbeat = asyncio.get_running_loop().time()
    last_severity = -1

    async def _send(data: dict) -> bool:
        try:
            await websocket.send_text(json.dumps(data))
            return True
        except Exception:
            return False

    def _get_nuclear_state() -> dict | None:
        try:
            from brain.nuclear_supervisor import get_nuclear_supervisor as _get_sup
            from risk.orchestrator import risk_orchestrator as _orch_singleton

            sup = _get_sup()
            sup_status = sup.get_status() if sup else {}
            orch_status = _orch_singleton.get_status() if _orch_singleton else {}
            return {
                "severity": sup_status.get("nuclear_level", 0),
                "action": sup_status.get("action", "normal"),
                "nuclear_level": sup_status.get("nuclear_level", 0),
                "trading_paused": sup_status.get("trading_paused", False),
                "rl_action": sup_status.get("rl_action", 0),
                "rl_action_label": sup_status.get("rl_action_label", "NORMAL"),
                "rl_agent_loaded": sup_status.get("rl_agent_loaded", False),
                "confidence": sup_status.get("confidence", 0.0),
                "raw_score": sup_status.get("raw_score", 0.0),
                "matched_terms": sup_status.get("matched_terms", []),
                "category_scores": sup_status.get("category_scores", {}),
                "vol_factor": sup_status.get("vol_factor", 1.0),
                "sentiment_factor": sup_status.get("sentiment_factor", 0.0),
                "explanation": sup_status.get("explanation", ""),
                "alert_active": sup_status.get("alert_active", False),
                "historical_analog": sup_status.get("historical_analog"),
                "cooldown_remaining": sup_status.get("cooldown_remaining", 0),
                "event_count": sup_status.get("event_count", 0),
                "hedge_active": orch_status.get("hedge_active", False),
                "max_risk_fraction": orch_status.get("max_risk_fraction", 1.0),
            }
        except Exception as exc:
            logger.debug("ws_nuclear: state fetch failed: %s", exc)
            return None

    try:
        while True:
            now = asyncio.get_running_loop().time()

            # Heartbeat
            if now - last_heartbeat >= _NUCLEAR_HEARTBEAT_INTERVAL:
                if not await _send({"type": "heartbeat", "ts": datetime.now(UTC).isoformat()}):
                    break
                last_heartbeat = now

            # State snapshot
            state = _get_nuclear_state()
            if state is not None:
                if not await _send({"type": "nuclear_chart_update", "data": state}):
                    break

                # Alert if severity crossed threshold
                severity = state.get("severity", 0)
                if (
                    severity >= 7
                    and last_severity < 7
                    and not await _send(
                        {
                            "type": "nuclear_alert",
                            "data": {
                                "severity": severity,
                                "action": state.get("action"),
                                "explanation": state.get("explanation", ""),
                                "ts": datetime.now(UTC).isoformat(),
                            },
                        }
                    )
                ):
                    break

                # Resume notification
                if (
                    last_severity >= 7
                    and severity < 7
                    and not await _send({"type": "nuclear_resume", "data": {"ts": datetime.now(UTC).isoformat()}})
                ):
                    break

                last_severity = severity

            # Drain any inbound messages (subscribe/ping) without blocking
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=_NUCLEAR_POLL_INTERVAL)
                inbound = json.loads(raw)
                if inbound.get("type") == "ping":
                    await _send({"type": "pong"})
            except TimeoutError:  # nosec B110 — poll timeout is expected; loop continues
                pass
            except (WebSocketDisconnect, json.JSONDecodeError):  # nosec B110 — client disconnect ends loop
                break

    except WebSocketDisconnect:  # nosec B110 — normal client disconnect; no action needed
        pass
    except Exception as exc:
        logger.error("ws_nuclear error for user %s: %s", user_id, exc)
    finally:
        logger.debug("ws_nuclear: disconnected user=%s", user_id)


async def broadcast_system_event(event: dict) -> None:
    """Broadcast a system-level event to all connected WebSocket clients.

    Used by superadmin endpoints (e.g. nuclear halt, maintenance mode).

    Args:
        event: dict payload to broadcast — should include a ``type`` key.
    """
    await _manager.broadcast("system", event)


# ─── /ws/notifications ────────────────────────────────────────────────────────

@router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket) -> None:
    """
    Real-time notification push channel.

    Auth: JWT token passed as query param ?token=<jwt> or as
    { type: 'auth', token: 'Bearer <jwt>' } message after connect.

    Outbound message types:
      connected      — initial handshake
      auth_ok        — auth accepted
      notification   — new notification payload
      heartbeat      — 30s keepalive
      error          — auth failure
    """
    await websocket.accept()
    await websocket.send_text(json.dumps({"type": "connected", "auth_required": True}))

    # Support token as query param (simpler for some clients)
    token_param = websocket.query_params.get("token", "")
    payload = _validate_ws_token(token_param) if token_param else None

    if not payload:
        # Fall back to auth message handshake
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
            msg = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError):
            await _safe_ws_close(websocket, code=4001, reason="auth_timeout")
            return
        except WebSocketDisconnect:
            return

        if msg.get("type") != "auth":
            await websocket.send_text(json.dumps({"type": "error", "code": "AUTH_REQUIRED"}))
            await _safe_ws_close(websocket, code=4001)
            return

        payload = _validate_ws_token(msg.get("token", ""))
        if not payload:
            await websocket.send_text(
                json.dumps({"type": "error", "code": "AUTH_FAILED", "message": "Invalid or expired token"})
            )
            await _safe_ws_close(websocket, code=4001)
            return

    user_id = str(payload.get("sub", "unknown"))
    await websocket.send_text(json.dumps({"type": "auth_ok", "user_id": user_id}))

    # Subscribe to Redis pub/sub channel for this user's notifications
    _NOTIF_CHANNEL = f"hopefx:notif:push:{user_id}"
    last_heartbeat = asyncio.get_running_loop().time()

    try:
        import redis.asyncio as aioredis
        import os

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        # Strip password from dev URL if empty
        r = aioredis.from_url(redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(_NOTIF_CHANNEL)

        try:
            while True:
                now = asyncio.get_running_loop().time()

                # Heartbeat
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    try:
                        await websocket.send_text(json.dumps({"type": "heartbeat"}))
                    except Exception:
                        break
                    last_heartbeat = now

                # Poll Redis for new notifications
                try:
                    message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=2.0)
                    if message and message.get("type") == "message":
                        try:
                            data = json.loads(message["data"])
                            await websocket.send_text(json.dumps({"type": "notification", "data": data}))
                        except Exception:  # nosec B110
                            pass
                except TimeoutError:  # nosec B110
                    pass
                except WebSocketDisconnect:
                    break

        finally:
            await pubsub.unsubscribe(_NOTIF_CHANNEL)
            await r.aclose()

    except Exception:
        # Redis unavailable — fall back to heartbeat-only loop
        try:
            while True:
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    try:
                        await websocket.send_text(json.dumps({"type": "heartbeat"}))
                    except Exception:
                        break
                    last_heartbeat = now
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                except TimeoutError:  # nosec B110
                    pass
                except WebSocketDisconnect:
                    break
        except WebSocketDisconnect:  # nosec B110
            pass
    finally:
        logger.debug("ws_notifications: disconnected user=%s", user_id)


# ─── /ws/audit-events ─────────────────────────────────────────────────────────

@router.websocket("/ws/audit-events")
async def ws_audit_events(websocket: WebSocket) -> None:
    """
    Real-time audit event stream (admin/superadmin only).

    Auth: JWT token passed as query param ?token=<jwt> or as
    { type: 'auth', token: 'Bearer <jwt>' } message after connect.

    Outbound message types:
      connected    — initial handshake
      auth_ok      — auth accepted
      audit_event  — new audit log entry
      heartbeat    — 30s keepalive
      error        — auth failure or insufficient role
    """
    await websocket.accept()
    await websocket.send_text(json.dumps({"type": "connected", "auth_required": True}))

    # Support token as query param
    token_param = websocket.query_params.get("token", "")
    payload = _validate_ws_token(token_param) if token_param else None

    if not payload:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
            msg = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError):
            await _safe_ws_close(websocket, code=4001, reason="auth_timeout")
            return
        except WebSocketDisconnect:
            return

        if msg.get("type") != "auth":
            await websocket.send_text(json.dumps({"type": "error", "code": "AUTH_REQUIRED"}))
            await _safe_ws_close(websocket, code=4001)
            return

        payload = _validate_ws_token(msg.get("token", ""))
        if not payload:
            await websocket.send_text(
                json.dumps({"type": "error", "code": "AUTH_FAILED", "message": "Invalid or expired token"})
            )
            await _safe_ws_close(websocket, code=4001)
            return

    user_id = str(payload.get("sub", "unknown"))
    role = str(payload.get("role", ""))

    # Restrict to admin and superadmin roles
    if role not in ("admin", "superadmin"):
        await websocket.send_text(
            json.dumps({"type": "error", "code": "FORBIDDEN", "message": "Admin role required"})
        )
        await _safe_ws_close(websocket, code=4003)
        return

    await websocket.send_text(json.dumps({"type": "auth_ok", "user_id": user_id, "role": role}))

    _AUDIT_CHANNEL = "hopefx:audit:events"
    last_heartbeat = asyncio.get_running_loop().time()

    try:
        import redis.asyncio as aioredis
        import os

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(_AUDIT_CHANNEL)

        try:
            while True:
                now = asyncio.get_running_loop().time()

                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    try:
                        await websocket.send_text(json.dumps({"type": "heartbeat"}))
                    except Exception:
                        break
                    last_heartbeat = now

                try:
                    message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=2.0)
                    if message and message.get("type") == "message":
                        try:
                            data = json.loads(message["data"])
                            await websocket.send_text(json.dumps({"type": "audit_event", "data": data}))
                        except Exception:  # nosec B110
                            pass
                except TimeoutError:  # nosec B110
                    pass
                except WebSocketDisconnect:
                    break

        finally:
            await pubsub.unsubscribe(_AUDIT_CHANNEL)
            await r.aclose()

    except Exception:
        # Redis unavailable — heartbeat-only loop
        try:
            while True:
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    try:
                        await websocket.send_text(json.dumps({"type": "heartbeat"}))
                    except Exception:
                        break
                    last_heartbeat = now
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                except TimeoutError:  # nosec B110
                    pass
                except WebSocketDisconnect:
                    break
        except WebSocketDisconnect:  # nosec B110
            pass
    finally:
        logger.debug("ws_audit_events: disconnected user=%s", user_id)
