# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/redis_stream_reader.py
================================
Real-time Redis pub/sub consumer for all NuclearStreamer channels.

Data flows exclusively from internal Redis pub/sub — no broker APIs,
no OANDA. NuclearStreamer publishes ticks and OHLCV bars; this module
subscribes and maintains in-memory ring buffers for the strategy engine.

Channels consumed
-----------------
  ticks_channel     Live bid/ask/volume ticks (from NuclearStreamer)
  ohlcv_1m          1-minute OHLCV bars
  ohlcv_5m          5-minute OHLCV bars
  ohlcv_30m         30-minute OHLCV bars
  ohlcv_1h          1-hour OHLCV bars
  ohlcv_daily       Daily OHLCV bars
  ohlcv_weekly      Weekly OHLCV bars
  ohlcv_monthly     Monthly OHLCV bars
  ohlcv_yearly      Yearly OHLCV bars
  itos_cone_channel Pre-computed ITOS cone updates (optional)
  macro_channel     Macro data: VIX/DXY/SPX/GLD/US10Y

Architecture
------------
  RedisStreamReader.start()
    └─ asyncio pub/sub listener
         ├─ on_tick()      → deque[TickSnapshot] (last 100 ticks)
         ├─ on_ohlcv()     → deque[OHLCVBar] per timeframe (last 500 bars)
         ├─ on_cone()      → latest ItosCone dict
         └─ on_macro()     → latest MacroSnapshot

Usage
-----
    reader = RedisStreamReader()
    await reader.start()

    # Synchronous snapshot access (thread-safe via asyncio.Lock)
    ticks = reader.get_ticks(n=30)
    bars  = reader.get_bars("ohlcv_daily", n=5)
    macro = reader.get_macro()
    cone  = reader.get_cone()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Channel names (must match NuclearStreamer publish targets) ─────────────────
TICKS_CHANNEL = "ticks_channel"
ITOS_CONE_CHANNEL = "itos_cone_channel"
MACRO_CHANNEL = "macro_channel"

OHLCV_CHANNELS: dict[str, str] = {
    "ohlcv_1m": "1m",
    "ohlcv_5m": "5m",
    "ohlcv_30m": "30m",
    "ohlcv_1h": "1h",
    "ohlcv_daily": "daily",
    "ohlcv_weekly": "weekly",
    "ohlcv_monthly": "monthly",
    "ohlcv_yearly": "yearly",
}

ALL_CHANNELS = [TICKS_CHANNEL, ITOS_CONE_CHANNEL, MACRO_CHANNEL] + list(OHLCV_CHANNELS.keys())

# Ring buffer sizes
_TICK_BUFFER = 200
_BAR_BUFFER = 500


# ── Data containers ───────────────────────────────────────────────────────────


@dataclass
class TickSnapshot:
    """Single tick from ticks_channel."""

    symbol: str
    bid: float
    ask: float
    mid: float
    volume: float
    timestamp: datetime
    source: str = ""
    spread: float = 0.0

    def __post_init__(self) -> None:
        if self.spread == 0.0 and self.ask > self.bid:
            self.spread = round(self.ask - self.bid, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "volume": self.volume,
            "spread": self.spread,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class OHLCVBar:
    """Single OHLCV bar from any ohlcv_* channel."""

    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_time: datetime
    close_time: datetime | None = None
    tick_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "tick_count": self.tick_count,
        }


@dataclass
class MacroSnapshot:
    """Latest macro data from macro_channel."""

    vix: float = 0.0
    dxy: float = 0.0
    spx: float = 0.0
    gld: float = 0.0
    us10y: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "vix": self.vix,
            "dxy": self.dxy,
            "spx": self.spx,
            "gld": self.gld,
            "us10y": self.us10y,
            "timestamp": self.timestamp.isoformat(),
        }

    @property
    def risk_off(self) -> bool:
        """True when macro signals risk-off environment."""
        return self.vix > 25.0 or self.us10y > 5.0

    @property
    def dollar_strength(self) -> str:
        """DXY regime: 'strong', 'weak', or 'neutral'."""
        if self.dxy > 105:
            return "strong"
        if self.dxy < 98:
            return "weak"
        return "neutral"


