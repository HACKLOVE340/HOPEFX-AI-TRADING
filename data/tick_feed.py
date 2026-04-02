# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data/tick_feed.py
=================
Tick data ingestion layer — aggregates live ticks from real broker feeds
(OANDA streaming, Finnhub WebSocket, Polygon WebSocket) into a unified
TickBus that the execution engine and market data layer can subscribe to.

Architecture
------------
TickSource (ABC)       — common interface for all tick providers
OandaTickSource        — OANDA v20 streaming prices API
FinnhubTickSource      — Finnhub WebSocket (wss://ws.finnhub.io)
PolygonTickSource      — Polygon.io forex WebSocket
TickAggregator         — OHLCV bar builder from raw ticks (1s / 5s / 1m)
TickBus                — fan-out hub; subscribers receive every validated tick
TickFeedManager        — lifecycle manager; starts/stops all sources

All sources implement exponential back-off reconnection and a per-source
circuit breaker.  Ticks are validated against a plausible price range before
being published.

Subscriber protocol
-------------------
Any object with an async ``on_tick(tick: Tick)`` method can subscribe.
The TickBus calls all subscribers concurrently on every validated tick.

Usage
-----
    from data.tick_feed import TickFeedManager, get_tick_feed

    manager = get_tick_feed()
    manager.subscribe(execution_engine)
    manager.subscribe(risk_manager)
    await manager.start()          # non-blocking; starts background tasks
    ...
    await manager.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, Callable
import contextlib

logger = logging.getLogger(__name__)

# ── Price sanity bounds (XAUUSD) ──────────────────────────────────────────────
_PRICE_MIN = 1_000.0
_PRICE_MAX = 10_000.0

# ── Back-off config ───────────────────────────────────────────────────────────
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 60.0
_CIRCUIT_THRESHOLD = 5  # consecutive failures before circuit opens
_CIRCUIT_COOLDOWN = 60.0  # seconds before circuit retries


# ── Tick dataclass ────────────────────────────────────────────────────────────


@dataclass
class Tick:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    volume: float = 0.0
    source: str = ""

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "mid": round(self.mid, 5),
            "spread": round(self.spread, 5),
            "volume": self.volume,
            "source": self.source,
        }


# ── OHLCV Bar ─────────────────────────────────────────────────────────────────


@dataclass
class OHLCVBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    timeframe_s: int  # bar duration in seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "timeframe_s": self.timeframe_s,
        }


# ── Tick validation ───────────────────────────────────────────────────────────


def _is_valid_tick(tick: Tick) -> bool:
    if tick.bid <= 0 or tick.ask <= 0:
        return False
    if tick.bid > tick.ask:
        return False
    mid = tick.mid
    return not (mid < _PRICE_MIN or mid > _PRICE_MAX)


# ── Abstract tick source ──────────────────────────────────────────────────────


