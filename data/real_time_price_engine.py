# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Real-Time Price Engine
WebSocket and REST hybrid data feed with automatic failover
"""

import abc
import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

import numpy as np

try:
    import aiohttp
    import aiohttp.web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import websockets

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class Tick:
    """Price tick data"""

    symbol: str
    timestamp: float
    bid: float
    ask: float
    mid: float
    volume: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.ask > self.bid else 0.0

    @property
    def spread_pct(self) -> float:
        return (self.spread / self.mid * 100) if self.mid > 0 else 0.0


@dataclass
class OHLCV:
    """OHLCV candle data"""

    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class PriceFeedBase(abc.ABC):
    """
    Abstract base class for all price feed implementations.

    Concrete subclasses must implement ``connect``, ``disconnect``, and
    ``get_ohlcv``.  Attempting to instantiate a subclass with any of these
    unimplemented raises ``TypeError`` at construction time.

    ``register_callback``, ``_notify_callbacks``, and ``get_last_price``
    are concrete helpers shared by all implementations.
    """

    def __init__(self, symbols: list[str], config: dict[str, Any]):
        self.symbols = symbols
        self.config = config
        self.active = False
        self._callbacks: list[Callable] = []
        self._last_prices: dict[str, Tick] = {}
        self._lock = asyncio.Lock()

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the feed connection and begin streaming prices."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close the feed connection and release resources."""

    def register_callback(self, callback: Callable[[Tick], None]) -> None:
        """Register a callback invoked on every new price tick."""
        self._callbacks.append(callback)

    def _notify_callbacks(self, tick: Tick) -> None:
        """Invoke all registered callbacks with the latest tick."""
        for callback in self._callbacks:
            try:
                callback(tick)
            except Exception as exc:
                logger.error("Price callback error: %s", exc)

    def get_last_price(self, symbol: str) -> Tick | None:
        """Return the most recent tick for *symbol*, or None if unseen."""
        return self._last_prices.get(symbol)

    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list[OHLCV]:
        """Return up to *limit* OHLCV bars for *symbol* at *timeframe*."""


