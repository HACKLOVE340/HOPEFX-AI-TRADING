# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# enhanced_realtime_engine.py
"""
=============================================================================
HOPEFX REAL-TIME MARKET DATA ENGINE v4.0
=============================================================================
Institutional-Grade Multi-Source Data Aggregation with Sub-Millisecond Latency

Features:
- Multi-venue WebSocket aggregation with Byzantine fault tolerance
- Consensus pricing using weighted median algorithms
- Nanosecond-precision timestamps with HFT-grade latency tracking
- Automatic failover and circuit breaker patterns
- Redis-backed distributed caching
- Real-time market microstructure analysis

Author: HOPEFX Development Team
License: Proprietary - Institutional Use Only
=============================================================================
"""

import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum, IntEnum, auto
from typing import Any

import aiohttp
import numpy as np
import websockets

# Optional high-performance libraries
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

import importlib.util as _importlib_util

ZMQ_AVAILABLE = _importlib_util.find_spec("zmq") is not None

try:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    UVLOOP_AVAILABLE = True
except ImportError:
    UVLOOP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("HOPEFX.Realtime")


# =============================================================================
# DATA STRUCTURES
# =============================================================================


class DataQuality(IntEnum):
    """Data quality classification based on latency and integrity"""

    EXCELLENT = 5  # < 1ms latency, fully validated
    GOOD = 4  # 1-10ms, minor issues acceptable
    FAIR = 3  # 10-100ms, some degradation
    POOR = 2  # 100-1000ms, significant issues
    STALE = 1  # > 1s, potentially unusable
    INVALID = 0  # Failed validation, reject


class ConnectionState(Enum):
    """Connection lifecycle states"""

    DISCONNECTED = auto()
    CONNECTING = auto()
    AUTHENTICATING = auto()
    SUBSCRIBING = auto()
    STREAMING = auto()
    DEGRADED = auto()
    FAILED = auto()
    RECONNECTING = auto()
    CIRCUIT_OPEN = auto()


@dataclass(frozen=True, slots=True)
class NanosecondTimestamp:
    """High-precision timestamp"""

    seconds: int
    nanoseconds: int

    @classmethod
    def now(cls) -> "NanosecondTimestamp":
        now = time.time_ns()
        return cls(now // 1_000_000_000, now % 1_000_000_000)

    def to_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.seconds + self.nanoseconds / 1e9, tz=UTC)

    def __float__(self) -> float:
        return self.seconds + self.nanoseconds / 1e9


@dataclass(frozen=True, slots=True)
class MarketTick:
    """Normalized market tick from any source"""

    timestamp: NanosecondTimestamp  # Exchange timestamp
    receive_timestamp: NanosecondTimestamp  # Local receive time
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_price: float | None = None
    last_size: float | None = None
    volume_24h: float | None = None
    vwap: float | None = None
    open_interest: float | None = None

    # Metadata
    source: str = "unknown"
    venue: str = "unknown"

    def __post_init__(self):
        # Validate
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError(f"Invalid prices: bid={self.bid}, ask={self.ask}")
        if self.bid >= self.ask:
            raise ValueError(f"Negative spread: {self.bid} >= {self.ask}")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        return (self.spread / self.mid) * 10000 if self.mid > 0 else 0

    @property
    def latency_ns(self) -> int:
        """Calculate tick-to-system latency"""
        recv_ns = self.receive_timestamp.seconds * 1_000_000_000 + self.receive_timestamp.nanoseconds
        tick_ns = self.timestamp.seconds * 1_000_000_000 + self.timestamp.nanoseconds
        return recv_ns - tick_ns

    @property
    def quality(self) -> DataQuality:
        """Classify data quality based on latency"""
        latency_ms = self.latency_ns / 1_000_000

        if latency_ms < 1:
            return DataQuality.EXCELLENT
        if latency_ms < 10:
            return DataQuality.GOOD
        if latency_ms < 100:
            return DataQuality.FAIR
        if latency_ms < 1000:
            return DataQuality.POOR
        return DataQuality.STALE