class TickSource(ABC):
    """Base class for all tick data providers."""

    def __init__(self, symbol: str = "XAU_USD"):
        self.symbol = symbol
        self._running = False
        self._fail_count = 0
        self._circuit_open_at: float | None = None
        self._on_tick: Callable | None = None

    def set_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection and start streaming ticks."""

    async def start(self) -> None:
        """Start with exponential back-off reconnection."""
        self._running = True
        backoff = _BACKOFF_INITIAL
        while self._running:
            if self._is_circuit_open():
                await asyncio.sleep(5.0)
                continue
            try:
                await self.connect()
                backoff = _BACKOFF_INITIAL
                self._fail_count = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._fail_count += 1
                logger.warning(
                    "%s: connection error (%d): %s",
                    self.__class__.__name__,
                    self._fail_count,
                    exc,
                )
                if self._fail_count >= _CIRCUIT_THRESHOLD:
                    self._circuit_open_at = time.monotonic()
                    logger.error(
                        "%s: circuit breaker OPEN after %d failures",
                        self.__class__.__name__,
                        self._fail_count,
                    )
                if self._running:
                    await asyncio.sleep(min(backoff, _BACKOFF_MAX))
                    backoff = min(backoff * 2, _BACKOFF_MAX)

    async def stop(self) -> None:
        self._running = False

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_at is None:
            return False
        if time.monotonic() - self._circuit_open_at >= _CIRCUIT_COOLDOWN:
            self._circuit_open_at = None
            self._fail_count = 0
            logger.info("%s: circuit breaker CLOSED", self.__class__.__name__)
            return False
        return True

    async def _emit(self, tick: Tick) -> None:
        if self._on_tick and _is_valid_tick(tick):
            await self._on_tick(tick)


# ── OANDA streaming tick source ───────────────────────────────────────────────


class OandaTickSource(TickSource):
    """
    OANDA v20 streaming prices API.

    Streams bid/ask ticks for the given instrument over a persistent HTTP
    chunked-transfer connection.  Reconnects automatically on disconnect.

    Env vars: OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_PRACTICE (default true)
    """

    def __init__(self, symbol: str = "XAU_USD"):
        super().__init__(symbol)
        self._api_key = os.getenv("OANDA_API_KEY", "")
        self._account_id = os.getenv("OANDA_ACCOUNT_ID", "")
        practice = os.getenv("OANDA_PRACTICE", "true").lower() != "false"
        self._stream_url = "https://stream-fxpractice.oanda.com" if practice else "https://stream-fxtrade.oanda.com"

    async def connect(self) -> None:
        if not self._api_key or not self._account_id:
            logger.warning("OandaTickSource: OANDA_API_KEY or OANDA_ACCOUNT_ID not set")
            await asyncio.sleep(30)
            return

        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed — OandaTickSource unavailable")
            await asyncio.sleep(60)
            return

        url = f"{self._stream_url}/v3/accounts/{self._account_id}/pricing/stream?instruments={self.symbol}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept-Datetime-Format": "RFC3339",
        }

        logger.info("OandaTickSource: connecting to %s", url)
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=None)) as resp,
        ):
            if resp.status != 200:
                body = await resp.text()
                raise ConnectionError(f"OANDA stream HTTP {resp.status}: {body[:200]}")

            logger.info("OandaTickSource: stream connected")
            async for raw_line in resp.content:
                if not self._running:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") != "PRICE":
                    continue

                bids = msg.get("bids", [])
                asks = msg.get("asks", [])
                if not bids or not asks:
                    continue

                bid = float(bids[0]["price"])
                ask = float(asks[0]["price"])
                ts_str = msg.get("time", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now(UTC)

                tick = Tick(
                    symbol=self.symbol,
                    timestamp=ts,
                    bid=bid,
                    ask=ask,
                    volume=0.0,
                    source="oanda",
                )
                await self._emit(tick)


# ── Finnhub WebSocket tick source ─────────────────────────────────────────────


class FinnhubTickSource(TickSource):
    """
    Finnhub WebSocket tick source (wss://ws.finnhub.io).

    Subscribes to FOREX:OANDA:XAU_USD.
    Env var: FINNHUB_API_KEY
    """

    _WS_URL = "wss://ws.finnhub.io"
    _FINNHUB_SYMBOL = "FOREX:OANDA:XAU_USD"

    def __init__(self, symbol: str = "XAU_USD"):
        super().__init__(symbol)
        self._api_key = os.getenv("FINNHUB_API_KEY", "")

    async def connect(self) -> None:
        if not self._api_key:
            logger.warning("FinnhubTickSource: FINNHUB_API_KEY not set")
            await asyncio.sleep(30)
            return

        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed — FinnhubTickSource unavailable")
            await asyncio.sleep(60)
            return

        url = f"{self._WS_URL}?token={self._api_key}"
        logger.info("FinnhubTickSource: connecting")

        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            await ws.send(json.dumps({"type": "subscribe", "symbol": self._FINNHUB_SYMBOL}))
            logger.info("FinnhubTickSource: subscribed to %s", self._FINNHUB_SYMBOL)

            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") != "trade":
                    continue

                for trade in msg.get("data", []):
                    price = float(trade.get("p", 0))
                    vol = float(trade.get("v", 0))
                    ts_ms = trade.get("t", 0)
                    ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)

                    # Finnhub gives last trade price; use as both bid and ask
                    # (spread unknown from this feed — use 0.5 pip estimate)
                    half_spread = price * 0.00003
                    tick = Tick(
                        symbol=self.symbol,
                        timestamp=ts,
                        bid=price - half_spread,
                        ask=price + half_spread,
                        volume=vol,
                        source="finnhub",
                    )
                    await self._emit(tick)


# ── Polygon WebSocket tick source ─────────────────────────────────────────────


class PolygonTickSource(TickSource):
    """
    Polygon.io forex WebSocket (wss://socket.polygon.io/forex).

    Subscribes to C.XAU/USD (forex quote channel).
    Env var: POLYGON_API_KEY
    """

    _WS_URL = "wss://socket.polygon.io/forex"

    def __init__(self, symbol: str = "XAU_USD"):
        super().__init__(symbol)
        self._api_key = os.getenv("POLYGON_API_KEY", "")

    async def connect(self) -> None:
        if not self._api_key:
            logger.warning("PolygonTickSource: POLYGON_API_KEY not set")
            await asyncio.sleep(30)
            return

        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed — PolygonTickSource unavailable")
            await asyncio.sleep(60)
            return

        logger.info("PolygonTickSource: connecting")
        async with websockets.connect(self._WS_URL, ping_interval=20) as ws:
            # Auth
            await ws.send(json.dumps({"action": "auth", "params": self._api_key}))
            auth_resp = json.loads(await ws.recv())
            if not any(m.get("status") == "auth_success" for m in auth_resp):
                raise ConnectionError(f"Polygon auth failed: {auth_resp}")

            # Subscribe to XAU/USD quotes
            await ws.send(json.dumps({"action": "subscribe", "params": "C.XAU/USD"}))
            logger.info("PolygonTickSource: subscribed to C.XAU/USD")

            async for raw in ws:
                if not self._running:
                    break
                try:
                    messages = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                for msg in messages:
                    ev = msg.get("ev")
                    if ev != "C":
                        continue
                    bid = float(msg.get("b", 0))
                    ask = float(msg.get("a", 0))
                    ts_ms = msg.get("t", 0)
                    ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)

                    tick = Tick(
                        symbol=self.symbol,
                        timestamp=ts,
                        bid=bid,
                        ask=ask,
                        volume=float(msg.get("x", 0)),
                        source="polygon",
                    )
                    await self._emit(tick)


# ── Tick Aggregator (ticks → OHLCV bars) ─────────────────────────────────────


class TickAggregator:
    """
    Aggregates raw ticks into OHLCV bars at configurable timeframes.

    Supported timeframes: 1s, 5s, 10s, 30s, 60s (1m), 300s (5m).
    Emits a completed bar to registered bar_callbacks when the bar closes.
    """

    def __init__(self, symbol: str, timeframe_s: int = 60):
        self.symbol = symbol
        self.timeframe_s = timeframe_s
        self._bar_callbacks: list[Callable] = []
        self._current_bar: dict[str, Any] | None = None
        self._bar_start: float | None = None

    def add_bar_callback(self, cb: Callable) -> None:
        self._bar_callbacks.append(cb)

    async def on_tick(self, tick: Tick) -> None:
        now = time.time()
        mid = tick.mid

        if self._bar_start is None or (now - self._bar_start) >= self.timeframe_s:
            # Close previous bar
            if self._current_bar is not None:
                bar = OHLCVBar(
                    symbol=self.symbol,
                    timestamp=datetime.fromtimestamp(self._bar_start, tz=UTC),
                    open=self._current_bar["open"],
                    high=self._current_bar["high"],
                    low=self._current_bar["low"],
                    close=self._current_bar["close"],
                    volume=self._current_bar["volume"],
                    tick_count=self._current_bar["tick_count"],
                    timeframe_s=self.timeframe_s,
                )
                for cb in self._bar_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(bar)
                        else:
                            cb(bar)
                    except Exception as exc:
                        logger.warning("TickAggregator bar callback error: %s", exc)

            # Open new bar
            self._bar_start = now
            self._current_bar = {
                "open": mid,
                "high": mid,
                "low": mid,
                "close": mid,
                "volume": tick.volume,
                "tick_count": 1,
            }
        else:
            # Update current bar
            self._current_bar["high"] = max(self._current_bar["high"], mid)
            self._current_bar["low"] = min(self._current_bar["low"], mid)
            self._current_bar["close"] = mid
            self._current_bar["volume"] += tick.volume
            self._current_bar["tick_count"] += 1


# ── Tick Bus ──────────────────────────────────────────────────────────────────


class TickBus:
    """
    Fan-out hub: receives ticks from all sources and delivers to all subscribers.

    Deduplicates ticks from multiple sources using a short-window price cache
    (same mid price within 50ms from different sources = one delivery).
    """

    def __init__(self, dedup_window_ms: float = 50.0):
        self._subscribers: list[Any] = []
        self._dedup_window_ms = dedup_window_ms
        self._recent: deque = deque(maxlen=20)  # (timestamp_ms, mid)
        self._tick_count = 0
        self._last_tick: Tick | None = None

    def subscribe(self, component: Any) -> None:
        """Register a subscriber with an async on_tick(tick) method."""
        self._subscribers.append(component)
        logger.info("TickBus: %s subscribed", type(component).__name__)

    def unsubscribe(self, component: Any) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(component)

    async def publish(self, tick: Tick) -> None:
        """Validate, deduplicate, and fan-out a tick to all subscribers."""
        if not _is_valid_tick(tick):
            return

        # Deduplication: skip if same mid seen within dedup_window_ms
        now_ms = tick.timestamp.timestamp() * 1000
        mid = tick.mid
        for prev_ms, prev_mid in self._recent:
            if abs(now_ms - prev_ms) <= self._dedup_window_ms and abs(mid - prev_mid) < 0.001:
                return

        self._recent.append((now_ms, mid))
        self._tick_count += 1
        self._last_tick = tick

        # Fan-out concurrently
        tasks = []
        for sub in self._subscribers:
            handler = getattr(sub, "on_tick", None)
            if handler and asyncio.iscoroutinefunction(handler):
                tasks.append(asyncio.create_task(handler(tick)))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("TickBus subscriber error: %s", r)

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_tick(self) -> Tick | None:
        return self._last_tick

    def status(self) -> dict[str, Any]:
        return {
            "subscribers": len(self._subscribers),
            "tick_count": self._tick_count,
            "last_tick": self._last_tick.to_dict() if self._last_tick else None,
        }


# ── Tick Feed Manager ─────────────────────────────────────────────────────────


class TickFeedManager:
    """
    Lifecycle manager for all tick sources.

    Starts OANDA, Finnhub, and Polygon sources concurrently.
    Routes all ticks through the TickBus.
    Builds OHLCV bars via TickAggregator.

    Usage
    -----
        manager = TickFeedManager()
        manager.subscribe(execution_engine)
        await manager.start()
        ...
        await manager.stop()
    """

    def __init__(self, symbol: str = "XAU_USD", bar_timeframe_s: int = 60):
        self.symbol = symbol
        self._bus = TickBus()
        self._aggregator = TickAggregator(symbol, timeframe_s=bar_timeframe_s)
        self._sources: list[TickSource] = [
            OandaTickSource(symbol),
            FinnhubTickSource(symbol),
            PolygonTickSource(symbol),
        ]
        self._tasks: list[asyncio.Task] = []
        self._running = False

        # Wire sources → bus
        for src in self._sources:
            src.set_callback(self._bus.publish)

        # Wire bus → aggregator
        self._bus.subscribe(self._aggregator)

    # ── public ────────────────────────────────────────────────────────────────

    def subscribe(self, component: Any) -> None:
        """Subscribe to tick events (component needs async on_tick method)."""
        self._bus.subscribe(component)

    def add_bar_callback(self, cb: Callable) -> None:
        """Subscribe to completed OHLCV bars."""
        self._aggregator.add_bar_callback(cb)

    async def start(self) -> None:
        """Start all tick sources as background tasks."""
        if self._running:
            return
        self._running = True
        for src in self._sources:
            task = asyncio.create_task(src.start(), name=f"tick_{src.__class__.__name__}")
            self._tasks.append(task)
        logger.info(
            "TickFeedManager: started %d sources for %s",
            len(self._sources),
            self.symbol,
        )

    async def stop(self) -> None:
        """Stop all tick sources."""
        self._running = False
        for src in self._sources:
            await src.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("TickFeedManager: stopped")

    def status(self) -> dict[str, Any]:
        source_status = []
        for src in self._sources:
            source_status.append(
                {
                    "source": src.__class__.__name__,
                    "running": src._running,
                    "fail_count": src._fail_count,
                    "circuit_open": src._is_circuit_open(),
                }
            )
        return {
            "symbol": self.symbol,
            "running": self._running,
            "sources": source_status,
            "bus": self._bus.status(),
        }

    @property
    def bus(self) -> TickBus:
        return self._bus

    @property
    def last_tick(self) -> Tick | None:
        return self._bus.last_tick


# ── module-level singleton ────────────────────────────────────────────────────

_manager: TickFeedManager | None = None


def get_tick_feed(symbol: str = "XAU_USD", bar_timeframe_s: int = 60) -> TickFeedManager:
    """Return the module-level TickFeedManager singleton (lazy init)."""
    global _manager
    if _manager is None:
        _manager = TickFeedManager(symbol=symbol, bar_timeframe_s=bar_timeframe_s)
    return _manager