class WebSocketPriceFeed(PriceFeedBase):
    """
    WebSocket-based real-time price feed
    Automatic reconnection with exponential backoff
    """

    def __init__(self, symbols: list[str], config: dict[str, Any]):
        super().__init__(symbols, config)
        self.ws_url = config.get("websocket_url", "wss://ws-feed.exchange.coinbase.com")
        self.reconnect_delay = config.get("reconnect_delay", 1.0)
        self.max_reconnect_delay = config.get("max_reconnect_delay", 60.0)
        self.heartbeat_interval = config.get("heartbeat_interval", 30.0)

        self._websocket = None
        self._reconnect_attempts = 0
        self._running = False
        self._heartbeat_task = None
        self._receive_task = None
        self._ohlcv_buffers: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=1000)))

    async def connect(self):
        """Connect to WebSocket feed"""
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets library required: pip install websockets")

        self._running = True

        while self._running:
            try:
                logger.info("Connecting to WebSocket: %s", self.ws_url)

                self._websocket = await websockets.connect(
                    self.ws_url, ping_interval=self.heartbeat_interval, ping_timeout=10
                )

                # Subscribe to channels
                subscribe_msg = {
                    "type": "subscribe",
                    "product_ids": self.symbols,
                    "channels": ["ticker", "heartbeat"],
                }
                await self._websocket.send(json.dumps(subscribe_msg))

                self.active = True
                self._reconnect_attempts = 0

                logger.info("WebSocket connected, subscribed to %s symbols", len(self.symbols))

                # Cancel any leftover tasks from a previous connection cycle
                for _dangling in (
                    getattr(self, "_receive_task", None),
                    getattr(self, "_heartbeat_task", None),
                ):
                    if _dangling is not None and not _dangling.done():
                        _dangling.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await _dangling

                # Start tasks
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # Wait for disconnect
                await self._receive_task

            except Exception as e:
                logger.error("WebSocket error: %s", e)

                self.active = False

                if not self._running:
                    break

                # Exponential backoff
                delay = min(
                    self.reconnect_delay * (2**self._reconnect_attempts),
                    self.max_reconnect_delay,
                )
                self._reconnect_attempts += 1

                logger.info("Reconnecting in %ss (attempt %s)", delay, self._reconnect_attempts)

                await asyncio.sleep(delay)

    async def disconnect(self):
        """Disconnect from WebSocket"""
        self._running = False
        self.active = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        if self._receive_task:
            self._receive_task.cancel()

        if self._websocket:
            await self._websocket.close()

        logger.info("WebSocket disconnected")

    async def _receive_loop(self):
        """Main receive loop"""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received: %s", message)

                except Exception as e:
                    logger.error("Message processing error: %s", e)

        except asyncio.CancelledError:
            ...  # nosec B110
        except Exception as e:
            logger.error("Receive loop error: %s", e)

    async def _process_message(self, data: dict):
        """Process incoming message"""
        msg_type = data.get("type")

        if msg_type == "ticker":
            # Process tick
            symbol = data.get("product_id")
            if symbol not in self.symbols:
                return

            # Prefer feed-provided timestamp to avoid local-clock skew
            _raw_ts = data.get("time")
            if _raw_ts:
                try:
                    _tick_ts = datetime.fromisoformat(str(_raw_ts).rstrip("Z")).replace(
                        tzinfo=UTC
                    ).timestamp()
                except (ValueError, TypeError):
                    _tick_ts = time.time()
            else:
                _tick_ts = time.time()

            tick = Tick(
                symbol=symbol,
                timestamp=_tick_ts,
                bid=float(data.get("best_bid", 0)),
                ask=float(data.get("best_ask", 0)),
                mid=(float(data.get("best_bid", 0)) + float(data.get("best_ask", 0))) / 2,
                volume=float(data.get("volume_24h", 0)),
                bid_volume=float(data.get("bid_volume", 0)),
                ask_volume=float(data.get("ask_volume", 0)),
            )

            async with self._lock:
                self._last_prices[symbol] = tick

            # Update OHLCV buffers
            self._update_ohlcv_buffers(symbol, tick)

            # Notify callbacks
            self._notify_callbacks(tick)

        elif msg_type == "heartbeat":
            logger.debug("Heartbeat received")

        elif msg_type == "error":
            logger.error("WebSocket error message: %s", data)

    def _update_ohlcv_buffers(self, symbol: str, tick: Tick):
        """Update OHLCV buffers with new tick"""
        now = datetime.now(UTC)

        for timeframe, seconds in [
            ("1m", 60),
            ("5m", 300),
            ("15m", 900),
            ("1h", 3600),
            ("4h", 14400),
            ("1d", 86400),
        ]:
            bucket_time = int(now.timestamp() / seconds) * seconds

            buffer = self._ohlcv_buffers[symbol][timeframe]

            if buffer and buffer[-1].timestamp == bucket_time:
                # Update existing candle
                candle = buffer[-1]
                candle.high = max(candle.high, tick.mid)
                candle.low = min(candle.low, tick.mid)
                candle.close = tick.mid
                candle.volume += tick.volume
            else:
                # New candle
                new_candle = OHLCV(
                    timestamp=bucket_time,
                    open=tick.mid,
                    high=tick.mid,
                    low=tick.mid,
                    close=tick.mid,
                    volume=tick.volume,
                )
                buffer.append(new_candle)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        try:
            while self._running:
                await asyncio.sleep(self.heartbeat_interval)
                if self._websocket and self._websocket.open:
                    try:
                        await self._websocket.send(json.dumps({"type": "heartbeat"}))
                    except Exception as e:
                        logger.warning("Heartbeat send failed: %s", e)

        except asyncio.CancelledError:
            ...  # nosec B110

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list[OHLCV]:
        """Get OHLCV from buffer"""
        if symbol not in self._ohlcv_buffers or timeframe not in self._ohlcv_buffers[symbol]:
            return []

        buffer = self._ohlcv_buffers[symbol][timeframe]
        return list(buffer)[-limit:]

    def get_spread(self, symbol: str) -> float | None:
        """Get current spread for symbol"""
        tick = self.get_last_price(symbol)
        return tick.spread if tick else None