@dataclass
class VenueMetrics:
    """Real-time venue performance tracking"""

    venue_name: str
    state: ConnectionState = ConnectionState.DISCONNECTED

    # Latency tracking (nanoseconds)
    latency_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    min_latency_ns: int = float("inf")
    max_latency_ns: int = 0
    avg_latency_ns: float = 0.0

    # Throughput
    ticks_received: int = 0
    ticks_valid: int = 0
    ticks_stale: int = 0
    ticks_invalid: int = 0

    # Errors
    errors: int = 0
    reconnections: int = 0
    last_error: str | None = None
    last_error_time: datetime | None = None

    # Health score 0-100
    health_score: float = 100.0

    def record_tick(self, tick: MarketTick):
        """Process new tick metrics"""
        self.ticks_received += 1

        # Update latency
        latency = tick.latency_ns
        self.latency_history.append(latency)
        self.min_latency_ns = min(self.min_latency_ns, latency)
        self.max_latency_ns = max(self.max_latency_ns, latency)
        self.avg_latency_ns = np.mean(list(self.latency_history)) if self.latency_history else latency

        # Quality classification
        if tick.quality >= DataQuality.GOOD:
            self.ticks_valid += 1
        elif tick.quality == DataQuality.STALE:
            self.ticks_stale += 1
        else:
            self.ticks_invalid += 1

        # Update health
        self._update_health()

    def record_error(self, error: str):
        """Record error and degrade health"""
        self.errors += 1
        self.last_error = error
        self.last_error_time = datetime.now(UTC)
        self.health_score = max(0, self.health_score - 10)

    def record_reconnection(self):
        """Record successful reconnection"""
        self.reconnections += 1
        self.health_score = min(100, self.health_score + 5)

    def _update_health(self):
        """Update health score based on recent performance"""
        if len(self.latency_history) < 10:
            return

        recent_latencies = list(self.latency_history)[-100:]
        p99_latency = np.percentile(recent_latencies, 99)

        # Degrade health if latency too high
        if p99_latency > 100_000_000:  # 100ms
            self.health_score = max(0, self.health_score - 1)
        elif p99_latency < 10_000_000:  # 10ms
            self.health_score = min(100, self.health_score + 0.5)


# =============================================================================
# DATA PROVIDERS
# =============================================================================