# ── RedisStreamReader ─────────────────────────────────────────────────────────


class RedisStreamReader:
    """
    Async Redis pub/sub consumer maintaining live ring buffers.

    All data originates from NuclearStreamer (FinnHub/TwelveData/Polygon WS).
    No broker APIs are called here.

    Parameters
    ----------
    host : str
        Redis host (env: REDIS_HOST, default: localhost)
    port : int
        Redis port (env: REDIS_PORT, default: 6379)
    db : int
        Redis DB index (env: REDIS_DB, default: 0)
    password : str, optional
        Redis password (env: REDIS_PASSWORD)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host or os.getenv("REDIS_HOST", "localhost")
        self._port = int(port or os.getenv("REDIS_PORT", "6379"))
        self._db = int(db or os.getenv("REDIS_DB", "0"))
        self._password = password or os.getenv("REDIS_PASSWORD") or None

        # Ring buffers
        self._ticks: deque[TickSnapshot] = deque(maxlen=_TICK_BUFFER)
        self._bars: dict[str, deque[OHLCVBar]] = {tf: deque(maxlen=_BAR_BUFFER) for tf in OHLCV_CHANNELS.values()}
        self._cone: dict[str, Any] = {}
        self._macro: MacroSnapshot = MacroSnapshot()

        # State
        self._running = False
        self._connected = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._redis_client = None
        self._pubsub = None

        # Stats
        self._stats: dict[str, int] = {
            "ticks_received": 0,
            "bars_received": 0,
            "cone_updates": 0,
            "macro_updates": 0,
            "parse_errors": 0,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the pub/sub listener as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop(), name="redis-stream-reader")
        logger.info(
            "RedisStreamReader started — %s:%d db=%d channels=%s",
            self._host,
            self._port,
            self._db,
            ALL_CHANNELS,
        )

    async def stop(self) -> None:
        """Gracefully stop the listener."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._disconnect()
        logger.info("RedisStreamReader stopped")

    # ── Public snapshot accessors (synchronous, safe to call from any coroutine)

    def get_ticks(self, n: int = 30) -> list[TickSnapshot]:
        """Return the last n ticks, newest last."""
        ticks = list(self._ticks)
        return ticks[-n:] if n < len(ticks) else ticks

    def get_bars(self, channel_or_tf: str, n: int = 5) -> list[OHLCVBar]:
        """
        Return the last n bars for a timeframe.

        Accepts either the channel name ('ohlcv_daily') or the
        timeframe label ('daily', '1h', etc.).
        """
        tf = OHLCV_CHANNELS.get(channel_or_tf, channel_or_tf)
        buf = self._bars.get(tf, deque())
        bars = list(buf)
        return bars[-n:] if n < len(bars) else bars

    def get_all_bars(self) -> dict[str, list[OHLCVBar]]:
        """Return all timeframe buffers as plain lists."""
        return {tf: list(buf) for tf, buf in self._bars.items()}

    def get_cone(self) -> dict[str, Any]:
        """Return the latest ITOS cone dict (empty if not yet received)."""
        return dict(self._cone)

    def get_macro(self) -> MacroSnapshot:
        """Return the latest macro snapshot."""
        return self._macro

    def get_latest_price(self) -> float | None:
        """Return the most recent mid price from the tick buffer."""
        if self._ticks:
            return self._ticks[-1].mid
        return None

    def is_connected(self) -> bool:
        return self._connected

    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "connected": self._connected,
            "tick_buffer_size": len(self._ticks),
            "bar_buffers": {tf: len(buf) for tf, buf in self._bars.items()},
        }

    # ── Internal listener loop ────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Main pub/sub loop with reconnect on failure."""
        backoff = 1.0
        while self._running:
            try:
                await self._connect()
                backoff = 1.0
                await self._consume()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._connected = False
                logger.warning(
                    "RedisStreamReader disconnected (%s) — reconnecting in %.1fs",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _connect(self) -> None:
        """Establish Redis connection and subscribe to all channels."""
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise RuntimeError("redis package required: pip install redis>=5.0.0") from exc

        self._redis_client = aioredis.Redis(
            host=self._host,
            port=self._port,
            db=self._db,
            password=self._password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=30,
            retry_on_timeout=True,
        )
        self._pubsub = self._redis_client.pubsub()
        await self._pubsub.subscribe(*ALL_CHANNELS)
        self._connected = True
        logger.info("RedisStreamReader connected to Redis %s:%d", self._host, self._port)

    async def _disconnect(self) -> None:
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            if self._redis_client:
                await self._redis_client.aclose()
        except Exception as _exc:  # non-fatal: best-effort cleanup on disconnect
            logger.debug("Error during Redis disconnect cleanup: %s", _exc)
        self._connected = False

    async def _consume(self) -> None:
        """Process messages from the pub/sub subscription."""
        async for message in self._pubsub.listen():
            if not self._running:
                break
            if message["type"] != "message":
                continue
            channel: str = message["channel"]
            data: str = message["data"]
            await self._dispatch(channel, data)

    async def _dispatch(self, channel: str, raw: str) -> None:
        """Parse and route a raw pub/sub message to the correct buffer."""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            self._stats["parse_errors"] += 1
            logger.debug("RedisStreamReader parse error on %s: %s", channel, exc)
            return

        try:
            if channel == TICKS_CHANNEL:
                await self._on_tick(payload)
            elif channel in OHLCV_CHANNELS:
                await self._on_ohlcv(channel, payload)
            elif channel == ITOS_CONE_CHANNEL:
                await self._on_cone(payload)
            elif channel == MACRO_CHANNEL:
                await self._on_macro(payload)
        except Exception as exc:
            self._stats["parse_errors"] += 1
            logger.error("RedisStreamReader dispatch error on %s: %s", channel, exc)

    # ── Message handlers ──────────────────────────────────────────────────────

    async def _on_tick(self, payload: dict[str, Any]) -> None:
        bid = float(payload.get("bid") or payload.get("price") or 0)
        ask = float(payload.get("ask") or payload.get("price") or 0)
        mid = float(payload.get("mid") or ((bid + ask) / 2 if bid and ask else 0))
        volume = float(payload.get("volume") or payload.get("vol") or 0)

        if mid <= 0:
            return

        ts_raw = payload.get("timestamp") or payload.get("time") or payload.get("t")
        ts = _parse_timestamp(ts_raw)

        tick = TickSnapshot(
            symbol=str(payload.get("symbol") or "XAU_USD"),
            bid=bid,
            ask=ask,
            mid=mid,
            volume=volume,
            timestamp=ts,
            source=str(payload.get("source") or ""),
        )
        async with self._lock:
            self._ticks.append(tick)
        self._stats["ticks_received"] += 1

    async def _on_ohlcv(self, channel: str, payload: dict[str, Any]) -> None:
        tf = OHLCV_CHANNELS[channel]
        o = float(payload.get("open") or 0)
        h = float(payload.get("high") or 0)
        lo = float(payload.get("low") or 0)
        c = float(payload.get("close") or 0)
        v = float(payload.get("volume") or 0)

        if c <= 0:
            return

        ts_raw = payload.get("open_time") or payload.get("time") or payload.get("t")
        open_time = _parse_timestamp(ts_raw)
        close_ts_raw = payload.get("close_time")
        close_time = _parse_timestamp(close_ts_raw) if close_ts_raw else None

        bar = OHLCVBar(
            symbol=str(payload.get("symbol") or "XAU_USD"),
            timeframe=tf,
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
            open_time=open_time,
            close_time=close_time,
            tick_count=int(payload.get("tick_count") or 0),
        )
        async with self._lock:
            self._bars[tf].append(bar)
        self._stats["bars_received"] += 1

    async def _on_cone(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._cone = payload
        self._stats["cone_updates"] += 1

    async def _on_macro(self, payload: dict[str, Any]) -> None:
        snap = MacroSnapshot(
            vix=float(payload.get("vix") or payload.get("VIX") or 0),
            dxy=float(payload.get("dxy") or payload.get("DXY") or 0),
            spx=float(payload.get("spx") or payload.get("SPX") or 0),
            gld=float(payload.get("gld") or payload.get("GLD") or 0),
            us10y=float(payload.get("us10y") or payload.get("US10Y") or 0),
            timestamp=_parse_timestamp(payload.get("timestamp")),
        )
        async with self._lock:
            self._macro = snap
        self._stats["macro_updates"] += 1

    # ── Bulk historical load from Redis lists/sorted-sets ─────────────────────

    async def load_historical_bars(
        self,
        channel: str,
        n: int = 500,
    ) -> list[OHLCVBar]:
        """
        Load the last n bars from a Redis list key (e.g. 'ohlcv_daily:history').

        NuclearStreamer appends completed bars to a list alongside pub/sub.
        This method bootstraps the ring buffer on startup.
        """
        if not self._redis_client:
            return []
        key = f"{channel}:history"
        try:
            raw_list = await self._redis_client.lrange(key, -n, -1)
            bars: list[OHLCVBar] = []
            tf = OHLCV_CHANNELS.get(channel, channel)
            for raw in raw_list:
                try:
                    payload = json.loads(raw)
                    o = float(payload.get("open") or 0)
                    h = float(payload.get("high") or 0)
                    lo = float(payload.get("low") or 0)
                    c = float(payload.get("close") or 0)
                    v = float(payload.get("volume") or 0)
                    if c <= 0:
                        continue
                    ts = _parse_timestamp(payload.get("open_time") or payload.get("time"))
                    bars.append(
                        OHLCVBar(
                            symbol=str(payload.get("symbol") or "XAU_USD"),
                            timeframe=tf,
                            open=o,
                            high=h,
                            low=lo,
                            close=c,
                            volume=v,
                            open_time=ts,
                        )
                    )
                except Exception as _exc:  # skip malformed bar entries
                    logger.debug("Skipping malformed bar entry in %s: %s", key, _exc)
                    continue
            logger.info("Loaded %d historical bars from %s", len(bars), key)
            return bars
        except Exception as exc:
            logger.warning("Could not load historical bars from %s: %s", key, exc)
            return []

    async def bootstrap(self) -> None:
        """
        Pre-fill ring buffers from Redis list history before live streaming.
        Call after start() to ensure bars are available immediately.
        """
        for channel in OHLCV_CHANNELS:
            bars = await self.load_historical_bars(channel, n=_BAR_BUFFER)
            tf = OHLCV_CHANNELS[channel]
            async with self._lock:
                for bar in bars:
                    self._bars[tf].append(bar)
        logger.info("RedisStreamReader bootstrap complete")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_timestamp(raw: Any) -> datetime:
    """Parse a timestamp from various formats into a UTC datetime."""
    if raw is None:
        return datetime.now(UTC)
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw
    if isinstance(raw, int | float):
        # Unix seconds or milliseconds
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
            except ValueError:
                continue
        # Try ISO format
        try:
            dt = datetime.fromisoformat(raw)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
        except ValueError:
            pass
    return datetime.now(UTC)


# ── Module-level singleton ────────────────────────────────────────────────────

_reader_instance: RedisStreamReader | None = None


def get_stream_reader(
    host: str | None = None,
    port: int | None = None,
    db: int | None = None,
) -> RedisStreamReader:
    """Return the process-wide RedisStreamReader singleton."""
    global _reader_instance
    if _reader_instance is None:
        _reader_instance = RedisStreamReader(host=host, port=port, db=db)
    return _reader_instance