class RESTPriceFeed(PriceFeedBase):
    """
    REST API fallback for historical data
    """

    def __init__(self, symbols: list[str], config: dict[str, Any]):
        super().__init__(symbols, config)
        self.rest_url = config.get("rest_url", "https://api.exchange.coinbase.com")
        self.rate_limit_per_sec = config.get("rate_limit_per_sec", 10)
        self._session: aiohttp.ClientSession | None = None
        self._request_times: deque = deque(maxlen=100)
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 5  # seconds

    async def connect(self):
        """Initialize REST client"""
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required: pip install aiohttp")

        self._session = aiohttp.ClientSession(
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        self.active = True
        logger.info("REST price feed initialized")

    async def disconnect(self):
        """Close REST client"""
        if self._session:
            await self._session.close()
        self.active = False

    async def _rate_limited_request(self, url: str) -> dict:
        """Make rate-limited request"""
        # Enforce rate limit
        now = time.time()
        while self._request_times and now - self._request_times[0] < 1.0:
            if len(self._request_times) >= self.rate_limit_per_sec:
                await asyncio.sleep(0.1)
                now = time.time()
            else:
                break

        self._request_times.append(now)

        async with self._session.get(url) as response:
            if response.status == 200:
                return await response.json()
            raise ValueError(f"HTTP {response.status}: {await response.text()}")

    # Coinbase only lists crypto products.  Forex and commodity symbols are
    # never available on this endpoint — skip them immediately so the caller
    # falls through to yfinance without an ERROR log on every poll cycle.
    _COINBASE_SYMBOL_PREFIXES = ("BTC", "ETH", "SOL", "LTC", "BCH", "XRP", "DOGE", "ADA", "MATIC", "AVAX")

    def _is_coinbase_symbol(self, symbol: str) -> bool:
        """Return True only for symbols Coinbase Exchange actually carries."""
        s = symbol.upper().replace("-", "").replace("/", "")
        return any(s.startswith(p) for p in self._COINBASE_SYMBOL_PREFIXES)

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list[OHLCV]:
        """Get OHLCV from Coinbase REST API.

        Returns an empty list immediately for non-crypto symbols (forex, gold,
        commodities) so the caller falls through to yfinance without making a
        doomed HTTP request or logging a spurious ERROR.
        """
        # Fast-path: Coinbase does not carry forex or commodity symbols.
        if not self._is_coinbase_symbol(symbol):
            logger.debug("REST feed: skipping %s (not a Coinbase product)", symbol)
            return []

        cache_key = f"{symbol}_{timeframe}_{limit}"

        # Check cache
        if cache_key in self._cache:
            cached_time, data = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return data

        # Map timeframe to API granularity
        granularity_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
        }
        granularity = granularity_map.get(timeframe, 3600)

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(seconds=granularity * limit)

        url = (
            f"{self.rest_url}/products/{symbol}/candles?"
            f"granularity={granularity}&"
            f"start={start_time.isoformat()}&"
            f"end={end_time.isoformat()}"
        )

        try:
            raw = await self._rate_limited_request(url)

            # Coinbase Exchange (legacy) returns a bare list:
            #   [[time, low, high, open, close, volume], ...]
            # Coinbase Advanced Trade API returns a dict:
            #   {"candles": [{"start": ..., "low": ..., ...}, ...]}
            candles_raw = raw.get("candles", []) if isinstance(raw, dict) else raw  # already a list

            ohlcv_list = []
            for candle in reversed(candles_raw):  # newest-first → reverse to chronological
                if isinstance(candle, dict):
                    # Advanced Trade format
                    ohlcv_list.append(
                        OHLCV(
                            timestamp=int(candle.get("start", candle.get("time", 0))),
                            low=float(candle.get("low", 0)),
                            high=float(candle.get("high", 0)),
                            open=float(candle.get("open", 0)),
                            close=float(candle.get("close", 0)),
                            volume=float(candle.get("volume", 0)),
                        )
                    )
                else:
                    # Legacy Exchange format: [time, low, high, open, close, volume]
                    ohlcv_list.append(
                        OHLCV(
                            timestamp=candle[0],
                            low=float(candle[1]),
                            high=float(candle[2]),
                            open=float(candle[3]),
                            close=float(candle[4]),
                            volume=float(candle[5]),
                        )
                    )

            # Cache result
            self._cache[cache_key] = (time.time(), ohlcv_list)

            return ohlcv_list

        except Exception as e:
            # Demote to WARNING — yfinance is the intended fallback for crypto
            # too, so a transient Coinbase outage is not an ERROR condition.
            logger.warning("REST feed error for %s: %s", symbol, e)
            return []