class DataProvider(ABC):
    """Abstract base for all market data providers"""

    def __init__(self, name: str, priority: int, weight: float = 1.0):
        self.name = name
        self.priority = priority  # Lower = higher priority
        self.weight = weight
        self.metrics = VenueMetrics(venue_name=name)
        self.state = ConnectionState.DISCONNECTED

        self.symbols: set[str] = set()
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        self.current_reconnect_delay = self.reconnect_delay

        self._callbacks: list[Callable[[MarketTick], Any]] = []
        self._running = False
        self._task: asyncio.Task | None = None

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to venue"""

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> bool:
        """Subscribe to market data for symbols"""

    @abstractmethod
    async def stream(self) -> AsyncIterator[MarketTick]:
        """Yield ticks from connection"""

    @abstractmethod
    async def disconnect(self):
        """Clean disconnect"""

    def on_tick(self, callback: Callable[[MarketTick], Any]):
        """Register tick callback"""
        self._callbacks.append(callback)

    async def _notify(self, tick: MarketTick):
        """Notify all callbacks"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    _t = asyncio.create_task(callback(tick))
                    _t.add_done_callback(lambda _: None)
                else:
                    callback(tick)
            except Exception as e:
                logger.error("Callback error in %s: %s", self.name, e)

    async def start(self):
        """Start with automatic reconnection"""
        self._running = True

        while self._running:
            try:
                self.metrics.state = ConnectionState.CONNECTING
                self.state = ConnectionState.CONNECTING

                if await self.connect():
                    self.metrics.state = ConnectionState.SUBSCRIBING

                    if await self.subscribe(list(self.symbols)):
                        self.metrics.state = ConnectionState.STREAMING
                        self.current_reconnect_delay = self.reconnect_delay

                        async for tick in self.stream():
                            if not self._running:
                                break

                            self.metrics.record_tick(tick)
                            await self._notify(tick)

            except Exception as e:
                logger.error("%s error: %s", self.name, e)

                self.metrics.record_error(str(e))

            if self._running:
                self.metrics.state = ConnectionState.RECONNECTING
                logger.info("%s reconnecting in %ss...", self.name, self.current_reconnect_delay)

                await asyncio.sleep(self.current_reconnect_delay)
                self.current_reconnect_delay = min(self.current_reconnect_delay * 1.5, self.max_reconnect_delay)
                self.metrics.record_reconnection()

    def stop(self):
        """Stop streaming"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()


class PolygonProvider(DataProvider):
    """Polygon.io WebSocket provider"""

    def __init__(self, api_key: str):
        super().__init__("polygon", priority=1, weight=1.0)
        self.api_key = api_key
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.uri = "wss://socket.polygon.io/stocks"

    async def connect(self) -> bool:
        try:
            self.ws = await websockets.connect(self.uri)

            # Authenticate
            auth_msg = {"action": "auth", "params": self.api_key}
            await self.ws.send(json.dumps(auth_msg))

            response = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            auth_result = json.loads(response)

            if auth_result[0].get("status") == "connected":
                logger.info("Polygon authenticated successfully")
                return True

            logger.error("Polygon auth failed: %s", auth_result)

            return False

        except Exception as e:
            logger.error("Polygon connect failed: %s", e)

            return False

    async def subscribe(self, symbols: list[str]) -> bool:
        if not self.ws:
            return False

        # Format symbols for Polygon
        formatted = [s.replace("/", "") for s in symbols]

        # Subscribe to trades and quotes
        channels = []
        for sym in formatted:
            channels.extend([f"T.{sym}", f"Q.{sym}"])

        sub_msg = {"action": "subscribe", "params": ",".join(channels)}
        await self.ws.send(json.dumps(sub_msg))

        logger.info("Polygon subscribed to %s symbols", len(symbols))

        return True

    async def stream(self) -> AsyncIterator[MarketTick]:
        """Stream ticks from Polygon"""
        last_quotes = {}  # Track last quote for trade enrichment

        while True:
            try:
                message = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
                data = json.loads(message)

                for item in data:
                    msg_type = item.get("ev")

                    if msg_type == "Q":  # Quote
                        symbol = item.get("sym", "")
                        last_quotes[symbol] = {
                            "bid": item.get("bp", 0),
                            "ask": item.get("ap", 0),
                            "bid_size": item.get("bs", 0),
                            "ask_size": item.get("as", 0),
                        }

                    elif msg_type == "T":  # Trade
                        symbol = item.get("sym", "")
                        quote = last_quotes.get(symbol, {})

                        tick = MarketTick(
                            timestamp=NanosecondTimestamp(
                                item.get("t", 0) // 1_000_000_000,
                                (item.get("t", 0) % 1_000_000_000) * 1000,
                            ),
                            receive_timestamp=NanosecondTimestamp.now(),
                            symbol=symbol,
                            bid=quote.get("bid", item.get("p", 0)),
                            ask=quote.get("ask", item.get("p", 0)),
                            bid_size=quote.get("bid_size", 0),
                            ask_size=quote.get("ask_size", 0),
                            last_price=item.get("p", 0),
                            last_size=item.get("s", 0),
                            source="polygon",
                            venue="polygon",
                        )

                        yield tick

            except TimeoutError:
                logger.warning("Polygon heartbeat timeout")
                raise
            except Exception as e:
                logger.error("Polygon stream error: %s", e)

                raise

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.ws = None


class OandaProvider(DataProvider):
    """OANDA streaming API"""

    def __init__(self, account_id: str, api_token: str, environment: str = "practice"):
        super().__init__("oanda", priority=2, weight=0.9)
        self.account_id = account_id
        self.api_token = api_token
        self.environment = environment
        self.base_url = f"https://stream-fx{'' if environment == 'live' else 'practice'}.oanda.com"
        self.session: aiohttp.ClientSession | None = None

    async def connect(self) -> bool:
        self.session = aiohttp.ClientSession()
        return True

    async def subscribe(self, symbols: list[str]) -> bool:
        # OANDA format: XAU_USD
        self.symbols = {s.replace("/", "_") for s in symbols}
        return True

    async def stream(self) -> AsyncIterator[MarketTick]:
        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing/stream"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        params = {"instruments": ",".join(self.symbols)}

        async with self.session.get(url, headers=headers, params=params) as response:
            async for line in response.content:
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    if data.get("type") == "PRICE":
                        tick_time = datetime.fromisoformat(data["time"])
                        receive_time = datetime.now(UTC)

                        # Calculate latency
                        (receive_time - tick_time).total_seconds()

                        tick = MarketTick(
                            timestamp=NanosecondTimestamp(int(tick_time.timestamp()), tick_time.microsecond * 1000),
                            receive_timestamp=NanosecondTimestamp.now(),
                            symbol=data["instrument"].replace("_", "/"),
                            bid=float(data["bids"][0]["price"]),
                            ask=float(data["asks"][0]["price"]),
                            bid_size=float(data["bids"][0]["liquidity"]),
                            ask_size=float(data["asks"][0]["liquidity"]),
                            source="oanda",
                            venue="oanda",
                        )

                        yield tick

                except Exception as e:
                    logger.error("OANDA parse error: %s", e)

    async def disconnect(self):
        if self.session:
            await self.session.close()


class BinanceProvider(DataProvider):
    """Binance WebSocket with depth"""

    def __init__(self, api_key: str | None = None):
        super().__init__("binance", priority=3, weight=0.8)
        self.api_key = api_key
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.base_endpoint = "wss://stream.binance.com:9443/ws"

    async def connect(self) -> bool:
        try:
            # Create combined stream
            streams = "/".join([f"{s.lower()}@bookTicker" for s in self.symbols])
            url = f"{self.base_endpoint}/{streams}"

            self.ws = await websockets.connect(url)
            return True

        except Exception as e:
            logger.error("Binance connect failed: %s", e)

            return False

    async def subscribe(self, symbols: list[str]) -> bool:
        self.symbols = {s.replace("/", "").upper() for s in symbols}
        return True

    async def stream(self) -> AsyncIterator[MarketTick]:
        while True:
            try:
                msg = await self.ws.recv()
                data = json.loads(msg)

                tick = MarketTick(
                    timestamp=NanosecondTimestamp.now(),  # Binance doesn't provide nanosecond timestamp
                    receive_timestamp=NanosecondTimestamp.now(),
                    symbol=data["s"],
                    bid=float(data["b"]),
                    ask=float(data["a"]),
                    bid_size=float(data["B"]),
                    ask_size=float(data["A"]),
                    source="binance",
                    venue="binance",
                )

                yield tick

            except Exception as e:
                logger.error("Binance stream error: %s", e)

                raise

    async def disconnect(self):
        if self.ws:
            await self.ws.close()


class MockProvider(DataProvider):
    """
    Synthetic GBM tick generator — FOR TESTING AND DEVELOPMENT ONLY.

    This provider generates statistically plausible but entirely fabricated
    price data.  It MUST NOT be added to a production ConsensusAggregator.
    Production deployments must use PolygonProvider, OandaProvider, or
    BinanceProvider with real credentials.

    Raises RuntimeError if instantiated when APP_ENV=production.
    """

    def __init__(
        self,
        volatility: float = 0.0002,
        drift: float = 0.0,
        tick_interval_ms: float = 100,
    ):
        from utils.production_guard import assert_not_production
        assert_not_production(
            "MockProvider",
            replacement="PolygonProvider, OandaProvider, or BinanceProvider",
            extra="Configure a real data provider with valid API credentials.",
        )
        super().__init__("mock", priority=10, weight=0.1)
        self.volatility = volatility
        self.drift = drift
        self.tick_interval = tick_interval_ms / 1000  # Convert to seconds

        self.prices: dict[str, float] = {}
        self._start_time = time.time()

    async def connect(self) -> bool:
        # Initialize prices
        self.prices = {
            "XAU/USD": 1950.0,
            "EUR/USD": 1.0850,
            "GBP/USD": 1.2650,
            "USD/JPY": 150.0,
            "BTC/USD": 65000.0,
        }
        return True

    async def subscribe(self, symbols: list[str]) -> bool:
        self.symbols = set(symbols)
        # Initialize any missing prices
        for sym in symbols:
            if sym not in self.prices:
                self.prices[sym] = 100.0 + random.random() * 900  # nosec B311 - mock provider initial price, not cryptographic
        return True

    async def stream(self) -> AsyncIterator[MarketTick]:
        """Generate realistic synthetic ticks"""
        while True:
            start_loop = time.time()

            for symbol in self.symbols:
                if symbol not in self.prices:
                    continue

                base_price = self.prices[symbol]

                # Geometric Brownian Motion
                dt = self.tick_interval
                noise = np.nan_to_num(np.random.normal(0, self.volatility * np.sqrt(max(dt, 0.0))), nan=0.0)
                new_price = base_price * np.exp(np.nan_to_num(self.drift * dt + noise, nan=0.0))
                self.prices[symbol] = new_price

                # Realistic spread based on volatility
                spread = abs(noise) * base_price * 2 + base_price * 0.0001

                tick = MarketTick(
                    timestamp=NanosecondTimestamp.now(),
                    receive_timestamp=NanosecondTimestamp.now(),
                    symbol=symbol,
                    bid=new_price - spread / 2,
                    ask=new_price + spread / 2,
                    bid_size=np.random.exponential(10),
                    ask_size=np.random.exponential(10),
                    source="mock",
                    venue="mock",
                )

                yield tick

            # Maintain precise timing
            elapsed = time.time() - start_loop
            sleep_time = max(0, self.tick_interval - elapsed)
            await asyncio.sleep(sleep_time)


# =============================================================================
# CONSENSUS AGGREGATION ENGINE
# =============================================================================


class ConsensusAggregator:
    """
    Byzantine fault-tolerant consensus pricing.
    Combines multiple venue streams into single authoritative price.
    """

    def __init__(
        self,
        consensus_threshold: float = 0.67,
        max_sources: int = 5,
        outlier_threshold: float = 0.001,  # 10 bps
        redis_url: str | None = None,
    ):
        self.consensus_threshold = consensus_threshold
        self.max_sources = max_sources
        self.outlier_threshold = outlier_threshold

        # Redis for distributed caching
        self.redis: redis.Redis | None = None
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis = redis.from_url(redis_url)
            except Exception as e:
                logger.warning("Redis unavailable: %s", e)

        # State
        self.providers: dict[str, DataProvider] = {}
        self.latest_ticks: dict[str, dict[str, MarketTick]] = defaultdict(dict)
        self.consensus_prices: dict[str, MarketTick] = {}
        self.consensus_history: deque = deque(maxlen=1000)

        # Quality tracking
        self.venue_scores: dict[str, float] = {}

        # Callbacks
        self._consensus_callbacks: list[Callable[[MarketTick], Any]] = []

        # Statistics
        self.stats = {
            "ticks_processed": 0,
            "consensus_formed": 0,
            "disagreements": 0,
            "outliers_rejected": 0,
        }

    def add_provider(self, provider: DataProvider):
        """Add data source to aggregation"""
        if len(self.providers) >= self.max_sources:
            logger.warning("Max sources (%s) reached", self.max_sources)

            return

        self.providers[provider.name] = provider
        provider.on_tick(lambda tick: asyncio.create_task(self._process_tick(tick)))

        # Initialize venue score
        self.venue_scores[provider.name] = 1.0

        logger.info("Added provider: %s (priority=%s, weight=%s)", provider.name, provider.priority, provider.weight)

    async def _process_tick(self, tick: MarketTick):
        """Process incoming tick from any provider"""
        # Validate tick
        if tick.quality == DataQuality.INVALID:
            self.stats["outliers_rejected"] += 1
            return

        # Store tick
        self.latest_ticks[tick.symbol][tick.source] = tick
        self.stats["ticks_processed"] += 1

        # Attempt consensus formation
        consensus = self._form_consensus(tick.symbol)
        if consensus:
            self.consensus_prices[tick.symbol] = consensus
            self.consensus_history.append((consensus, datetime.now(UTC)))
            self.stats["consensus_formed"] += 1

            # Cache and notify
            await self._cache_consensus(consensus)
            await self._notify_consensus(consensus)

    def _form_consensus(self, symbol: str) -> MarketTick | None:
        """
        Form consensus price using weighted median.
        Implements Byzantine fault tolerance.
        """
        ticks = list(self.latest_ticks[symbol].values())

        # Need minimum sources
        if len(ticks) < 2:
            return ticks[0] if ticks else None

        # Check freshness (< 1 second old)
        now = time.time_ns()
        fresh_ticks = [
            t for t in ticks if (now - (t.timestamp.seconds * 1_000_000_000 + t.timestamp.nanoseconds)) < 1_000_000_000
        ]

        # Check if we have enough fresh data
        if len(fresh_ticks) < len(ticks) * self.consensus_threshold:
            return None

        # Calculate weighted scores for each tick
        scored_ticks = []
        for tick in fresh_ticks:
            provider = self.providers.get(tick.source)
            if not provider:
                continue

            # Score = weight * (1/latency) * health * quality
            latency_ms = tick.latency_ns / 1_000_000
            latency_score = 1 / max(latency_ms, 0.1)

            health_score = provider.metrics.health_score / 100.0

            quality_score = tick.quality.value / 5.0

            total_score = provider.weight * latency_score * health_score * quality_score

            scored_ticks.append((total_score, tick))

        if not scored_ticks:
            return None

        # Sort by score
        scored_ticks.sort(reverse=True)

        # Extract prices for outlier detection
        prices = [t.mid for _, t in scored_ticks]

        # Detect outliers using IQR
        if len(prices) >= 3:
            q1, q3 = np.percentile(prices, [25, 75])
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            # Filter outliers
            filtered = [(s, t) for s, t in scored_ticks if lower_bound <= t.mid <= upper_bound]

            if len(filtered) < len(scored_ticks):
                self.stats["outliers_rejected"] += len(scored_ticks) - len(filtered)
                scored_ticks = filtered

        # Calculate weighted median
        if not scored_ticks:
            return None

        total_weight = sum(s for s, _ in scored_ticks)
        cumulative = 0
        median_tick = None

        for score, tick in scored_ticks:
            cumulative += score
            if cumulative >= total_weight / 2:
                median_tick = tick
                break

        if not median_tick:
            median_tick = scored_ticks[0][1]

        # Calculate consensus spread (tightest spread across all sources)
        best_bid = max(t.bid for _, t in scored_ticks)
        best_ask = min(t.ask for _, t in scored_ticks)

        # Check for significant disagreement (Byzantine fault detection)
        price_range = max(t.mid for _, t in scored_ticks) - min(t.mid for _, t in scored_ticks)
        consensus_price = median_tick.mid

        if price_range > consensus_price * self.outlier_threshold:
            self.stats["disagreements"] += 1
            logger.warning(
                "Price disagreement for %s: range=%s (%s bps), sources=%s",
                symbol,
                price_range,
                price_range / consensus_price * 10000,
                [t.source for _, t in scored_ticks],
            )

        # Create consensus tick
        consensus = MarketTick(
            timestamp=median_tick.timestamp,
            receive_timestamp=NanosecondTimestamp.now(),
            symbol=symbol,
            bid=best_bid,
            ask=best_ask,
            bid_size=np.mean([t.bid_size for _, t in scored_ticks]),
            ask_size=np.mean([t.ask_size for _, t in scored_ticks]),
            source="consensus",
            venue="consensus",
        )

        return consensus

    async def _cache_consensus(self, tick: MarketTick):
        """Cache consensus in Redis"""
        if not self.redis:
            return

        try:
            key = f"consensus:{tick.symbol}"
            value = json.dumps(
                {
                    "timestamp": float(tick.timestamp),
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "quality": tick.quality.name,
                }
            )
            await self.redis.setex(key, 60, value)  # 60 second TTL
        except Exception as e:
            logger.error("Redis cache error: %s", e)

    async def _notify_consensus(self, tick: MarketTick):
        """Notify all consensus subscribers"""
        for callback in self._consensus_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    _t = asyncio.create_task(callback(tick))
                    _t.add_done_callback(lambda _: None)
                else:
                    callback(tick)
            except Exception as e:
                logger.error("Consensus callback error: %s", e)

    def on_consensus(self, callback: Callable[[MarketTick], Any]):
        """Subscribe to consensus ticks"""
        self._consensus_callbacks.append(callback)

    async def start(self):
        """Start all providers"""
        tasks = [asyncio.create_task(provider.start()) for provider in self.providers.values()]

        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        """Stop all providers"""
        for provider in self.providers.values():
            provider.stop()

    def get_health_report(self) -> dict[str, Any]:
        """Generate comprehensive health report"""
        return {
            "providers": {
                name: {
                    "state": provider.metrics.state.name,
                    "health_score": provider.metrics.health_score,
                    "latency_p50_ms": np.percentile(list(provider.metrics.latency_history), 50) / 1_000_000
                    if provider.metrics.latency_history
                    else 0,
                    "ticks_received": provider.metrics.ticks_received,
                    "errors": provider.metrics.errors,
                }
                for name, provider in self.providers.items()
            },
            "consensus": {
                "symbols_tracked": len(self.consensus_prices),
                "stats": self.stats,
                "latest_consensus": {
                    symbol: {
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "latency_ms": tick.latency_ns / 1_000_000,
                    }
                    for symbol, tick in list(self.consensus_prices.items())[:5]
                },
            },
            "redis": "connected" if self.redis else "disconnected",
        }


# =============================================================================
# PRODUCTION FACTORY
# =============================================================================


def build_production_aggregator(
    symbols: list[str] | None = None,
    consensus_threshold: float = 0.67,
    redis_url: str | None = None,
) -> "ConsensusAggregator":
    """
    Build a ConsensusAggregator wired with real data providers from env vars.

    Provider priority (highest weight first):
        1. Polygon.io  — POLYGON_API_KEY
        2. OANDA       — OANDA_ACCOUNT_ID + OANDA_API_KEY
        3. Binance     — BINANCE_API_KEY + BINANCE_SECRET

    At least one provider must be configured.  Raises RuntimeError if none
    are available and APP_ENV=production.

    Args:
        symbols:             Symbols to subscribe to (default: XAUUSD, EURUSD,
                             GBPUSD, USDJPY, BTCUSD).
        consensus_threshold: Fraction of sources that must agree (default 0.67).
        redis_url:           Optional Redis URL for distributed tick caching.

    Returns:
        Configured ConsensusAggregator ready to call .start() on.
    """
    import os as _os

    _symbols = symbols or ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD"]
    aggregator = ConsensusAggregator(
        consensus_threshold=consensus_threshold,
        max_sources=5,
        outlier_threshold=0.001,
        redis_url=redis_url or _os.getenv("REDIS_URL"),
    )

    added: list[str] = []

    # 1. Polygon.io
    polygon_key = _os.getenv("POLYGON_API_KEY", "").strip()
    if polygon_key:
        try:
            aggregator.add_provider(PolygonProvider(polygon_key))
            added.append("Polygon")
            logger.info("build_production_aggregator: added PolygonProvider")
        except Exception as exc:
            logger.warning("build_production_aggregator: PolygonProvider failed: %s", exc)

    # 2. OANDA
    oanda_account = _os.getenv("OANDA_ACCOUNT_ID", "").strip()
    oanda_key = _os.getenv("OANDA_API_KEY", "").strip()
    if oanda_account and oanda_key:
        try:
            aggregator.add_provider(OandaProvider(oanda_account, oanda_key))
            added.append("OANDA")
            logger.info("build_production_aggregator: added OandaProvider")
        except Exception as exc:
            logger.warning("build_production_aggregator: OandaProvider failed: %s", exc)

    # 3. Binance
    binance_key = _os.getenv("BINANCE_API_KEY", "").strip()
    binance_secret = _os.getenv("BINANCE_SECRET", "").strip()
    if binance_key and binance_secret:
        try:
            aggregator.add_provider(BinanceProvider(binance_key, binance_secret))
            added.append("Binance")
            logger.info("build_production_aggregator: added BinanceProvider")
        except Exception as exc:
            logger.warning("build_production_aggregator: BinanceProvider failed: %s", exc)

    if not added:
        env = _os.getenv("APP_ENV", "production").lower()
        msg = (
            "build_production_aggregator: no data providers configured. "
            "Set at least one of: POLYGON_API_KEY, OANDA_ACCOUNT_ID+OANDA_API_KEY, "
            "BINANCE_API_KEY+BINANCE_SECRET."
        )
        if env == "production":
            raise RuntimeError(msg)
        logger.warning(msg)

    logger.info(
        "build_production_aggregator: %d provider(s) registered: %s",
        len(added),
        ", ".join(added) or "none",
    )
    return aggregator


# =============================================================================
# EXAMPLE USAGE & TESTING
# =============================================================================


async def run_realtime_test():
    """
    Smoke-test for the realtime engine using MockProvider.

    FOR DEVELOPMENT / CI USE ONLY.  This function uses MockProvider which
    generates synthetic GBM ticks — not real market data.  It will raise
    RuntimeError if called in APP_ENV=production.
    """
    import os as _os

    if _os.getenv("APP_ENV", "production").lower() == "production":
        raise RuntimeError(
            "run_realtime_test() uses MockProvider and cannot run in production. "
            "Set APP_ENV=development or APP_ENV=test to use this function."
        )

    logger.info("=" * 80)
    logger.info("HOPEFX REAL-TIME ENGINE v4.0 - DEVELOPMENT SMOKE TEST")
    logger.info("=" * 80)

    # Create aggregator
    logger.info("\n[1] Initializing consensus aggregator...")
    aggregator = ConsensusAggregator(consensus_threshold=0.5, max_sources=5, outlier_threshold=0.001)

    # Add synthetic providers for smoke-testing only.
    # For production use, call build_production_aggregator() instead — it wires
    # real providers from POLYGON_API_KEY, OANDA_ACCOUNT_ID/OANDA_API_KEY,
    # and BINANCE_API_KEY/BINANCE_SECRET automatically.
    logger.info("[2] Adding synthetic test providers (MockProvider)...")
    aggregator.add_provider(MockProvider(volatility=0.0002, drift=0.00001, tick_interval_ms=100))  # pylint: disable=abstract-class-instantiated
    aggregator.add_provider(MockProvider(volatility=0.0003, drift=-0.00001, tick_interval_ms=150))  # pylint: disable=abstract-class-instantiated

    logger.info(f"    Added {len(aggregator.providers)} providers")

    # Set up tick collection
    consensus_ticks = []
    latencies = []

    def on_consensus(tick: MarketTick):
        consensus_ticks.append(tick)
        latencies.append(tick.latency_ns / 1_000_000)  # Convert to ms

        if len(consensus_ticks) % 100 == 0:
            logger.info(
                f"    Received {len(consensus_ticks)} consensus ticks (avg latency: {np.mean(latencies[-100:]):.2f} ms)"
            )

    aggregator.on_consensus(on_consensus)

    # Start aggregation
    logger.info("\n[3] Starting realtime aggregation (5 seconds)...")
    start_time = time.time()

    task = asyncio.create_task(aggregator.start())

    # Let it run
    await asyncio.sleep(5)

    # Stop
    logger.info("\n[4] Stopping aggregation...")
    aggregator.stop()
    task.cancel()

    elapsed = time.time() - start_time

    # Generate report
    logger.info("\n" + "=" * 80)
    logger.info("REAL-TIME ENGINE REPORT")
    logger.info("=" * 80)

    logger.info(f"\nDuration: {elapsed:.2f} seconds")
    logger.info(f"Consensus ticks received: {len(consensus_ticks)}")
    logger.info(f"Rate: {len(consensus_ticks) / elapsed:.1f} ticks/second")

    if latencies:
        logger.info("\n--- Latency Statistics ---")
        logger.info(f"Min: {min(latencies):.3f} ms")
        logger.info(f"Max: {max(latencies):.3f} ms")
        logger.info(f"Mean: {np.mean(latencies):.3f} ms")
        logger.info(f"P50: {np.percentile(latencies, 50):.3f} ms")
        logger.info(f"P99: {np.percentile(latencies, 99):.3f} ms")

    # Health report
    logger.info("\n--- Provider Health ---")
    health = aggregator.get_health_report()
    for name, status in health["providers"].items():
        logger.info(
            f"{name:15}: {status['state']:12} | "
            f"Health: {status['health_score']:5.1f} | "
            f"Latency: {status['latency_p50_ms']:6.2f} ms"
        )

    logger.info("\n--- Consensus Stats ---")
    logger.info(f"Ticks processed: {aggregator.stats['ticks_processed']}")
    logger.info(f"Consensus formed: {aggregator.stats['consensus_formed']}")
    logger.info(f"Disagreements: {aggregator.stats['disagreements']}")
    logger.info(f"Outliers rejected: {aggregator.stats['outliers_rejected']}")

    # Sample consensus prices
    if consensus_ticks:
        logger.info("\n--- Sample Prices (last 5) ---")
        for tick in consensus_ticks[-5:]:
            logger.info(f"{tick.symbol}: Bid={tick.bid:.5f} Ask={tick.ask:.5f} Spread={tick.spread_bps:.2f} bps")

    logger.info("\n" + "=" * 80)
    logger.info("✅ REAL-TIME ENGINE TEST COMPLETED")
    logger.info("=" * 80)


if __name__ == "__main__":
    # Run test
    try:
        asyncio.run(run_realtime_test())
    except KeyboardInterrupt:
        logger.info("\n\nTest interrupted by user")


# Backward-compat alias used by comprehensive_test_framework.py
MultiSourceAggregator = ConsensusAggregator
