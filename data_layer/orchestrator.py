# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/orchestrator.py
============================
MarketDataOrchestrator — the ONLY entry point for all market data.

Architecture
------------
No other module in this codebase is permitted to import directly from
individual feed adapters, quality engines, or sentiment feeds.
All data flows through this orchestrator.

Component wiring
----------------
  GoldFeedManager        → polls 5 gold price APIs, consensus tick
  DataQualityEngine      → validates every tick (anomaly, stale, jump)
  MicrostructureEngine   → bid/ask spread, OFI, Kyle's lambda, VWAP
  NewsSentimentEngine    → 5 news feeds, VADER scoring, EMA signal
  MacroCalendarEngine    → Finnhub calendar, gold impact scoring
  MacroStoreBridge       → FRED → MacroStore injection
  DataLayerRedisStore    → per-instrument TTL caching
  DataLineageStore       → immutable audit trail (SQLite WAL)
  NormalizationPipeline  → tick + OHLCV cleaning
  MarketReplayEngine     → Dukascopy historical replay

Public API (the only interface the rest of the codebase uses)
-------------------------------------------------------------
  orchestrator.get_latest_tick()          → Optional[GoldTick]
  orchestrator.get_ml_features(as_of)     → Dict[str, float]  (26+ features)
  orchestrator.get_current_gold_price()   → Optional[float]
  orchestrator.get_macro_impact_score()   → float
  orchestrator.is_blackout_window()       → bool
  orchestrator.get_quality_report()       → QualityReport
  orchestrator.health()                   → Dict[str, Any]
  orchestrator.start()                    → coroutine
  orchestrator.stop()                     → coroutine

ML features produced (26 total)
---------------------------------
  Microstructure (16):  micro_spread, micro_spread_pct, micro_spread_z,
                        micro_spread_ema_fast, micro_spread_ema_slow,
                        micro_volume_delta, micro_cumulative_delta,
                        micro_buy_pressure, micro_sell_pressure, micro_ofi,
                        micro_trade_pressure, micro_depth_imbalance,
                        micro_vwap_dev, micro_kyles_lambda,
                        micro_delta_divergence, micro_absorption

  Sentiment (4):        news_sentiment_score, news_sentiment_momentum,
                        news_article_count_1h, news_bullish_ratio

  Macro calendar (6):   macro_impact_score_now, macro_hours_to_next_high,
                        macro_hours_since_last_high, macro_surprise_last,
                        macro_high_event_count_24h, macro_is_blackout

  Tick quality (3):     tick_confidence, tick_spread_pct, tick_source_count

  FRED macro (varies):  macro_dxy, macro_us10y, macro_us2y, macro_vix, ...
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import sys
from datetime import datetime

if sys.version_info >= (3, 11):
    from datetime import UTC
else:
    from datetime import timezone

    UTC = timezone.utc
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# ── Component imports ─────────────────────────────────────────────────────────
import contextlib

from data_layer.cache.redis_store import DataLayerRedisStore, dl_redis_store
from data_layer.calendar.engine import MacroCalendarEngine, macro_calendar_engine
from data_layer.feeds.gold.manager import GoldFeedManager
from data_layer.feeds.macro.store_bridge import MacroStoreBridge, macro_store_bridge
from data_layer.feeds.macro.cftc_cot import CFTCCOTFeed, cot_feed
from data_layer.feeds.macro.imf_gold import IMFGoldFeed, imf_gold_feed
from data_layer.feeds.macro.yahoo_macro import YahooMacroFeed, yahoo_macro_feed
from data_layer.lineage.store import DataLineageStore, lineage_store
from data_layer.microstructure.engine import MicrostructureEngine, microstructure_engine
from data_layer.normalization.pipeline import (
    NormalizationPipeline,
    normalization_pipeline,
)
from data_layer.quality.engine import DataQualityEngine, dqe
from data_layer.replay.engine import MarketReplayEngine, market_replay_engine
from data_layer.sentiment.engine import NewsSentimentEngine, news_sentiment_engine
from data_layer.types import FeedSource, GoldTick, QualityReport, TickQuality

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_CB_FAILURE_THRESHOLD = int(os.getenv("ORCHESTRATOR_CB_FAILURES", "5"))
_CB_RECOVERY_TIMEOUT_S = float(os.getenv("ORCHESTRATOR_CB_RECOVERY_S", "30.0"))
_WS_BROADCAST_QUEUE_SIZE = int(os.getenv("ORCHESTRATOR_WS_QUEUE", "256"))


class _CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — calls rejected
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Per-component circuit breaker.

    States:
      CLOSED    → normal; failures counted
      OPEN      → component is failing; calls rejected immediately
      HALF_OPEN → one probe call allowed; success → CLOSED, failure → OPEN

    Parameters
    ----------
    name              : Component name for logging
    failure_threshold : Consecutive failures before opening (default 5)
    recovery_timeout  : Seconds in OPEN before moving to HALF_OPEN (default 30)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = _CB_FAILURE_THRESHOLD,
        recovery_timeout: float = _CB_RECOVERY_TIMEOUT_S,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = _CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_ts = 0.0
        self._success_count = 0
        self._total_calls = 0
        self._total_failures = 0

    @property
    def state(self) -> _CircuitState:
        if self._state == _CircuitState.OPEN and time.monotonic() - self._last_failure_ts >= self._recovery_timeout:
            self._state = _CircuitState.HALF_OPEN
            logger.info("CircuitBreaker[%s]: OPEN → HALF_OPEN (probe allowed)", self.name)
        return self._state

    def is_open(self) -> bool:
        return self.state == _CircuitState.OPEN

    def allow_call(self) -> bool:
        """Return True if the call should be allowed through."""
        s = self.state
        return s in (_CircuitState.CLOSED, _CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self._total_calls += 1
        self._success_count += 1
        if self._state == _CircuitState.HALF_OPEN:
            self._state = _CircuitState.CLOSED
            self._failure_count = 0
            logger.info("CircuitBreaker[%s]: HALF_OPEN → CLOSED (recovery confirmed)", self.name)
        elif self._state == _CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self, exc: Exception | None = None) -> None:
        self._total_calls += 1
        self._total_failures += 1
        self._failure_count += 1
        self._last_failure_ts = time.monotonic()
        if self._state in (_CircuitState.CLOSED, _CircuitState.HALF_OPEN) and self._failure_count >= self._threshold:
            self._state = _CircuitState.OPEN
            logger.warning(
                "CircuitBreaker[%s]: → OPEN after %d failures (last: %s)",
                self.name,
                self._failure_count,
                exc,
            )

    def reset(self) -> None:
        self._state = _CircuitState.CLOSED
        self._failure_count = 0
        logger.info("CircuitBreaker[%s]: manually reset to CLOSED", self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "success_count": self._success_count,
        }


