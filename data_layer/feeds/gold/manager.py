# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/manager.py
=================================
GoldFeedManager — coordinates all five gold price adapters.

Responsibilities
----------------
- Polls all configured adapters concurrently on configurable intervals
- Passes every raw tick through DataQualityEngine
- Computes cross-source consensus mid price (confidence-weighted)
- Priority-ordered failover:
    1. GoldAPI.io      (highest frequency, bid/ask available)
    2. Metals.dev      (WebSocket capable)
    3. Metals-API
    4. MetalpriceAPI
    5. CommodityPriceAPI
- Publishes validated ticks to Redis pub/sub channel hopefx:tick:XAU_USD
- Exposes get_latest_tick() for synchronous consumers
- Prometheus metrics: tick rate, consensus price, active source count
- Circuit breaker per feed — dead feeds don't block consensus
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

UTC = timezone.utc

from data_layer.feeds.gold.base import CircuitState, GoldFeedBase
from data_layer.feeds.gold.commodity_api import CommodityAPIFeed
from data_layer.feeds.gold.goldapi import GoldAPIFeed
from data_layer.feeds.gold.metalpriceapi import MetalpriceAPIFeed
from data_layer.feeds.gold.metals_api import MetalsAPIFeed
from data_layer.feeds.gold.metals_dev import MetalsDevFeed
from data_layer.quality.engine import dqe
from data_layer.types import FeedSource, GoldTick, TickQuality

logger = logging.getLogger(__name__)

# Poll interval per source (seconds)
_POLL_INTERVALS: dict[FeedSource, float] = {
    FeedSource.GOLDAPI: 5.0,
    FeedSource.METALS_DEV: 10.0,
    FeedSource.METALS_API: 60.0,
    FeedSource.METALPRICEAPI: 60.0,
    FeedSource.COMMODITY_API: 60.0,
}

# Priority order for primary source selection (index 0 = highest priority)
_PRIORITY: list[FeedSource] = [
    FeedSource.GOLDAPI,
    FeedSource.METALS_DEV,
    FeedSource.METALS_API,
    FeedSource.METALPRICEAPI,
    FeedSource.COMMODITY_API,
]