class RealTimePriceEngine:
    """
    Hybrid price engine with WebSocket primary and REST fallback.

    Features:
    - Automatic failover between WebSocket and REST
    - OHLCV aggregation from ticks
    - Spread monitoring
    - Latency tracking
    - Persistent tick storage via SQLAlchemy (batch-flushed to tick_data table)

    Tick persistence
    ----------------
    Pass a SQLAlchemy ``session_factory`` (e.g. the app's ``SessionLocal``) to
    enable durable tick storage.  Ticks are buffered in memory and flushed to
    the database in batches every ``tick_flush_interval`` seconds (default 5 s)
    or when the buffer reaches ``tick_batch_size`` entries (default 500).

    Without a session_factory the engine runs in memory-only mode — ticks are
    still available via the in-process deque buffers and Redis cache, but are
    lost on restart.

    Environment overrides
    ---------------------
    TICK_FLUSH_INTERVAL_SEC  — flush period in seconds (default 5)
    TICK_BATCH_SIZE          — max ticks per flush (default 500)
    TICK_PERSIST_ENABLED     — set to "0" to disable persistence even when a
                               session_factory is provided (useful in tests)
    """

    def __init__(self, config: dict[str, Any], session_factory=None):
        self.config = config
        self.symbols = config.get("symbols", ["EURUSD", "XAUUSD"])

        # Primary and fallback feeds
        self._ws_feed = WebSocketPriceFeed(self.symbols, config)
        self._rest_feed = RESTPriceFeed(self.symbols, config)

        # State
        self.active = False
        self._primary_active = False
        self._fallback_active = False
        self._latency_metrics: deque = deque(maxlen=1000)
        self._spread_metrics: dict[str, deque] = {s: deque(maxlen=100) for s in self.symbols}

        # Callbacks
        self._price_callbacks: list[Callable[[Tick], None]] = []
        self._candle_callbacks: list[Callable[[str, str, OHLCV], None]] = []

        # Tasks
        self._tasks: list[asyncio.Task] = []
        self._monitor_task: asyncio.Task | None = None
        self._tick_flush_task: asyncio.Task | None = None

        # ── Tick persistence ──────────────────────────────────────────────────
        import os as _os

        self._session_factory = session_factory
        self._tick_persist_enabled: bool = (
            session_factory is not None and _os.getenv("TICK_PERSIST_ENABLED", "1") != "0"
        )
        self._tick_flush_interval: float = float(_os.getenv("TICK_FLUSH_INTERVAL_SEC", "5"))
        self._tick_batch_size: int = int(_os.getenv("TICK_BATCH_SIZE", "500"))
        # Pending ticks waiting to be flushed; bounded to avoid unbounded growth
        # if the DB is slow.  Oldest ticks are dropped when the buffer is full
        # (same behaviour as the existing deque(maxlen=1000) OHLCV buffers).
        self._tick_buffer: deque = deque(maxlen=self._tick_batch_size * 4)
        self._tick_buffer_lock = asyncio.Lock()

    async def start(self):
        """Start price engine"""
        logger.info("Starting price engine for %s symbols", len(self.symbols))

        # Start fallback first
        try:
            await self._rest_feed.connect()
            self._fallback_active = True
            logger.info("REST fallback active")
        except Exception as e:
            logger.warning("REST fallback failed: %s", e)

        # Start primary WebSocket — skip when no URL is configured (e.g. tests)
        ws_url = self.config.get("websocket_url", "")
        if ws_url:
            try:
                ws_task = asyncio.create_task(self._ws_feed.connect())
                self._tasks.append(ws_task)
                self._primary_active = True

                # Register for updates
                self._ws_feed.register_callback(self._on_price_update)

                logger.info("WebSocket feed active")
            except Exception as e:
                logger.warning("WebSocket failed, using REST only: %s", e)

                self._primary_active = False
        else:
            logger.info("No WebSocket URL configured — running REST-only mode")

        self.active = self._primary_active or self._fallback_active

        # Start monitoring
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        # Start tick persistence flush loop if a session factory was provided
        if self._tick_persist_enabled:
            self._tick_flush_task = asyncio.create_task(self._tick_flush_loop(), name="tick_flush")
            logger.info(
                "Tick persistence enabled: flush every %.0fs, batch size %d",
                self._tick_flush_interval,
                self._tick_batch_size,
            )
        else:
            logger.info("Tick persistence disabled (no session_factory or TICK_PERSIST_ENABLED=0)")

        logger.info("Price engine started")

    async def stop(self):
        """Stop price engine"""
        logger.info("Stopping price engine")

        # Cancel tasks
        for task in self._tasks:
            task.cancel()

        if self._monitor_task:
            self._monitor_task.cancel()

        # Stop tick flush loop and drain any remaining buffered ticks
        if self._tick_flush_task and not self._tick_flush_task.done():
            self._tick_flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_flush_task
        if self._tick_persist_enabled and self._tick_buffer:
            await self._flush_ticks()

        # Disconnect feeds
        await self._ws_feed.disconnect()
        await self._rest_feed.disconnect()

        self.active = False
        logger.info("Price engine stopped")

    def _on_price_update(self, tick: Tick):
        """Handle price update from WebSocket."""
        # Record metrics
        self._spread_metrics[tick.symbol].append(tick.spread)

        # Buffer tick for DB persistence (non-blocking — flush loop drains async)
        if self._tick_persist_enabled:
            self._tick_buffer.append(tick)

        # Notify callbacks
        for callback in self._price_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error("Price callback error: %s", e)

    async def _tick_flush_loop(self) -> None:
        """Periodically flush buffered ticks to the tick_data table."""
        while True:
            try:
                await asyncio.sleep(self._tick_flush_interval)
                if self._tick_buffer:
                    await self._flush_ticks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Tick flush loop error: %s", exc)

    async def _flush_ticks(self) -> None:
        """
        Drain the tick buffer and batch-insert into the tick_data table.

        Runs in a thread-pool executor so the SQLAlchemy synchronous session
        does not block the event loop.
        """
        if not self._tick_buffer:
            return

        # Drain up to _tick_batch_size ticks atomically
        async with self._tick_buffer_lock:
            batch = []
            for _ in range(min(self._tick_batch_size, len(self._tick_buffer))):
                if self._tick_buffer:
                    batch.append(self._tick_buffer.popleft())

        if not batch:
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._persist_tick_batch, batch)
            logger.debug("Tick flush: persisted %d ticks to DB", len(batch))
        except Exception as exc:
            logger.error("Tick flush: DB write failed (%s) — %d ticks lost", exc, len(batch))

    def _persist_tick_batch(self, batch: list) -> None:
        """
        Synchronous DB write — called from a thread-pool executor.

        Inserts a batch of Tick objects into the tick_data table using the
        SQLAlchemy TickData model.  A single transaction covers the whole batch
        so a partial failure rolls back cleanly.
        """
        try:
            from database.models import TickData
        except ImportError as exc:
            logger.error("Tick persistence: could not import TickData model: %s", exc)
            return

        try:
            with self._session_factory() as session:
                rows = [
                    TickData(
                        symbol=tick.symbol,
                        bid=tick.bid,
                        ask=tick.ask,
                        last_price=tick.mid,
                        volume=tick.volume,
                        timestamp=datetime.fromtimestamp(tick.timestamp, tz=UTC),
                        source="websocket",
                    )
                    for tick in batch
                ]
                session.bulk_save_objects(rows)
                session.commit()
        except Exception as exc:
            logger.error("Tick persistence: session write failed: %s", exc)
            raise

    def register_price_callback(self, callback: Callable[[Tick], None]):
        """Register for price updates"""
        self._price_callbacks.append(callback)

    def register_candle_callback(self, callback: Callable[[str, str, OHLCV], None]):
        """Register for candle updates"""
        self._candle_callbacks.append(callback)

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list[OHLCV]:
        """
        Get OHLCV data, validated for price sanity and temporal ordering.

        Resolution order:
        1. WebSocket in-memory buffer (when primary feed is active)
        2. REST feed (Coinbase / configured endpoint)
        3. yfinance (free, no API key required) — always available
        4. Paper broker market_prices synthetic bars (last resort)

        Applies the data validation layer before returning bars to callers so
        that strategies and the ML pipeline never receive malformed data.
        """
        # 1. WebSocket buffer
        if self._primary_active:
            data = self._ws_feed.get_ohlcv(symbol, timeframe, limit)
            if data:
                return self._validate_ohlcv_list(data, symbol)

        # 2. REST feed
        raw = await self._rest_feed.get_ohlcv(symbol, timeframe, limit)
        if raw:
            return self._validate_ohlcv_list(raw, symbol)

        # 3. yfinance fallback — free, no API key required
        yf_data = await self._get_ohlcv_yfinance(symbol, timeframe, limit)
        if yf_data:
            return self._validate_ohlcv_list(yf_data, symbol)

        # 4. Paper broker synthetic bars (last resort — uses static market_prices)
        synth = self._get_ohlcv_from_broker(symbol, limit)
        return self._validate_ohlcv_list(synth, symbol)

    # ── yfinance OHLCV fallback ───────────────────────────────────────────────

    # Map internal symbol names to yfinance tickers
    _YF_TICKER_MAP: dict[str, str] = {
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "XPTUSD": "PL=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "USDCHF": "CHF=X",
        "AUDUSD": "AUDUSD=X",
        "NZDUSD": "NZDUSD=X",
        "USDCAD": "CAD=X",
        "BTCUSD": "BTC-USD",
        "BTC/USD": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "ETH/USD": "ETH-USD",
        "US30": "YM=F",
        "US500": "ES=F",
        "NAS100": "NQ=F",
        "USOIL": "CL=F",
        "UKOIL": "BZ=F",
    }

    _YF_INTERVAL_MAP: dict[str, str] = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",   # yfinance has no 4h; use 1h and let caller aggregate
        "1d": "1d",
        "1w": "1wk",
    }

    async def _get_ohlcv_yfinance(
        self, symbol: str, timeframe: str, limit: int
    ) -> list[OHLCV]:
        """Fetch OHLCV from yfinance in a thread pool (non-blocking)."""
        try:
            import yfinance as yf
            import pandas as pd

            ticker_sym = self._YF_TICKER_MAP.get(symbol.upper(), symbol)
            interval = self._YF_INTERVAL_MAP.get(timeframe, "1h")

            # Determine period based on limit + interval
            _period_map = {
                "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
                "1h": "730d", "1d": "5y", "1wk": "10y",
            }
            period = _period_map.get(interval, "730d")

            loop = asyncio.get_event_loop()

            def _fetch() -> list[OHLCV]:
                ticker = yf.Ticker(ticker_sym)
                df: pd.DataFrame = ticker.history(period=period, interval=interval, auto_adjust=True)
                if df.empty:
                    return []
                df = df.tail(limit)
                result: list[OHLCV] = []
                for ts, row in df.iterrows():
                    result.append(
                        OHLCV(
                            timestamp=int(ts.timestamp()),
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=float(row.get("Volume", 0)),
                        )
                    )
                return result

            data = await loop.run_in_executor(None, _fetch)
            if data:
                logger.info(
                    "OHLCV yfinance: %s %s — %d bars fetched",
                    symbol, timeframe, len(data),
                )
            return data
        except Exception as exc:
            logger.warning("OHLCV yfinance fallback failed for %s: %s", symbol, exc)
            return []

    def _get_ohlcv_from_broker(self, symbol: str, limit: int) -> list[OHLCV]:
        """
        Build synthetic OHLCV bars from the paper broker's static market_prices.
        Used only as a last resort when all real data sources are unavailable.
        Each bar spans 1 hour; price is constant (no movement fabricated).
        """
        try:
            from core.app_state import app_state  # type: ignore[import]

            broker = getattr(app_state, "broker", None)
            market_prices = getattr(broker, "market_prices", {}) if broker else {}
            price = market_prices.get(symbol)
            if not price or price <= 0:
                return []

            now = int(time.time())
            bars: list[OHLCV] = []
            for i in range(limit):
                ts = now - (limit - i) * 3600
                bars.append(OHLCV(
                    timestamp=ts,
                    open=price, high=price, low=price, close=price, volume=0.0,
                ))
            logger.debug(
                "OHLCV broker fallback: %s — %d synthetic bars (static price %.2f)",
                symbol, len(bars), price,
            )
            return bars
        except Exception as exc:
            logger.debug("OHLCV broker fallback failed for %s: %s", symbol, exc)
            return []

    def get_last_price(self, symbol: str) -> "Tick | None":
        """
        Return the most recent tick for *symbol*.

        Resolution order:
        1. WebSocket feed in-memory buffer
        2. REST feed in-memory buffer
        3. Paper broker market_prices (synthesise a Tick on the fly)
        """
        # 1. WebSocket buffer
        tick = self._ws_feed.get_last_price(symbol)
        if tick is not None:
            return tick

        # 2. REST buffer
        tick = self._rest_feed.get_last_price(symbol)
        if tick is not None:
            return tick

        # 3. Paper broker static prices
        try:
            from core.app_state import app_state  # type: ignore[import]

            broker = getattr(app_state, "broker", None)
            market_prices = getattr(broker, "market_prices", {}) if broker else {}
            price = market_prices.get(symbol)
            if price and price > 0:
                spread_map = {
                    "XAUUSD": 0.30, "XAGUSD": 0.03, "EURUSD": 0.0001,
                    "GBPUSD": 0.0002, "USDJPY": 0.02, "BTCUSD": 10.0,
                }
                spread = spread_map.get(symbol, price * 0.0002)
                return Tick(
                    symbol=symbol,
                    timestamp=time.time(),
                    bid=round(price - spread / 2, 5),
                    ask=round(price + spread / 2, 5),
                    mid=round(price, 5),
                    volume=0.0,
                )
        except Exception:
            pass
        return None

    def _validate_ohlcv_list(self, bars: list, symbol: str) -> list:
        """
        Validate a list of OHLCV namedtuples/objects.

        Converts to DataFrame, runs validate_ohlcv, then converts back.
        Returns the original list unchanged if validation is unavailable.
        """
        if not bars:
            return bars
        try:
            import pandas as pd
            from data_layer.validation import validate_ohlcv

            df = pd.DataFrame(
                [
                    {
                        "timestamp": getattr(b, "timestamp", i),
                        "open": getattr(b, "open", 0.0),
                        "high": getattr(b, "high", 0.0),
                        "low": getattr(b, "low", 0.0),
                        "close": getattr(b, "close", 0.0),
                        "volume": getattr(b, "volume", 0.0),
                    }
                    for i, b in enumerate(bars)
                ]
            )
            df = validate_ohlcv(df, symbol=symbol, strict=False, drop_bad_rows=True)
            # Reconstruct OHLCV objects from validated rows
            OHLCVType = type(bars[0])
            validated = []
            for _, row in df.iterrows():
                with contextlib.suppress(Exception):  # skip rows that can't be reconstructed
                    validated.append(
                        OHLCVType(
                            timestamp=row["timestamp"],
                            open=row["open"],
                            high=row["high"],
                            low=row["low"],
                            close=row["close"],
                            volume=row["volume"],
                        )
                    )
            return validated if validated else bars
        except Exception:  # nosec B110 — validation is non-fatal for live feed
            return bars

    async def _monitor_loop(self):
        """Monitor feed health"""
        while self.active:
            try:
                # Check WebSocket health
                if self._primary_active and not self._ws_feed.active:
                    logger.warning("WebSocket disconnected, activating REST fallback")
                    self._primary_active = False

                # Log statistics
                avg_spreads = {
                    s: np.mean(list(self._spread_metrics[s])) if self._spread_metrics[s] else 0 for s in self.symbols
                }

                logger.debug("Price engine stats: %s", avg_spreads)

                await asyncio.sleep(60)  # Check every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)

                await asyncio.sleep(5)

    def get_status(self) -> dict[str, Any]:
        """Get engine status"""
        return {
            "active": self.active,
            "primary_active": self._primary_active,
            "fallback_active": self._fallback_active,
            "symbols": self.symbols,
            "websocket_connected": self._ws_feed.active if self._ws_feed else False,
            "rest_available": self._rest_feed.active if self._rest_feed else False,
        }


# Convenience function
async def create_price_engine(config: dict[str, Any]) -> RealTimePriceEngine:
    """Factory function to create price engine"""
    engine = RealTimePriceEngine(config)
    await engine.start()
    return engine