class _WebSocketBroadcaster:
    """
    Async WebSocket broadcast integration for the orchestrator.

    Maintains a set of active WebSocket connections and fans out
    tick/microstructure/sentiment messages to all of them.

    Connections are registered via add_connection() and removed
    automatically when they close (send raises an exception).

    Uses an asyncio.Queue to decouple the synchronous _on_tick()
    path from the async broadcast loop — no blocking in the hot path.
    """

    def __init__(self, queue_size: int = _WS_BROADCAST_QUEUE_SIZE) -> None:
        self._connections: set = set()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dropped = 0
        self._sent = 0

    def add_connection(self, ws: Any) -> None:
        self._connections.add(ws)
        logger.debug("WebSocketBroadcaster: connection added (%d total)", len(self._connections))

    def remove_connection(self, ws: Any) -> None:
        self._connections.discard(ws)
        logger.debug("WebSocketBroadcaster: connection removed (%d total)", len(self._connections))

    def enqueue(self, message: str) -> None:
        """Non-blocking enqueue from sync context. Drops if queue is full.

        asyncio.Queue is bound to a single event loop and is NOT thread-safe.
        _on_tick may run on a feed/executor thread, so when called off the loop
        thread we hand the put_nowait to the loop via call_soon_threadsafe rather
        than mutating the queue directly (which can corrupt its internal state).
        """
        loop = self._loop
        if loop is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                # Called from another thread (or no running loop) — schedule on
                # the broadcaster's loop thread.
                loop.call_soon_threadsafe(self._enqueue_on_loop, message)
                return
        self._enqueue_on_loop(message)

    def _enqueue_on_loop(self, message: str) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            self._dropped += 1

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._broadcast_loop(), name="ws_broadcast")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                message = await self._queue.get()
                dead = set()
                for ws in list(self._connections):
                    try:
                        await ws.send_text(message)
                        self._sent += 1
                    except Exception:
                        dead.add(ws)
                for ws in dead:
                    self._connections.discard(ws)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("WebSocketBroadcaster loop error: %s", exc)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def stats(self) -> dict[str, Any]:
        return {
            "connections": self.connection_count,
            "queue_size": self._queue.qsize(),
            "sent": self._sent,
            "dropped": self._dropped,
        }