class GoldFeedManager:
    """
    Manages all gold price feed adapters.

    Usage:
        manager = GoldFeedManager()
        await manager.start()
        tick = manager.get_latest_tick()
        await manager.stop()
    """

    def __init__(self, redis_client=None) -> None:
        self._feeds: dict[FeedSource, GoldFeedBase] = {
            FeedSource.GOLDAPI: GoldAPIFeed(),
            FeedSource.METALPRICEAPI: MetalpriceAPIFeed(),
            FeedSource.METALS_API: MetalsAPIFeed(),
            FeedSource.METALS_DEV: MetalsDevFeed(),
            FeedSource.COMMODITY_API: CommodityAPIFeed(),
        }
        self._latest: dict[FeedSource, GoldTick] = {}
        self._consensus_tick: GoldTick | None = None
        self._redis = redis_client
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()
        self._tick_count: int = 0
        self._last_consensus_at: float = 0.0
        # Suppress repeated poll-error warnings per source — log once, then DEBUG.
        self._poll_error_warned: set = set()

        # Prometheus
        self._prom_consensus_price = None
        self._prom_active_sources = None
        self._prom_tick_rate = None
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

            self._prom_consensus_price = _gauge(
                "hopefx_gold_consensus_price_usd",
                "Current consensus gold price in USD/oz",
            )
            self._prom_active_sources = _gauge(
                "hopefx_gold_active_sources",
                "Number of active gold price sources",
            )
            self._prom_tick_rate = _counter(
                "hopefx_gold_ticks_total",
                "Total validated gold ticks processed",
            )
        except Exception as _exc:
            logger.debug("GoldFeedManager: Prometheus init skipped: %s", _exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all configured feed polling loops."""
        self._running = True
        configured = [(src, feed) for src, feed in self._feeds.items() if feed.is_configured]
        if not configured:
            logger.info(
                "GoldFeedManager: no gold feed API keys configured — live gold prices unavailable. "
                "Set at least one of: GOLDAPI_IO_KEY, METALS_DEV_KEY, "
                "METALS_API_KEY, METALPRICEAPI_KEY, COMMODITY_PRICE_API_KEY"
            )
            return

        for src, feed in configured:
            task = asyncio.create_task(
                self._poll_loop(src, feed),
                name=f"gold_feed_{src.value}",
            )
            self._tasks.append(task)
            logger.info("GoldFeedManager: started feed %s", src.value)

        # Start Metals.dev WebSocket if configured
        metals_dev: MetalsDevFeed = self._feeds[FeedSource.METALS_DEV]  # type: ignore
        if metals_dev.is_configured:
            await metals_dev.start_websocket()

        logger.info(
            "GoldFeedManager: %d feeds active: %s",
            len(configured),
            [s.value for s, _ in configured],
        )

    async def stop(self) -> None:
        """Gracefully stop all feed loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        metals_dev: MetalsDevFeed = self._feeds[FeedSource.METALS_DEV]  # type: ignore
        await metals_dev.stop_websocket()

        for feed in self._feeds.values():
            await feed.close()

        logger.info("GoldFeedManager: stopped")

    # ── Polling loop ──────────────────────────────────────────────────────────

    async def _poll_loop(self, src: FeedSource, feed: GoldFeedBase) -> None:
        interval = _POLL_INTERVALS.get(src, 60.0)
        # Stagger startup to avoid thundering herd
        await asyncio.sleep(_PRIORITY.index(src) * 0.5)

        while self._running:
            t0 = time.monotonic()
            try:
                # Skip if circuit is open
                if feed.circuit_state == CircuitState.OPEN:
                    logger.debug("GoldFeedManager: %s circuit OPEN — skipping poll", src.value)
                else:
                    raw_tick = await feed.fetch_tick()
                    received_at = time.time()

                    # Pre-DQE age gate: reject ticks with timestamps more than
                    # 5 minutes in the past or any time in the future.
                    # REST APIs occasionally return cached/stale prices; this
                    # catches them before they corrupt the consensus.
                    tick_age_s = received_at - raw_tick.timestamp.timestamp()
                    if tick_age_s > 300.0:
                        logger.warning(
                            "GoldFeedManager: %s tick too old (age=%.1fs) — discarded",
                            src.value,
                            tick_age_s,
                        )
                    elif tick_age_s < -10.0:
                        logger.warning(
                            "GoldFeedManager: %s tick from future (age=%.1fs) — discarded",
                            src.value,
                            tick_age_s,
                        )
                    else:
                        validated = dqe.validate_tick(raw_tick, received_at=received_at)

                        async with self._lock:
                            self._latest[src] = validated
                            await self._update_consensus()

                        if validated.quality != TickQuality.REJECTED:
                            self._tick_count += 1
                            if self._prom_tick_rate:
                                self._prom_tick_rate.inc()
                            await self._publish_tick(validated)

                        # Reset DQE source confidence when circuit recovers
                        # from OPEN → CLOSED so a recovered feed isn't
                        # permanently penalised by its pre-outage error history.
                        if feed.circuit_state == CircuitState.CLOSED:
                            prev_state = getattr(feed, "_prev_circuit_state", None)
                            if prev_state == CircuitState.HALF_OPEN:
                                dqe.reset_source(src)
                                logger.info(
                                    "GoldFeedManager: %s circuit recovered — DQE source state reset",
                                    src.value,
                                )
                        feed._prev_circuit_state = feed.circuit_state

            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Log first poll error per source as WARNING; suppress repeats
                # to DEBUG so the log is not flooded when an API is offline.
                if src not in self._poll_error_warned:
                    logger.warning("GoldFeedManager poll error source=%s: %s", src.value, exc)
                    self._poll_error_warned.add(src)
                else:
                    logger.debug(
                        "GoldFeedManager poll error source=%s (suppressed): %s",
                        src.value,
                        exc,
                    )

            elapsed = time.monotonic() - t0
            sleep_s = max(0.1, interval - elapsed)
            await asyncio.sleep(sleep_s)

    # ── Consensus ─────────────────────────────────────────────────────────────

    async def _update_consensus(self) -> None:
        """
        Recompute weighted consensus tick from all live feeds.

        Consensus algorithm:
          1. Collect all non-rejected, valid ticks
          2. Compute confidence-weighted mean mid price
          3. Reject outliers > DQE_CROSS_SOURCE_MAX_DIFF from weighted mean
          4. Recompute with outliers removed
          5. Use best-source bid/ask spread centred on consensus mid
        """
        now_epoch = time.time()
        # Exclude ticks that are REJECTED, STALE, or older than 2× the stale
        # threshold — a source that stopped sending keeps its last GOOD tick in
        # _latest indefinitely; the age gate prevents stale prices from
        # contaminating the consensus even before DQE marks the source STALE.
        _max_age_s = float(os.getenv("DQE_STALE_THRESHOLD_S", "30.0")) * 2.0
        live = {
            src: tick
            for src, tick in self._latest.items()
            if tick.is_valid() and (now_epoch - tick.timestamp.timestamp()) <= _max_age_s
        }
        if not live:
            return

        consensus_mid, confidence, _ = dqe.cross_source_consensus(live)
        if consensus_mid <= 0:
            return

        # Use the best source's bid/ask spread, centred on consensus mid.
        # Priority: GoldAPI (has real bid/ask) > others (synthesised spread).
        best_src = dqe.best_source()
        if best_src and best_src in live:
            ref = live[best_src]
            half_spread = ref.spread / 2.0
        else:
            # Fallback: typical gold spread ~$0.30 (0.015% of $2000)
            half_spread = max(consensus_mid * 0.00015, 0.10)

        self._consensus_tick = GoldTick(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            bid=round(consensus_mid - half_spread, 4),
            ask=round(consensus_mid + half_spread, 4),
            mid=round(consensus_mid, 4),
            source=FeedSource.AGGREGATED,
            confidence=round(confidence, 4),
            spread=round(half_spread * 2, 4),
            lineage_id=str(uuid.uuid4()),
        )
        self._last_consensus_at = time.time()

        if self._prom_consensus_price:
            with contextlib.suppress(Exception):
                self._prom_consensus_price.set(consensus_mid)
        if self._prom_active_sources:
            with contextlib.suppress(Exception):
                self._prom_active_sources.set(len(live))

        # Cache consensus tick to Redis for synchronous consumers.
        # Use run_in_executor — self._redis is a sync client; calling it
        # directly inside an async method blocks the event loop.
        if self._redis and self._consensus_tick:
            try:
                payload = json.dumps(
                    {
                        "symbol": self._consensus_tick.symbol,
                        "timestamp": self._consensus_tick.timestamp.isoformat(),
                        "bid": self._consensus_tick.bid,
                        "ask": self._consensus_tick.ask,
                        "mid": self._consensus_tick.mid,
                        "source": self._consensus_tick.source.value,
                        "quality": self._consensus_tick.quality.value,
                        "confidence": self._consensus_tick.confidence,
                        "spread": self._consensus_tick.spread,
                        "lineage_id": self._consensus_tick.lineage_id,
                        "epoch": self._consensus_tick.timestamp.timestamp(),
                    }
                )
                _r, _p = self._redis, payload
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: _r.setex("hopefx:dl:tick:XAU_USD", 30, _p),
                )
            except Exception as exc:
                logger.debug("GoldFeedManager consensus Redis cache error: %s", exc)

    # ── Redis pub/sub ─────────────────────────────────────────────────────────

    async def _publish_tick(self, tick: GoldTick) -> None:
        if not self._redis:
            return
        try:
            payload = {
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
            serialised = json.dumps(payload)
            loop = asyncio.get_running_loop()
            # Publish to symbol-specific channel (hopefx:tick:XAU_USD)
            await loop.run_in_executor(
                None,
                lambda: self._redis.publish("hopefx:tick:XAU_USD", serialised),
            )
            # Also publish to the main CH_TICK channel (hopefx:tick) so that
            # ws_live.py broadcasters and strategy/engine.py receive gold ticks.
            await loop.run_in_executor(
                None,
                lambda: self._redis.publish("hopefx:tick", serialised),
            )
            # Cache as latest tick (TTL 30s) for synchronous consumers
            await loop.run_in_executor(
                None,
                lambda: self._redis.setex("hopefx:dl:tick:XAU_USD", 30, serialised),
            )
        except Exception as exc:
            logger.debug("GoldFeedManager Redis publish error: %s", exc)

    # ── Public accessors ──────────────────────────────────────────────────────

    def get_latest_tick(self, prefer_consensus: bool = True) -> GoldTick | None:
        """
        Return the best available tick.

        prefer_consensus=True  → returns weighted consensus across all live feeds
        prefer_consensus=False → returns tick from highest-confidence single source
        """
        if prefer_consensus and self._consensus_tick:
            return self._consensus_tick

        # Fallback: priority-ordered single source
        for src in _PRIORITY:
            tick = self._latest.get(src)
            if tick and tick.quality != TickQuality.REJECTED and tick.is_valid():
                return tick
        return None

    def get_source_tick(self, source: FeedSource) -> GoldTick | None:
        return self._latest.get(source)

    def active_sources(self) -> list[FeedSource]:
        return [src for src, tick in self._latest.items() if tick.quality != TickQuality.REJECTED and tick.is_valid()]

    def health(self) -> dict:
        h = {
            "running": self._running,
            "tick_count": self._tick_count,
            "active_sources": [s.value for s in self.active_sources()],
            "consensus_mid": self._consensus_tick.mid if self._consensus_tick else None,
            "consensus_conf": self._consensus_tick.confidence if self._consensus_tick else None,
            "last_consensus_age_s": round(time.time() - self._last_consensus_at, 1)
            if self._last_consensus_at
            else None,
            "source_health": dqe.get_source_health(),
            "feed_health": {src.value: feed.health_summary() for src, feed in self._feeds.items()},
        }
        # Cache feed health to Redis (TTL 10s) for monitoring dashboards
        if self._redis:
            try:
                self._redis.setex(
                    "hopefx:dl:feed_health",
                    10,
                    json.dumps(h, default=str),
                )
            except Exception as exc:
                logger.debug("GoldFeedManager health Redis cache error: %s", exc)
        return h
