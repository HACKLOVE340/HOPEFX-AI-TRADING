# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/manager.py
=================================
GoldFeedManager — coordinates all five gold price adapters.

Responsibilities
----------------
- Polls all configured adapters concurrently on a configurable interval
- Passes every raw tick through DataQualityEngine
- Computes cross-source consensus mid price
- Implements priority-ordered failover:
    1. GoldAPI.io      (highest frequency, bid/ask available)
    2. Metals.dev      (WebSocket capable)
    3. Metals-API
    4. MetalpriceAPI
    5. CommodityPriceAPI
- Publishes validated ticks to Redis pub/sub channel hopefx:tick:XAU_USD
- Exposes get_latest_tick() for synchronous consumers
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.feeds.gold.goldapi import GoldAPIFeed
from data_layer.feeds.gold.metalpriceapi import MetalpriceAPIFeed
from data_layer.feeds.gold.metals_api import MetalsAPIFeed
from data_layer.feeds.gold.metals_dev import MetalsDevFeed
from data_layer.feeds.gold.commodity_api import CommodityAPIFeed
from data_layer.quality.engine import dqe
from data_layer.types import FeedSource, GoldTick, TickQuality

logger = logging.getLogger(__name__)

# Poll interval in seconds — GoldAPI is polled most frequently
_POLL_INTERVALS: Dict[FeedSource, float] = {
    FeedSource.GOLDAPI:       5.0,
    FeedSource.METALS_DEV:    10.0,
    FeedSource.METALS_API:    60.0,
    FeedSource.METALPRICEAPI: 60.0,
    FeedSource.COMMODITY_API: 60.0,
}

# Priority order for primary source selection
_PRIORITY: List[FeedSource] = [
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
        self._feeds: Dict[FeedSource, GoldFeedBase] = {
            FeedSource.GOLDAPI:       GoldAPIFeed(),
            FeedSource.METALPRICEAPI: MetalpriceAPIFeed(),
            FeedSource.METALS_API:    MetalsAPIFeed(),
            FeedSource.METALS_DEV:    MetalsDevFeed(),
            FeedSource.COMMODITY_API: CommodityAPIFeed(),
        }
        self._latest: Dict[FeedSource, GoldTick] = {}
        self._consensus_tick: Optional[GoldTick] = None
        self._redis = redis_client
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all configured feed polling loops."""
        self._running = True
        configured = [
            (src, feed) for src, feed in self._feeds.items()
            if feed.is_configured
        ]
        if not configured:
            logger.error(
                "GoldFeedManager: NO gold feed API keys configured. "
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

    # ── Polling loop ──────────────────────────────────────────────────────────

    async def _poll_loop(self, src: FeedSource, feed: GoldFeedBase) -> None:
        interval = _POLL_INTERVALS.get(src, 60.0)
        while self._running:
            t0 = time.monotonic()
            try:
                raw_tick = await feed.fetch_tick()
                received_at = time.time()
                validated   = dqe.validate_tick(raw_tick, received_at=received_at)

                async with self._lock:
                    self._latest[src] = validated
                    await self._update_consensus()

                if validated.quality != TickQuality.REJECTED:
                    await self._publish_tick(validated)

            except Exception as exc:
                logger.warning(
                    "GoldFeedManager poll error source=%s: %s", src.value, exc
                )

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_s)

    # ── Consensus ─────────────────────────────────────────────────────────────

    async def _update_consensus(self) -> None:
        """Recompute weighted consensus tick from all live feeds."""
        live = {
            src: tick for src, tick in self._latest.items()
            if tick.quality != TickQuality.REJECTED
        }
        if not live:
            return

        consensus_mid, confidence, weights = dqe.cross_source_consensus(live)
        if consensus_mid <= 0:
            return

        # Use the best source's bid/ask, adjusted to consensus mid
        best_src = dqe.best_source()
        if best_src and best_src in live:
            ref = live[best_src]
            half_spread = ref.spread / 2
        else:
            half_spread = consensus_mid * 0.0001

        import uuid
        from datetime import datetime, timezone
        self._consensus_tick = GoldTick(
            symbol     = "XAU_USD",
            timestamp  = datetime.now(timezone.utc),
            bid        = round(consensus_mid - half_spread, 4),
            ask        = round(consensus_mid + half_spread, 4),
            mid        = round(consensus_mid, 4),
            source     = FeedSource.SYNTHETIC,
            confidence = round(confidence, 4),
            spread     = round(half_spread * 2, 4),
            lineage_id = str(uuid.uuid4()),
        )

    # ── Redis pub/sub ─────────────────────────────────────────────────────────

    async def _publish_tick(self, tick: GoldTick) -> None:
        if not self._redis:
            return
        try:
            import json
            payload = {
                "symbol":     tick.symbol,
                "timestamp":  tick.timestamp.isoformat(),
                "bid":        tick.bid,
                "ask":        tick.ask,
                "mid":        tick.mid,
                "source":     tick.source.value,
                "quality":    tick.quality.value,
                "confidence": tick.confidence,
                "spread":     tick.spread,
                "lineage_id": tick.lineage_id,
            }
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._redis.publish("hopefx:tick:XAU_USD", json.dumps(payload)),
            )
        except Exception as exc:
            logger.debug("GoldFeedManager Redis publish error: %s", exc)

    # ── Public accessors ──────────────────────────────────────────────────────

    def get_latest_tick(self, prefer_consensus: bool = True) -> Optional[GoldTick]:
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
            if tick and tick.quality != TickQuality.REJECTED:
                return tick
        return None

    def get_source_tick(self, source: FeedSource) -> Optional[GoldTick]:
        return self._latest.get(source)

    def active_sources(self) -> List[FeedSource]:
        return [
            src for src, tick in self._latest.items()
            if tick.quality != TickQuality.REJECTED
        ]

    def health(self) -> dict:
        return {
            "active_sources": [s.value for s in self.active_sources()],
            "consensus_mid":  self._consensus_tick.mid if self._consensus_tick else None,
            "source_health":  dqe.get_source_health(),
            "feed_health":    {
                src.value: feed.health_summary()
                for src, feed in self._feeds.items()
            },
        }