class MarketDataOrchestrator:
    """
    Central coordinator for all market data.

    Lifecycle:
        orch = MarketDataOrchestrator()
        await orch.start()
        tick = orch.get_latest_tick()
        await orch.stop()
    """

    def __init__(self) -> None:
        # Redis client (shared across all components)
        self._redis = None
        self._redis_store: DataLayerRedisStore = dl_redis_store
        # Track Redis availability so health() and degraded-mode alerting work.
        self._redis_healthy: bool = False

        # Core components
        self._gold_feed: GoldFeedManager | None = None
        self._dqe: DataQualityEngine = dqe
        self._micro: MicrostructureEngine = microstructure_engine
        self._sentiment: NewsSentimentEngine = news_sentiment_engine
        self._calendar: MacroCalendarEngine = macro_calendar_engine
        self._macro_bridge: MacroStoreBridge = macro_store_bridge
        self._cot_feed: CFTCCOTFeed = cot_feed
        self._imf_feed: IMFGoldFeed = imf_gold_feed
        self._yahoo_macro: YahooMacroFeed = yahoo_macro_feed
        self._lineage: DataLineageStore = lineage_store
        self._norm: NormalizationPipeline = normalization_pipeline
        self._replay: MarketReplayEngine = market_replay_engine

        self._started = False
        self._start_ts = 0.0
        self._tick_count = 0

        # Background task handle — tracked so stop() can cancel it immediately
        self._uptime_task: asyncio.Task | None = None

        # Tick subscriber callbacks: name → Callable[[GoldTick], None]
        # Registered via subscribe_ticks(); called on every accepted tick.
        self._tick_callbacks: dict[str, Any] = {}

        # Async tick subscriber callbacks: name → Coroutine[[GoldTick], None]
        # Called via asyncio.create_task() — non-blocking fanout
        self._async_tick_callbacks: dict[str, Any] = {}

        # Per-component circuit breakers
        self._cb: dict[str, CircuitBreaker] = {
            "gold_feed": CircuitBreaker("gold_feed"),
            "dqe": CircuitBreaker("dqe"),
            "microstructure": CircuitBreaker("microstructure"),
            "sentiment": CircuitBreaker("sentiment"),
            "calendar": CircuitBreaker("calendar"),
            "macro_bridge": CircuitBreaker("macro_bridge"),
            "lineage": CircuitBreaker("lineage"),
            "redis": CircuitBreaker("redis"),
        }

        # WebSocket broadcaster
        self._ws_broadcaster = _WebSocketBroadcaster()

        # Prometheus
        self._prom_uptime = None
        self._prom_tick_rate = None
        self._prom_cb_open = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import REGISTRY, Counter, Gauge

            def _gauge(name: str, doc: str):
                try:
                    return Gauge(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _counter(name: str, doc: str):
                try:
                    return Counter(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            self._prom_uptime = _gauge(
                "hopefx_orchestrator_uptime_s",
                "Orchestrator uptime in seconds",
            )
            self._prom_tick_rate = _counter(
                "hopefx_orchestrator_ticks_total",
                "Total ticks processed by orchestrator",
            )
            self._prom_cb_open = _gauge(
                "hopefx_orchestrator_circuit_breakers_open",
                "Number of open circuit breakers",
            )
        except Exception as _exc:
            logger.debug("MarketDataOrchestrator: Prometheus init skipped: %s", _exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start all data layer components in dependency order.

        Order:
          1. Redis connection
          2. DataLineageStore (SQLite WAL)
          3. GoldFeedManager (price feeds)
          4. NewsSentimentEngine (news feeds)
          5. MacroCalendarEngine (economic calendar)
          6. MacroStoreBridge (FRED → MacroStore)
        """
        if self._started:
            logger.warning("MarketDataOrchestrator: already started")
            return

        logger.info("MarketDataOrchestrator: starting...")

        # 1. Redis
        try:
            import redis as redis_lib

            r = redis_lib.from_url(_REDIS_URL, decode_responses=False)
            r.ping()
            self._redis = r
            self._redis_store._r = r
            self._calendar._redis = r
            self._redis_healthy = True
            logger.info("MarketDataOrchestrator: Redis connected (%s)", _REDIS_URL)
        except Exception as exc:
            self._redis_healthy = False
            # Warn (not error) — degraded mode is expected in dev/offline environments.
            logger.warning(
                "MarketDataOrchestrator: Redis UNAVAILABLE (%s) — caching disabled. "
                "Trading continues in degraded mode (no tick cache, no kill-switch propagation). "
                "Set REDIS_URL and ensure Redis is running to restore full functionality.",
                exc,
            )

        # 2. Lineage store
        try:
            self._lineage.start()
            self._sentiment._lineage = self._lineage
            logger.info("MarketDataOrchestrator: DataLineageStore started")
        except Exception as exc:
            # Non-fatal — lineage is an audit trail, not a trading dependency.
            logger.warning("MarketDataOrchestrator: lineage store error: %s", exc)

        # 3. Gold feed manager
        try:
            self._gold_feed = GoldFeedManager(redis_client=self._redis)
            await self._gold_feed.start()
            logger.info("MarketDataOrchestrator: GoldFeedManager started")
        except Exception as exc:
            logger.error("MarketDataOrchestrator: GoldFeedManager error: %s", exc)

        # 4. News sentiment engine
        try:
            self._sentiment._redis = self._redis
            await self._sentiment.start()
            logger.info("MarketDataOrchestrator: NewsSentimentEngine started")
        except Exception as exc:
            logger.warning("MarketDataOrchestrator: sentiment engine error: %s", exc)

        # 5. Macro calendar
        try:
            self._calendar._redis = self._redis
            await self._calendar.start()
            logger.info("MarketDataOrchestrator: MacroCalendarEngine started")
        except Exception as exc:
            logger.warning("MarketDataOrchestrator: calendar engine error: %s", exc)

        # Feed startup timeout — prevents blocking startup when external APIs
        # are unreachable (CFTC, IMF, FRED, WGC, Yahoo).  Each feed has its
        # own retry logic; the timeout here is a hard cap so the orchestrator
        # never blocks the HTTP server from accepting connections.
        _FEED_TIMEOUT = float(os.getenv("ORCHESTRATOR_FEED_TIMEOUT_S", "15.0"))

        # 6. FRED → MacroStore bridge
        # Timeouts on feeds 6-9 are expected in offline/dev environments.
        # Each feed injects zero-filled neutral series so ML features are never
        # NaN.  Log at INFO (not WARNING) — degraded mode is handled gracefully.
        try:
            await asyncio.wait_for(self._macro_bridge.start(), timeout=_FEED_TIMEOUT)
            logger.info("MarketDataOrchestrator: MacroStoreBridge started")
        except TimeoutError:
            logger.info(
                "MarketDataOrchestrator: MacroStoreBridge timed out after %.0fs "
                "— macro features degraded (FRED unreachable, neutral series injected)",
                _FEED_TIMEOUT,
            )
        except Exception as exc:
            logger.info("MarketDataOrchestrator: macro bridge error: %s", exc)

        # 7. CFTC COT feed — real gold futures positioning (free, weekly)
        try:
            await asyncio.wait_for(self._cot_feed.start(), timeout=_FEED_TIMEOUT)
            logger.info("MarketDataOrchestrator: CFTCCOTFeed started")
        except TimeoutError:
            logger.info(
                "MarketDataOrchestrator: CFTCCOTFeed timed out after %.0fs "
                "— COT features zero-filled (CFTC unreachable)",
                _FEED_TIMEOUT,
            )
        except Exception as exc:
            logger.info("MarketDataOrchestrator: COT feed error: %s", exc)

        # 8. IMF central bank gold reserves (free, monthly)
        try:
            await asyncio.wait_for(self._imf_feed.start(), timeout=_FEED_TIMEOUT)
            logger.info("MarketDataOrchestrator: IMFGoldFeed started")
        except TimeoutError:
            logger.info(
                "MarketDataOrchestrator: IMFGoldFeed timed out after %.0fs "
                "— IMF features zero-filled (dataservices.imf.org unreachable)",
                _FEED_TIMEOUT,
            )
        except Exception as exc:
            logger.info("MarketDataOrchestrator: IMF feed error: %s", exc)

        # 9. Yahoo Finance cross-asset macro (SPX, GLD, copper, oil, USDCNY)
        try:
            await asyncio.wait_for(self._yahoo_macro.start(), timeout=_FEED_TIMEOUT)
            logger.info("MarketDataOrchestrator: YahooMacroFeed started")
        except TimeoutError:
            logger.info(
                "MarketDataOrchestrator: YahooMacroFeed timed out after %.0fs "
                "— Yahoo macro features zero-filled (Yahoo Finance unreachable)",
                _FEED_TIMEOUT,
            )
        except Exception as exc:
            logger.info("MarketDataOrchestrator: Yahoo macro feed error: %s", exc)

        # 10. Ensure macro CSV fallback is loaded so features are never zero at startup
        #    at startup even without a FRED key or network access.
        try:
            from ml.macro_store import macro_store as _ms

            if len(_ms) == 0:
                self._macro_bridge._load_csv_fallback()
                logger.info(
                    "MarketDataOrchestrator: macro CSV fallback loaded (%d series)",
                    len(_ms),
                )
        except Exception as exc:
            logger.debug("MarketDataOrchestrator: macro CSV fallback error: %s", exc)

        self._started = True
        self._start_ts = time.time()

        # Start uptime/health reporter — track task so stop() can cancel it
        self._uptime_task = asyncio.create_task(self._uptime_loop(), name="orchestrator_uptime")

        # Start WebSocket broadcaster
        await self._ws_broadcaster.start()

        logger.info("MarketDataOrchestrator: all components started")

    async def stop(self) -> None:
        """
        Gracefully stop all components in reverse startup order.

        Order:
          1. MacroStoreBridge (FRED HTTP sessions)
          2. MacroCalendarEngine (Finnhub HTTP sessions)
          3. NewsSentimentEngine (all news HTTP sessions)
          4. GoldFeedManager (all price feed HTTP sessions)
          5. DataLineageStore (flush queue, close SQLite)
        """
        # 1. COT feed
        try:
            await self._cot_feed.stop()
        except Exception as exc:
            logger.debug("CFTCCOTFeed stop error: %s", exc)

        # 1b. IMF feed
        try:
            await self._imf_feed.stop()
        except Exception as exc:
            logger.debug("IMFGoldFeed stop error: %s", exc)

        # 1c. Yahoo macro feed
        try:
            await self._yahoo_macro.stop()
        except Exception as exc:
            logger.debug("YahooMacroFeed stop error: %s", exc)

        # 2. Macro bridge (FRED sessions)
        try:
            await self._macro_bridge.stop()
        except Exception as exc:
            logger.debug("MacroStoreBridge stop error: %s", exc)

        # 2. Calendar engine
        try:
            await self._calendar.stop()
        except Exception as exc:
            logger.debug("MacroCalendarEngine stop error: %s", exc)

        # 3. Sentiment engine
        if self._sentiment:
            try:
                await self._sentiment.stop()
            except Exception as exc:
                logger.debug("NewsSentimentEngine stop error: %s", exc)

        # 4. Gold feed manager
        if self._gold_feed:
            try:
                await self._gold_feed.stop()
            except Exception as exc:
                logger.debug("GoldFeedManager stop error: %s", exc)

        # 5. Lineage store — flush remaining records before closing
        try:
            self._lineage.flush()
            self._lineage.stop()
        except Exception as exc:
            logger.debug("DataLineageStore stop error: %s", exc)

        # 6. Cancel background uptime/health task immediately (don't wait 10s)
        if self._uptime_task and not self._uptime_task.done():
            self._uptime_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._uptime_task
            self._uptime_task = None

        # 7. Stop WebSocket broadcaster
        await self._ws_broadcaster.stop()

        self._started = False
        logger.info("MarketDataOrchestrator: stopped")

    async def _uptime_loop(self) -> None:
        """
        Background loop: update Prometheus uptime gauge and push health snapshot
        to Redis every 10 seconds for monitoring dashboards and alerting.
        Cancelled cleanly by stop() via task.cancel().
        """
        import json as _json

        _health_push_interval = 10.0
        try:
            while self._started:
                if self._prom_uptime:
                    try:
                        self._prom_uptime.set(time.time() - self._start_ts)
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)

                # Push health snapshot to Redis (TTL 30s) for dashboards/alerting.
                # Run in executor — self._redis is a sync client.
                if self._redis_store._r:
                    try:
                        h = self.health()
                        payload = _json.dumps(h, default=str)
                        _r = self._redis_store._r
                        await asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda: _r.setex("hopefx:dl:orchestrator_health", 30, payload),
                        )
                    except Exception as _exc:
                        logger.debug("Orchestrator health push error: %s", _exc)

                await asyncio.sleep(_health_push_interval)
        except asyncio.CancelledError:
            logger.debug("MarketDataOrchestrator: _uptime_loop cancelled")

    # ── Primary data access ───────────────────────────────────────────────────

    def get_latest_tick(self, symbol: str = "XAU_USD") -> GoldTick | None:
        """
        Return the latest validated, normalised gold tick.

        Checks Redis cache first, then falls back to in-memory GoldFeedManager.
        """
        # Try Redis cache
        if self._redis_store._r:
            cached = self._redis_store.get_tick(symbol)
            if cached:
                try:
                    # Require source to be present and a known FeedSource value.
                    # Missing or unrecognised source → fall through to live feed
                    # rather than labelling the tick with a fabricated origin.
                    raw_source = cached.get("source")
                    if not raw_source:
                        raise ValueError(f"Cached tick for {symbol} has no 'source' field")
                    tick = GoldTick(
                        symbol=cached["symbol"],
                        timestamp=datetime.fromisoformat(cached["timestamp"]),
                        bid=cached["bid"],
                        ask=cached["ask"],
                        mid=cached["mid"],
                        source=FeedSource(raw_source),
                        quality=TickQuality(cached.get("quality", "good")),
                        confidence=cached.get("confidence", 1.0),
                        spread=cached.get("spread", 0.0),
                        lineage_id=cached.get("lineage_id", ""),
                    )
                    # Freshness gate: never serve a stale OR future-dated cached
                    # tick as the live price. Match the DQE stale threshold (the
                    # previous 2x buffer re-served as "good" a tick the quality
                    # engine would mark STALE). A future timestamp (negative age
                    # beyond a small clock-skew tolerance) signals upstream clock
                    # skew or a parse error and must never be treated as live —
                    # otherwise its negative age trivially passes the upper bound.
                    _max_age_s = float(os.getenv("DQE_STALE_THRESHOLD_S", "30.0"))
                    _skew_tol_s = float(os.getenv("TICK_FUTURE_SKEW_TOLERANCE_S", "5.0"))
                    _age_s = (datetime.now(UTC) - tick.timestamp).total_seconds()
                    if -_skew_tol_s <= _age_s <= _max_age_s:
                        return tick
                    logger.debug(
                        "Orchestrator: cached tick for %s age=%.1fs outside [%.1f, %.1f]s — discarding",
                        symbol,
                        _age_s,
                        -_skew_tol_s,
                        _max_age_s,
                    )
                except Exception as exc:
                    logger.debug(
                        "Orchestrator: discarding cached tick for %s: %s",
                        symbol,
                        exc,
                    )

        # Fall back to in-memory
        if self._gold_feed:
            tick = self._gold_feed.get_latest_tick()
            if tick:
                # Normalise and cache
                tick = self._norm.normalize_tick(tick)
                self._on_tick(tick)
                return tick

        return None

    def _on_tick(self, tick: GoldTick) -> None:
        """
        Side-effects on every tick: microstructure, cache, lineage, fanout.

        Uses per-component circuit breakers to isolate failures.
        Fans out to all registered sync and async tick subscribers.
        Enqueues WebSocket broadcast message (non-blocking).
        """
        import json as _json

        # ── Microstructure (circuit-breaker guarded) ──────────────────────
        snap = None
        cb_micro = self._cb["microstructure"]
        if cb_micro.allow_call():
            try:
                snap = self._micro.on_tick(tick)
                cb_micro.record_success()
            except Exception as exc:
                cb_micro.record_failure(exc)
                logger.debug("Orchestrator: microstructure error: %s", exc)

        # ── Redis cache (circuit-breaker guarded) ─────────────────────────
        cb_redis = self._cb["redis"]
        if self._redis_store._r and cb_redis.allow_call():
            try:
                tick_dict = {
                    "symbol": tick.symbol,
                    "timestamp": tick.timestamp.isoformat(),
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "mid": tick.mid,
                    "source": tick.source.value,
                    "quality": tick.quality.value,
                    "confidence": tick.confidence,
                    "spread": tick.spread,
                    "lineage_id": tick.lineage_id,
                    "epoch": tick.timestamp.timestamp(),
                }
                self._redis_store.set_tick(tick.symbol, tick_dict, broadcast=True)
                cb_redis.record_success()

                # Cache microstructure snapshot
                if snap:
                    self._redis_store.set_microstructure(
                        tick.symbol,
                        {
                            "spread": snap.spread,
                            "spread_pct": snap.spread_pct,
                            "volume_delta": snap.volume_delta,
                            "cumulative_delta": snap.cumulative_delta,
                            "buy_pressure": snap.buy_pressure,
                            "sell_pressure": snap.sell_pressure,
                            "order_flow_imbalance": snap.order_flow_imbalance,
                            "trade_pressure": snap.trade_pressure,
                            "depth_imbalance": snap.depth_imbalance,
                            "vwap": snap.vwap,
                            "tick_count": snap.tick_count,
                            "timestamp": snap.timestamp.isoformat(),
                        },
                        broadcast=False,
                    )
            except Exception as exc:
                cb_redis.record_failure(exc)
                logger.debug("Orchestrator: Redis cache error: %s", exc)

        # ── Lineage (circuit-breaker guarded) ─────────────────────────────
        cb_lineage = self._cb["lineage"]
        if tick.quality != TickQuality.REJECTED and cb_lineage.allow_call():
            try:
                self._lineage.record_tick(tick)
                cb_lineage.record_success()
            except Exception as exc:
                cb_lineage.record_failure(exc)
                logger.debug("Orchestrator: lineage record_tick error: %s", exc)

        self._tick_count += 1
        if self._prom_tick_rate:
            with contextlib.suppress(Exception):
                self._prom_tick_rate.inc()

        # Update circuit breaker Prometheus gauge
        if self._prom_cb_open:
            with contextlib.suppress(Exception):
                open_count = sum(1 for cb in self._cb.values() if cb.is_open())
                self._prom_cb_open.set(open_count)

        # ── WebSocket broadcast (non-blocking enqueue) ────────────────────
        try:
            ws_msg = _json.dumps(
                {
                    "type": "tick",
                    "symbol": tick.symbol,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "mid": tick.mid,
                    "spread": tick.spread,
                    "source": tick.source.value,
                    "quality": tick.quality.value,
                    "timestamp": tick.timestamp.isoformat(),
                }
            )
            self._ws_broadcaster.enqueue(ws_msg)
        except Exception as exc:
            logger.debug("Orchestrator: WS broadcast enqueue error: %s", exc)

        # ── Sync tick subscriber fanout ───────────────────────────────────
        for _name, _cb in list(self._tick_callbacks.items()):
            try:
                _cb(tick)
            except Exception as _exc:
                logger.debug("Orchestrator: tick callback %s error: %s", _name, _exc)

        # ── Async tick subscriber fanout (fire-and-forget) ────────────────
        for _name, _coro_fn in list(self._async_tick_callbacks.items()):
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    asyncio.create_task(_coro_fn(tick), name=f"tick_cb_{_name}")
            except Exception as _exc:
                logger.debug("Orchestrator: async tick callback %s error: %s", _name, _exc)

    # ── ML feature aggregation ────────────────────────────────────────────────

    def get_ml_features(
        self,
        as_of: datetime | None = None,
        symbol: str = "XAU_USD",
    ) -> dict[str, float]:
        """
        Return all 26+ ML features from the data layer.

        Parameters
        ----------
        as_of  : Causal cutoff — only use data available at this time.
                 Passed to sentiment and calendar sub-components.
                 Microstructure features are always computed from past ticks.
        symbol : Instrument symbol (default "XAU_USD"). Currently only
                 XAU_USD is supported; parameter accepted for API compatibility.

        Causal guarantee (IMPORTANT — partial):
          - HONORED by `as_of`: sentiment, macro calendar, temporal features.
          - NOT honored (always reflect CURRENT live state): microstructure,
            tick-quality, and FRED macro features. These read the live rolling
            window / latest tick and are NOT point-in-time reconstructed.

        Consequently, calling this with a PAST `as_of` (replay / training-row
        construction) leaks present-time micro/tick/macro data into a row labeled
        causal — look-ahead bias. Do NOT use the micro/tick/macro features in a
        causal training or walk-forward pipeline. A warning is emitted whenever
        `as_of` is supplied so such misuse is not silent.

        Returns empty dict on error — never raises.
        """
        features: dict[str, float] = {}

        if as_of is not None:
            logger.warning(
                "get_ml_features(as_of=%s): microstructure, tick-quality and FRED "
                "macro features are LIVE (not causally filtered) — do not use them "
                "in causal training/backtest rows (look-ahead bias).",
                as_of,
            )

        # 1. Microstructure (16 features) — NOTE: live window, not causal.
        try:
            features.update(self._micro.get_ml_features())
        except Exception as exc:
            logger.debug("Orchestrator: micro features error: %s", exc)

        # 2. Sentiment (4 features)
        try:
            features.update(self._sentiment.get_ml_features(as_of=as_of))
        except Exception as exc:
            logger.debug("Orchestrator: sentiment features error: %s", exc)

        # 3. Macro calendar (6 features)
        try:
            features.update(self._calendar.get_ml_features(as_of=as_of))
        except Exception as exc:
            logger.debug("Orchestrator: calendar features error: %s", exc)

        # 4. FRED macro features (varies — typically 8-12)
        try:
            features.update(self._macro_bridge.get_ml_features())
        except Exception as exc:
            logger.debug("Orchestrator: macro bridge features error: %s", exc)

        # 5. Tick quality features (3)
        try:
            tick = self.get_latest_tick()
            if tick:
                features["tick_confidence"] = tick.confidence
                features["tick_spread_pct"] = tick.spread / tick.mid * 100.0 if tick.mid > 0 else 0.0
                # bid_ask_spread in absolute USD terms (not percentage)
                features["bid_ask_spread"] = tick.spread
            else:
                features["tick_confidence"] = 0.0
                features["tick_spread_pct"] = 0.0
                features["bid_ask_spread"] = 0.0

            if self._gold_feed:
                features["tick_source_count"] = float(len(self._gold_feed.active_sources()))
            else:
                features["tick_source_count"] = 0.0
        except Exception as exc:
            logger.debug("Orchestrator: tick quality features error: %s", exc)

        # 6. Temporal features — session_time and day_of_week
        # These are causal: computed from the as_of timestamp (or now).
        try:
            ref_time = as_of if as_of is not None else datetime.now(UTC)
            # session_time: fraction of the 24h UTC day elapsed [0, 1)
            # Used by the ML model to capture intraday seasonality
            # (gold is most liquid during London/NY overlap 13:00-17:00 UTC)
            seconds_since_midnight = (
                ref_time.hour * 3600 + ref_time.minute * 60 + ref_time.second + ref_time.microsecond / 1_000_000
            )
            features["session_time"] = round(seconds_since_midnight / 86400.0, 6)

            # day_of_week: 0=Monday … 6=Sunday, normalised to [0, 1)
            # Captures weekly seasonality (gold often weaker on Fridays
            # as traders reduce risk ahead of the weekend)
            features["day_of_week"] = round(ref_time.weekday() / 7.0, 6)

            # is_weekend: 1.0 on Saturday/Sunday (gold market closed)
            features["is_weekend"] = 1.0 if ref_time.weekday() >= 5 else 0.0

            # hour_of_day: raw hour [0, 23] for tree-based models that
            # can learn non-linear hour effects without normalisation
            features["hour_of_day"] = float(ref_time.hour)
        except Exception as exc:
            logger.debug("Orchestrator: temporal features error: %s", exc)

        return features

    # ── Convenience accessors ─────────────────────────────────────────────────

    def get_microstructure_snapshot(self) -> object | None:
        """Return the current MicrostructureSnapshot, or None if unavailable.

        Provides a stable public API so callers do not need to access the
        private ``_micro`` attribute directly.
        """
        try:
            return self._micro.get_snapshot()
        except Exception as exc:
            logger.debug("get_microstructure_snapshot: %s", exc)
            return None

    def get_sentiment_snapshot(self) -> dict | None:
        """Return a serialisable sentiment snapshot for WebSocket broadcast.

        Combines ML feature signals with recent article data into the shape
        expected by the frontend SentimentGauge component.  Returns None when
        the sentiment engine is not yet initialised.
        """
        try:
            if self._sentiment is None:
                return None
            features = self.get_ml_features()
            sentiment_features = {k: v for k, v in features.items() if k.startswith("news_")}
            articles: list[dict] = []
            try:
                raw_articles = self._sentiment.get_recent_articles(hours=1.0, min_relevance=0.1)
                articles = [
                    {
                        "headline": getattr(a, "title", getattr(a, "headline", "")),
                        "source": getattr(a, "source", ""),
                        "sentiment_score": getattr(a, "sentiment_score", 0.0),
                        "sentiment_label": getattr(a, "sentiment_label", "neutral"),
                        "published_at": (a.published_at.isoformat() if getattr(a, "published_at", None) else None),
                        "url": getattr(a, "url", None),
                    }
                    for a in (raw_articles or [])[:5]
                ]
            except Exception as _fmt_exc:
                logger.debug("get_sentiment_snapshot: article serialisation skipped: %s", _fmt_exc)
            return {"signal": sentiment_features, "recent_articles": articles}
        except Exception as exc:
            logger.debug("get_sentiment_snapshot: %s", exc)
            return None

    def get_current_gold_price(self) -> float | None:
        """Return current consensus gold mid price, or None if unavailable."""
        tick = self.get_latest_tick()
        return tick.mid if tick else None

    def get_macro_impact_score(self) -> float:
        """Return current macro calendar impact score [0, 1]."""
        try:
            return self._calendar.get_current_impact_score()
        except Exception:
            return 0.0

    def is_blackout_window(self) -> bool:
        """True if within a HIGH-impact event blackout window."""
        try:
            return self._calendar.is_blackout_window()
        except Exception:
            return False

    def is_safe_to_trade(self) -> bool:
        """
        Return True if conditions are safe for live trading.

        Checks:
          1. At least one gold feed is alive and returning valid ticks
          2. Not in a macro event blackout window
          3. Latest tick confidence >= 0.30
        """
        # Check blackout
        if self.is_blackout_window():
            return False

        # Check tick quality. No tick means no live price — fail CLOSED: a
        # missing tick must NOT be treated as safe to trade.
        tick = self.get_latest_tick()
        if tick is None:
            return False
        if tick.confidence < 0.30:
            return False

        # No active sources — but only block if we've been running > 30s
        feed_stalled = (
            self._gold_feed
            and not self._gold_feed.active_sources()
            and self._started
            and (time.time() - self._start_ts) > 30.0
        )
        return not feed_stalled

    def get_ohlcv(
        self,
        symbol: str = "XAU_USD",
        bars: int = 150,
        timeframe: str = "H1",
    ) -> pd.DataFrame | None:
        """
        Return the last ``bars`` closed OHLCV bars as a DataFrame.

        Delegates to the OHLCVStore (Redis + ring buffer).  Returns None
        when fewer than ``bars`` are available — callers must handle this.
        """
        try:
            from brokers.ohlcv_store import get_ohlcv_store

            return get_ohlcv_store(timeframe=timeframe).get(symbol, bars=bars)
        except Exception as exc:
            logger.debug("Orchestrator.get_ohlcv: %s", exc)
            return None

    def get_macro_features(self) -> pd.DataFrame | None:
        """
        Return the MacroStore as a DataFrame aligned to the current time.

        Used by the live inference loop to pass macro context to the predictor.
        Returns None when MacroStore is empty or unavailable.
        """
        try:
            from ml.macro_store import macro_store

            if len(macro_store) == 0:
                macro_store.load_defaults()
            if len(macro_store) == 0:
                return None
            # Return the raw macro DataFrame (predictor aligns it internally)
            return macro_store._data if hasattr(macro_store, "_data") else None
        except Exception as exc:
            logger.debug("Orchestrator.get_macro_features: %s", exc)
            return None

    def get_quality_report(self, symbol: str = "XAU_USD") -> QualityReport | None:
        """
        Return the latest data quality report.

        Also caches the report to Redis (TTL 30s) and writes it to the
        lineage store for audit purposes.
        """
        try:
            report = self._dqe.generate_report(symbol)
            if report is None:
                return None

            report_dict = {
                "timestamp": report.timestamp.isoformat(),
                "symbol": report.symbol,
                "ticks_received": report.ticks_received,
                "ticks_accepted": report.ticks_accepted,
                "ticks_rejected": report.ticks_rejected,
                "stale_count": report.stale_count,
                "jump_count": report.jump_count,
                "anomaly_count": report.anomaly_count,
                "active_sources": report.active_sources,
                "primary_source": report.primary_source,
                "consensus_price": report.consensus_price,
                "price_spread_across_sources": report.price_spread_across_sources,
            }

            # Cache to Redis
            if self._redis_store._r:
                try:
                    self._redis_store.set_quality_report(symbol, report_dict)
                except Exception as _exc:
                    logger.debug("Orchestrator: quality report Redis cache error: %s", _exc)

            # Write to lineage store
            try:
                self._lineage.record_quality(report_dict)
            except Exception as _exc:
                logger.debug("Orchestrator: quality report lineage error: %s", _exc)

            return report
        except Exception as exc:
            logger.debug("Orchestrator.get_quality_report error: %s", exc)
            return None

    def get_ohlcv_from_ticks(
        self,
        symbol: str = "XAU_USD",
        timeframe_minutes: int = 60,
        max_ticks: int = 5000,
    ) -> pd.DataFrame | None:
        """
        Build an OHLCV DataFrame from the tick history in Redis.

        Fetches up to max_ticks recent ticks from the Redis sorted set,
        converts them to GoldTick objects, and aggregates into OHLCV bars
        via NormalizationPipeline.tick_to_ohlcv().

        Returns None when fewer than 2 ticks are available.
        """
        try:
            raw_ticks = self._redis_store.get_tick_history(symbol, limit=max_ticks)
            if len(raw_ticks) < 2:
                return None

            ticks = []
            for r in raw_ticks:
                try:
                    raw_source = r.get("source")
                    if not raw_source:
                        continue
                    ticks.append(
                        GoldTick(
                            symbol=r["symbol"],
                            timestamp=datetime.fromisoformat(r["timestamp"]),
                            bid=float(r["bid"]),
                            ask=float(r["ask"]),
                            mid=float(r["mid"]),
                            source=FeedSource(raw_source),
                            quality=TickQuality(r.get("quality", "good")),
                            confidence=float(r.get("confidence", 1.0)),
                            spread=float(r.get("spread", 0.0)),
                            lineage_id=r.get("lineage_id", ""),
                        )
                    )
                except Exception:  # nosec B112 - skip malformed tick record during replay  # noqa: S112
                    continue

            if len(ticks) < 2:
                return None

            return self._norm.tick_to_ohlcv(ticks, timeframe_minutes=timeframe_minutes)
        except Exception as exc:
            logger.debug("Orchestrator.get_ohlcv_from_ticks error: %s", exc)
            return None

    # ── Tick subscription ─────────────────────────────────────────────────────

    def subscribe_ticks(self, name: str, callback: Any) -> None:
        """
        Register a callback to be called on every accepted tick.

        Parameters
        ----------
        name     : Unique subscriber name (used for deregistration).
        callback : Callable[[GoldTick], None].  Must not block — use
                   asyncio.create_task() inside the callback for async work.

        Example
        -------
        def on_tick(tick: GoldTick) -> None:
            logger.info(tick.mid)

        orchestrator.subscribe_ticks("my_handler", on_tick)
        """
        if not callable(callback):
            raise TypeError(f"subscribe_ticks: callback must be callable, got {type(callback)}")
        self._tick_callbacks[name] = callback
        logger.debug("Orchestrator: tick subscriber registered: %s", name)

    def unsubscribe_ticks(self, name: str) -> None:
        """Remove a previously registered tick callback."""
        removed = self._tick_callbacks.pop(name, None)
        if removed is None:
            logger.debug("Orchestrator: unsubscribe_ticks: unknown subscriber %s", name)
        else:
            logger.debug("Orchestrator: tick subscriber removed: %s", name)

    def subscribe_ticks_async(self, name: str, coro_fn: Any) -> None:
        """
        Register an async coroutine function for tick fanout.

        coro_fn must be an async callable: async def handler(tick: GoldTick) -> None

        Called via asyncio.create_task() on every accepted tick — non-blocking.
        """
        if not callable(coro_fn):
            raise TypeError(f"subscribe_ticks_async: coro_fn must be callable, got {type(coro_fn)}")
        self._async_tick_callbacks[name] = coro_fn
        logger.debug("Orchestrator: async tick subscriber registered: %s", name)

    def unsubscribe_ticks_async(self, name: str) -> None:
        """Remove a previously registered async tick callback."""
        self._async_tick_callbacks.pop(name, None)

    # ── WebSocket integration ─────────────────────────────────────────────────

    def add_websocket_connection(self, ws: Any) -> None:
        """Register a WebSocket connection for tick broadcast."""
        self._ws_broadcaster.add_connection(ws)

    def remove_websocket_connection(self, ws: Any) -> None:
        """Remove a WebSocket connection from the broadcast set."""
        self._ws_broadcaster.remove_connection(ws)

    # ── Circuit breaker management ────────────────────────────────────────────

    def get_circuit_breaker(self, component: str) -> CircuitBreaker | None:
        """Return the circuit breaker for a named component."""
        return self._cb.get(component)

    def reset_circuit_breaker(self, component: str) -> bool:
        """Manually reset a circuit breaker to CLOSED. Returns True if found."""
        cb = self._cb.get(component)
        if cb:
            cb.reset()
            return True
        return False

    def get_circuit_breaker_status(self) -> dict[str, dict]:
        """Return status dict for all circuit breakers."""
        return {name: cb.to_dict() for name, cb in self._cb.items()}

    # ── OHLCV window helper ───────────────────────────────────────────────────

    def get_ohlcv_window(
        self,
        symbol: str = "XAU_USD",
        bars: int = 200,
        timeframe: str = "H1",
    ) -> pd.DataFrame | None:
        """
        Return up to ``bars`` OHLCV bars, trying OHLCVStore first then
        falling back to tick-based reconstruction from Redis.

        This is the preferred method for the live inference loop — it
        abstracts the two OHLCV sources behind a single call.

        Returns None when insufficient data is available.
        """
        # Try OHLCVStore (broker feed) first
        df = self.get_ohlcv(symbol=symbol, bars=bars, timeframe=timeframe)
        if df is not None and len(df) >= 10:
            return df

        # Fall back to tick-based reconstruction
        tf_map = {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
        }
        tf_minutes = tf_map.get(timeframe.upper(), 60)
        return self.get_ohlcv_from_ticks(
            symbol=symbol,
            timeframe_minutes=tf_minutes,
            max_ticks=bars * 60,
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        h: dict[str, Any] = {
            "started": self._started,
            "uptime_s": round(time.time() - self._start_ts, 1) if self._started else 0,
            "tick_count": self._tick_count,
            # Redis health is surfaced explicitly so monitoring dashboards can
            # page on degraded mode — Redis failure is NOT a silent event.
            "redis_healthy": self._redis_healthy,
            "redis_url": _REDIS_URL,
            "redis": self._redis_store.stats(),
            "lineage": self._lineage.stats(),
        }
        if self._gold_feed:
            h["gold_feed"] = self._gold_feed.health()
        h["dqe"] = self._dqe.get_source_health()
        h["dqe_latency"] = self._dqe.latency_report()
        snap = self._micro.get_snapshot()
        h["micro"] = snap.__dict__ if snap else {}
        h["micro_health"] = self._micro.health()
        h["sentiment"] = self._sentiment.health()
        h["calendar"] = self._calendar.health()
        h["macro"] = self._macro_bridge.health()
        h["replay"] = self._replay.health()
        h["circuit_breakers"] = self.get_circuit_breaker_status()
        h["websocket"] = self._ws_broadcaster.stats()
        h["async_subscribers"] = list(self._async_tick_callbacks.keys())
        h["sync_subscribers"] = list(self._tick_callbacks.keys())

        # NOTE: Redis caching of this snapshot is handled by _uptime_loop
        # (every 10s via run_in_executor). Do NOT write to Redis here —
        # health() is called from both sync API endpoints and the async
        # _uptime_loop; a direct Redis write here would either block the
        # event loop (async context) or duplicate the write (sync context).

        # Aggregate health score [0.0, 1.0] — weighted combination of
        # sub-component health indicators for the OrchestratorHealthGrid.
        h["aggregate_health"] = self._compute_aggregate_health(h)
        h["status"] = (
            "healthy" if h["aggregate_health"] >= 0.7 else "degraded" if h["aggregate_health"] >= 0.3 else "unhealthy"
        )

        return h

    def _compute_aggregate_health(self, h: dict) -> float:
        """
        Compute a weighted aggregate health score [0.0, 1.0].

        Weights:
          - Gold feed active sources (0.30): most critical — no feed = no prices
          - Redis healthy (0.20): pub/sub and cache depend on Redis
          - DQE source confidence (0.20): data quality
          - Microstructure has data (0.15): tick processing working
          - Sentiment engine alive (0.10): news pipeline
          - Calendar engine alive (0.05): macro events
        """
        score = 0.0

        # Gold feed: score proportional to active source count (max 5 sources)
        import contextlib

        with contextlib.suppress(Exception):  # nosec B110
            gold = h.get("gold_feed", {})
            active = len(gold.get("active_sources", []))
            score += 0.30 * min(active / 3.0, 1.0)  # 3+ sources = full score

        # Redis
        with contextlib.suppress(Exception):  # nosec B110
            score += 0.20 if h.get("redis_healthy", False) else 0.0

        # DQE source confidence — average across all sources
        try:
            dqe = h.get("dqe", {})
            if dqe:
                confs = [v.get("confidence", 0.0) for v in dqe.values() if isinstance(v, dict)]
                if confs:
                    score += 0.20 * (sum(confs) / len(confs))
        except Exception:  # nosec B110  # noqa: S110
            pass

        # Microstructure has data
        try:
            micro_h = h.get("micro_health", {})
            score += 0.15 if micro_h.get("has_data", False) else 0.0
        except Exception:  # nosec B110  # noqa: S110
            pass

        # Sentiment engine alive
        try:
            sent = h.get("sentiment", {})
            score += 0.10 if sent.get("running", False) or sent.get("article_count_1h", 0) > 0 else 0.05
        except Exception:  # nosec B110  # noqa: S110
            pass

        # Calendar engine alive
        try:
            cal = h.get("calendar", {})
            score += 0.05 if cal.get("event_count", 0) >= 0 else 0.0
        except Exception:
            score += 0.05  # calendar is non-critical; give benefit of doubt

        return round(min(score, 1.0), 4)


# ── Module-level singleton ────────────────────────────────────────────────────
orchestrator = MarketDataOrchestrator()
