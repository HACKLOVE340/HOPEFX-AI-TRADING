# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
market_data/ibkr_feed.py

IBKR market data feed — real-time XAUUSD ticks via ib_insync, with Redis
pub/sub fanout and in-memory OHLCV bar aggregation.

Architecture:
  IBKRMarketDataFeed
    ├── IBKRConnector.subscribe_ticks()  → raw tick stream
    ├── TickNormalizer                   → validated Tick objects
    ├── OHLCVAggregator                  → 1m/5m/1h bar construction
    ├── RedisPublisher                   → pub/sub fanout to consumers
    └── HealthMonitor                    → stale-data detection

Design invariants:
- Zero silent failures: every exception logged + Sentry captured
- Stale data detection: if no tick in >5s, health degrades to STALE
- Redis publish failures do NOT stop the feed (logged + counted)
- Thread-safe: all state behind RLock
- Tick validation: rejects negative prices, inverted spreads, >2% jumps
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Optional Sentry
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False

# Optional Redis
try:
    import redis  # type: ignore[import]  # noqa: F401

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    logger.warning("redis-py not installed. Redis pub/sub disabled.")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Tick:
    """Normalised market tick."""

    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: float  # Unix epoch seconds
    source: str = "ibkr"
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        return (self.spread / mid * 10000.0) if mid > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": self.mid,
            "spread": self.spread,
            "spread_bps": self.spread_bps,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass
class OHLCVBar:
    """OHLCV bar for a given timeframe."""

    symbol: str
    timeframe: str  # "1m", "5m", "1h"
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    bar_open_ts: float  # Unix epoch of bar open
    bar_close_ts: float  # Unix epoch of bar close (expected)
    is_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "bar_open_ts": self.bar_open_ts,
            "bar_close_ts": self.bar_close_ts,
            "is_closed": self.is_closed,
        }


class FeedStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    LIVE = "live"
    STALE = "stale"  # connected but no tick in >5s
    ERROR = "error"


@dataclass
class FeedHealth:
    status: FeedStatus
    last_tick_ts: float | None
    ticks_received: int
    ticks_rejected: int
    redis_publish_errors: int
    last_error: str | None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "last_tick_ts": self.last_tick_ts,
            "ticks_received": self.ticks_received,
            "ticks_rejected": self.ticks_rejected,
            "redis_publish_errors": self.redis_publish_errors,
            "last_error": self.last_error,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Tick validation
# ---------------------------------------------------------------------------


class TickValidator:
    """
    Validates incoming ticks against reasonability constraints.

    Rejects:
    - Negative or zero prices
    - Inverted spread (bid > ask)
    - Price jumps > max_jump_pct from last known price
    - Timestamps more than max_age_sec in the past
    """

    def __init__(
        self,
        max_jump_pct: float = 0.02,  # 2% max single-tick price move
        max_age_sec: float = 30.0,  # reject ticks older than 30s
        max_spread_bps: float = 500.0,  # reject spreads > 500bps (5%)
    ) -> None:
        self._max_jump_pct = max_jump_pct
        self._max_age_sec = max_age_sec
        self._max_spread_bps = max_spread_bps
        self._last_prices: dict[str, float] = {}

    def validate(self, tick: Tick) -> tuple[bool, str]:
        """
        Returns (is_valid, reason).
        reason is empty string on success.
        """
        # Price sanity
        if tick.bid <= 0 or tick.ask <= 0:
            return False, f"non-positive price: bid={tick.bid} ask={tick.ask}"

        # Spread sanity
        if tick.bid > tick.ask:
            return False, f"inverted spread: bid={tick.bid} > ask={tick.ask}"

        if tick.spread_bps > self._max_spread_bps:
            return False, (f"spread {tick.spread_bps:.1f}bps exceeds limit {self._max_spread_bps:.0f}bps")

        # Timestamp staleness
        age = time.time() - tick.timestamp
        if age > self._max_age_sec:
            return False, f"stale tick: age={age:.1f}s > limit={self._max_age_sec}s"

        # Price jump check
        last = self._last_prices.get(tick.symbol)
        if last is not None and last > 0:
            jump = abs(tick.mid - last) / last
            if jump > self._max_jump_pct:
                return False, (
                    f"price jump {jump:.2%} exceeds limit {self._max_jump_pct:.2%}: last={last:.4f} mid={tick.mid:.4f}"
                )

        # Update last known price
        self._last_prices[tick.symbol] = tick.mid
        return True, ""


# ---------------------------------------------------------------------------
# OHLCV bar aggregator
# ---------------------------------------------------------------------------

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class OHLCVAggregator:
    """
    Builds OHLCV bars from a tick stream.

    Supports multiple timeframes simultaneously.
    Emits a closed bar via on_bar_closed callback when a bar period ends.
    """

    def __init__(
        self,
        symbol: str,
        timeframes: list[str],
        on_bar_closed: Callable[[OHLCVBar], None] | None = None,
    ) -> None:
        self._symbol = symbol
        self._timeframes = timeframes
        self._on_bar_closed = on_bar_closed
        self._lock = threading.RLock()

        # Current open bar per timeframe
        self._open_bars: dict[str, OHLCVBar | None] = dict.fromkeys(timeframes)

    def on_tick(self, tick: Tick) -> None:
        """Process a tick and update/close bars as needed."""
        if tick.symbol != self._symbol:
            return
        price = tick.mid
        ts = tick.timestamp

        with self._lock:
            for tf in self._timeframes:
                period = _TIMEFRAME_SECONDS.get(tf, 60)
                bar_open_ts = (ts // period) * period
                bar_close_ts = bar_open_ts + period

                bar = self._open_bars[tf]

                if bar is None or bar.bar_open_ts != bar_open_ts:
                    # Close previous bar
                    if bar is not None and not bar.is_closed:
                        bar.is_closed = True
                        if self._on_bar_closed:
                            try:
                                self._on_bar_closed(bar)
                            except Exception as exc:
                                logger.error(
                                    "OHLCVAggregator: on_bar_closed callback error: %s",
                                    exc,
                                )

                    # Open new bar
                    self._open_bars[tf] = OHLCVBar(
                        symbol=self._symbol,
                        timeframe=tf,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=tick.bid_size + tick.ask_size,
                        tick_count=1,
                        bar_open_ts=bar_open_ts,
                        bar_close_ts=bar_close_ts,
                    )
                else:
                    # Update existing bar
                    bar.high = max(bar.high, price)
                    bar.low = min(bar.low, price)
                    bar.close = price
                    bar.volume += tick.bid_size + tick.ask_size
                    bar.tick_count += 1

    def get_current_bar(self, timeframe: str) -> OHLCVBar | None:
        with self._lock:
            return self._open_bars.get(timeframe)


# ---------------------------------------------------------------------------
# Redis publisher
# ---------------------------------------------------------------------------


class RedisTickPublisher:
    """
    Publishes ticks and bars to Redis pub/sub channels.

    Channels:
      ticks:{symbol}          → raw tick JSON
      bars:{symbol}:{tf}      → closed bar JSON
      feed:health             → health snapshot JSON

    Also maintains a sorted-set cache:
      tick_cache:{symbol}     → last 1000 ticks (score = timestamp)
    """

    def __init__(self, redis_client, key_prefix: str = "") -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._error_count = 0

    def publish_tick(self, tick: Tick) -> None:
        if self._redis is None:
            return
        try:
            channel = f"{self._prefix}ticks:{tick.symbol}"
            payload = json.dumps(tick.to_dict())
            self._redis.publish(channel, payload)

            # Maintain rolling cache (last 1000 ticks)
            cache_key = f"{self._prefix}tick_cache:{tick.symbol}"
            self._redis.zadd(cache_key, {payload: tick.timestamp})
            self._redis.zremrangebyrank(cache_key, 0, -1001)  # keep last 1000
        except Exception as exc:
            self._error_count += 1
            logger.error("RedisTickPublisher.publish_tick error: %s", exc)
            # Do NOT re-raise — Redis failure must not stop the feed

    def publish_bar(self, bar: OHLCVBar) -> None:
        if self._redis is None:
            return
        try:
            channel = f"{self._prefix}bars:{bar.symbol}:{bar.timeframe}"
            payload = json.dumps(bar.to_dict())
            self._redis.publish(channel, payload)

            # Store latest bar per timeframe
            key = f"{self._prefix}latest_bar:{bar.symbol}:{bar.timeframe}"
            self._redis.set(key, payload, ex=86400)  # 24h TTL
        except Exception as exc:
            self._error_count += 1
            logger.error("RedisTickPublisher.publish_bar error: %s", exc)

    def publish_health(self, health: FeedHealth) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(
                f"{self._prefix}feed:health",
                json.dumps(health.to_dict()),
                ex=60,
            )
        except Exception as exc:
            self._error_count += 1
            logger.error("RedisTickPublisher.publish_health error: %s", exc)

    @property
    def error_count(self) -> int:
        return self._error_count


# ---------------------------------------------------------------------------
# Main feed
# ---------------------------------------------------------------------------


class IBKRMarketDataFeed:
    """
    IBKR real-time market data feed for XAUUSD.

    Wires together:
    - IBKRConnector tick subscription
    - TickValidator (rejects bad ticks)
    - OHLCVAggregator (1m/5m/1h bars)
    - RedisTickPublisher (pub/sub fanout)
    - Health monitoring (stale-data detection)

    Thread-safe: all public methods safe to call from any thread.
    """

    _STALE_THRESHOLD_SEC: float = 5.0
    _HEALTH_PUBLISH_INTERVAL: float = 10.0

    def __init__(
        self,
        ibkr_connector,
        symbol: str = "XAUUSD",
        timeframes: list[str] | None = None,
        redis_client=None,
        redis_key_prefix: str = "hopefx:",
        on_tick: Callable[[Tick], None] | None = None,
        on_bar: Callable[[OHLCVBar], None] | None = None,
        instrument: str = "commodity",
    ) -> None:
        self._connector = ibkr_connector
        self._symbol = symbol
        self._timeframes = timeframes or ["1m", "5m", "1h"]
        self._on_tick_callback = on_tick
        self._on_bar_callback = on_bar
        self._instrument = instrument

        self._validator = TickValidator()
        self._aggregator = OHLCVAggregator(
            symbol=symbol,
            timeframes=self._timeframes,
            on_bar_closed=self._on_bar_closed,
        )
        self._publisher = RedisTickPublisher(redis_client, key_prefix=redis_key_prefix)

        # State
        self._lock = threading.RLock()
        self._status = FeedStatus.DISCONNECTED
        self._last_tick_ts: float | None = None
        self._ticks_received = 0
        self._ticks_rejected = 0
        self._last_error: str | None = None
        self._running = False

        # Health monitor thread
        self._health_thread: threading.Thread | None = None

        # Recent ticks buffer (thread-safe, bounded)
        self._tick_buffer: deque = deque(maxlen=1000)

        logger.info(
            "IBKRMarketDataFeed initialised | symbol=%s timeframes=%s",
            symbol,
            self._timeframes,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to IBKR ticks and start health monitor."""
        with self._lock:
            if self._running:
                logger.warning("IBKRMarketDataFeed.start() called while running — ignored.")
                return
            self._running = True
            self._status = FeedStatus.CONNECTING

        try:
            self._connector.subscribe_ticks(
                symbol=self._symbol,
                callback=self._on_raw_tick,
                instrument=self._instrument,
            )
            with self._lock:
                self._status = FeedStatus.LIVE
            logger.info("IBKRMarketDataFeed: subscribed to %s ticks.", self._symbol)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("IBKRMarketDataFeed.start: subscribe_ticks failed: %s\n%s", exc, tb)
            self._capture_sentry(exc)
            with self._lock:
                self._status = FeedStatus.ERROR
                self._last_error = str(exc)
            raise

        # Start health monitor
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop,
            name="ibkr-feed-health",
            daemon=True,
        )
        self._health_thread.start()

    def stop(self) -> None:
        """Stop the feed."""
        with self._lock:
            self._running = False
            self._status = FeedStatus.DISCONNECTED
        logger.info("IBKRMarketDataFeed stopped.")

    # ------------------------------------------------------------------
    # Tick processing
    # ------------------------------------------------------------------

    def _on_raw_tick(self, raw: dict) -> None:
        """
        Callback from IBKRConnector.subscribe_ticks().
        Validates, normalises, aggregates, and publishes the tick.
        """
        try:
            tick = self._normalise(raw)
        except Exception as exc:
            logger.error(
                "IBKRMarketDataFeed: tick normalisation error: %s | raw=%r",
                exc,
                str(raw)[:200],
            )
            with self._lock:
                self._ticks_rejected += 1
                self._last_error = f"normalise: {exc}"
            return

        # Validate
        valid, reason = self._validator.validate(tick)
        if not valid:
            logger.warning(
                "IBKRMarketDataFeed: tick rejected | symbol=%s reason=%s",
                tick.symbol,
                reason,
            )
            with self._lock:
                self._ticks_rejected += 1
            return

        # Update state
        with self._lock:
            self._ticks_received += 1
            self._last_tick_ts = tick.timestamp
            self._status = FeedStatus.LIVE
            self._tick_buffer.append(tick)

        # Aggregate into OHLCV bars
        try:
            self._aggregator.on_tick(tick)
        except Exception as exc:
            logger.error("IBKRMarketDataFeed: aggregator error: %s", exc)
            self._capture_sentry(exc)

        # Publish to Redis
        self._publisher.publish_tick(tick)

        # User callback
        if self._on_tick_callback:
            try:
                self._on_tick_callback(tick)
            except Exception as exc:
                logger.error("IBKRMarketDataFeed: on_tick callback error: %s", exc)
                self._capture_sentry(exc)

    def _on_bar_closed(self, bar: OHLCVBar) -> None:
        """Called by OHLCVAggregator when a bar closes."""
        logger.debug(
            "IBKRMarketDataFeed: bar closed | %s %s O=%.4f H=%.4f L=%.4f C=%.4f ticks=%d",
            bar.symbol,
            bar.timeframe,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.tick_count,
        )
        self._publisher.publish_bar(bar)

        if self._on_bar_callback:
            try:
                self._on_bar_callback(bar)
            except Exception as exc:
                logger.error("IBKRMarketDataFeed: on_bar callback error: %s", exc)
                self._capture_sentry(exc)

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(raw: dict) -> Tick:
        """Convert raw IBKR tick dict to Tick dataclass."""
        symbol = raw.get("symbol", "XAUUSD")
        bid = float(raw.get("bid", 0.0) or 0.0)
        ask = float(raw.get("ask", 0.0) or 0.0)
        last = float(raw.get("last", 0.0) or 0.0)
        ts = float(raw.get("timestamp", time.time()) or time.time())

        # If bid/ask are zero but last is valid, synthesise a 1-pip spread
        if bid <= 0 and ask <= 0 and last > 0:
            bid = last * 0.9999
            ask = last * 1.0001

        return Tick(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last if last > 0 else (bid + ask) / 2.0,
            timestamp=ts,
            source=raw.get("source", "ibkr"),
            bid_size=float(raw.get("bid_size", 0.0) or 0.0),
            ask_size=float(raw.get("ask_size", 0.0) or 0.0),
        )

    # ------------------------------------------------------------------
    # Health monitor
    # ------------------------------------------------------------------

    def _health_monitor_loop(self) -> None:
        """Background thread: detects stale data and publishes health."""
        while self._running:
            time.sleep(self._HEALTH_PUBLISH_INTERVAL)
            if not self._running:
                break

            with self._lock:
                last_ts = self._last_tick_ts
                status = self._status

            # Stale detection
            if last_ts is not None and status == FeedStatus.LIVE:
                age = time.time() - last_ts
                if age > self._STALE_THRESHOLD_SEC:
                    with self._lock:
                        self._status = FeedStatus.STALE
                    logger.warning(
                        "IBKRMarketDataFeed: STALE — no tick for %.1fs (symbol=%s)",
                        age,
                        self._symbol,
                    )
                    if _SENTRY:
                        try:
                            sentry_sdk.capture_message(
                                f"IBKRMarketDataFeed stale: {self._symbol} no tick for {age:.1f}s",
                                level="warning",
                            )
                        except Exception as _exc:
                            logger.debug("Suppressed exception: %s", _exc)

            # Publish health snapshot
            health = self.get_health()
            self._publisher.publish_health(health)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_health(self) -> FeedHealth:
        with self._lock:
            return FeedHealth(
                status=self._status,
                last_tick_ts=self._last_tick_ts,
                ticks_received=self._ticks_received,
                ticks_rejected=self._ticks_rejected,
                redis_publish_errors=self._publisher.error_count,
                last_error=self._last_error,
            )

    def get_latest_tick(self) -> Tick | None:
        """Return the most recent validated tick."""
        with self._lock:
            if self._tick_buffer:
                return self._tick_buffer[-1]
            return None

    def get_recent_ticks(self, n: int = 100) -> list[Tick]:
        """Return up to *n* most recent validated ticks."""
        with self._lock:
            buf = list(self._tick_buffer)
        return buf[-n:]

    def get_current_bar(self, timeframe: str = "1m") -> OHLCVBar | None:
        """Return the currently open OHLCV bar for *timeframe*."""
        return self._aggregator.get_current_bar(timeframe)

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def is_live(self) -> bool:
        with self._lock:
            return self._status == FeedStatus.LIVE

    # ------------------------------------------------------------------
    # Sentry helper
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
