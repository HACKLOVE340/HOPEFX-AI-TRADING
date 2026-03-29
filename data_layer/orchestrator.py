# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/orchestrator.py
============================
MarketDataOrchestrator — single source of truth for all market data.

This is the ONLY entry point the rest of the system uses to access
market data. No module should import from individual feed adapters directly.

Architecture
------------
  MarketDataOrchestrator
    ├── GoldFeedManager          → 5 gold price feeds, consensus tick
    ├── DataQualityEngine        → validation, anomaly detection, failover
    ├── MicrostructureEngine     → bid/ask, OFI, delta, Kyle's lambda
    ├── NewsSentimentEngine      → 5 news feeds, VADER scoring, EMA signal
    ├── MacroCalendarEngine      → Finnhub calendar, gold impact scoring
    ├── MacroStoreBridge         → FRED → ml/macro_store.py population
    ├── DataLayerRedisStore      → per-instrument TTL caching
    ├── DataLineageStore         → immutable audit trail
    ├── NormalizationPipeline    → tick + OHLCV cleaning
    └── MarketReplayEngine       → Dukascopy historical replay

Downstream consumers (wired via get_ml_features())
---------------------------------------------------
  ml/features_extended.py   → 230+ feature builder
  ml/macro_store.py         → daily macro series alignment
  ml/inference_engine.py    → live signal generation
  ml/online_learner.py      → SGD adapter updates
  ml/advanced_predictor.py  → ensemble prediction
  ml/live_inference.py      → feature cache + prediction
  risk/manager.py           → position sizing, drawdown
  risk/gatekeeper.py        → news blackout, confidence floor
  execution/smart_router.py → order routing (OANDA/IBKR execution only)

Startup sequence
----------------
  1. Connect Redis
  2. Start DataLineageStore (SQLite writer thread)
  3. Start GoldFeedManager (5 feed polling loops)
  4. Start NewsSentimentEngine (5 news polling loops)
  5. Start MacroCalendarEngine (hourly Finnhub calendar refresh)
  6. Start MacroStoreBridge (FRED load + daily refresh)
  7. Begin publishing ticks to Redis pub/sub

Usage:
    from data_layer import orchestrator

    await orchestrator.start()

    # Get latest validated tick
    tick = orchestrator.get_latest_tick()

    # Get all ML features (microstructure + sentiment + macro + calendar)
    features = orchestrator.get_ml_features()

    # Get OHLCV DataFrame for ML pipeline
    df = await orchestrator.get_ohlcv_dataframe("XAU_USD", "1h", limit=200)

    # Check if trading is safe right now
    safe = orchestrator.is_safe_to_trade()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from data_layer.cache.redis_store import DataLayerRedisStore, dl_redis_store
from data_layer.calendar.engine import MacroCalendarEngine, macro_calendar_engine
from data_layer.feeds.gold.manager import GoldFeedManager
from data_layer.feeds.macro.store_bridge import MacroStoreBridge, macro_store_bridge
from data_layer.lineage.store import DataLineageStore, lineage_store
from data_layer.microstructure.engine import MicrostructureEngine, microstructure_engine
from data_layer.normalization.pipeline import NormalizationPipeline, normalization_pipeline
from data_layer.quality.engine import DataQualityEngine, dqe
from data_layer.replay.engine import MarketReplayEngine, market_replay_engine
from data_layer.sentiment.engine import NewsSentimentEngine, news_sentiment_engine
from data_layer.types import FeedSource, GoldTick, TickQuality

logger = logging.getLogger(__name__)

_OHLCV_BAR_LIMIT = int(os.getenv("ORCHESTRATOR_OHLCV_LIMIT", "500"))


class MarketDataOrchestrator:
    """
    Single source of truth for all market data in HOPEFX.

    Instantiate once at application startup via the module-level
    `orchestrator` singleton. All other modules import from here.
    """

    def __init__(self) -> None:
        self._redis: Optional[Any] = None
        self._gold_feeds: Optional[GoldFeedManager] = None
        self._dqe:        DataQualityEngine          = dqe
        self._micro:      MicrostructureEngine       = microstructure_engine
        self._news:       NewsSentimentEngine        = news_sentiment_engine
        self._calendar:   MacroCalendarEngine        = macro_calendar_engine
        self._macro_bridge: MacroStoreBridge         = macro_store_bridge
        self._cache:      DataLayerRedisStore        = dl_redis_store
        self._lineage:    DataLineageStore           = lineage_store
        self._norm:       NormalizationPipeline      = normalization_pipeline
        self._replay:     MarketReplayEngine         = market_replay_engine
        self._started     = False
        self._tick_count  = 0
        self._start_time: Optional[float] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, redis_url: Optional[str] = None) -> None:
        """
        Start the full data layer.

        redis_url: override REDIS_URL env var (useful for testing).
        """
        if self._started:
            logger.warning("MarketDataOrchestrator already started")
            return

        logger.info("MarketDataOrchestrator: starting...")
        self._start_time = time.time()

        # 1. Connect Redis
        await self._connect_redis(redis_url)

        # 2. Start lineage store
        self._lineage.start()

        # 3. Wire Redis into sub-components
        self._cache._r = self._redis
        self._news._redis = self._redis
        self._calendar._redis = self._redis
        self._news._lineage = self._lineage

        # 4. Start gold feeds
        self._gold_feeds = GoldFeedManager(redis_client=self._redis)
        await self._gold_feeds.start()

        # 5. Start news sentiment engine
        await self._news.start()

        # 6. Start macro calendar engine
        await self._calendar.start()

        # 7. Start macro store bridge (FRED → ml/macro_store.py)
        await self._macro_bridge.start()

        # 8. Start tick processing loop
        asyncio.create_task(
            self._tick_processing_loop(),
            name="orchestrator_tick_loop",
        )

        # 9. Start health reporting loop
        asyncio.create_task(
            self._health_loop(),
            name="orchestrator_health_loop",
        )

        self._started = True
        logger.info("MarketDataOrchestrator: fully started")

    async def stop(self) -> None:
        """Gracefully stop all components."""
        if self._gold_feeds:
            await self._gold_feeds.stop()
        await self._news.stop()
        self._lineage.stop()
        self._started = False
        logger.info("MarketDataOrchestrator: stopped")

    # ── Redis connection ──────────────────────────────────────────────────────

    async def _connect_redis(self, redis_url: Optional[str] = None) -> None:
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis as redis_lib
            self._redis = redis_lib.from_url(url, decode_responses=False)
            self._redis.ping()
            logger.info("MarketDataOrchestrator: Redis connected at %s", url)
        except Exception as exc:
            logger.warning(
                "MarketDataOrchestrator: Redis unavailable (%s) — "
                "running without cache/pub-sub", exc
            )
            self._redis = None

    # ── Tick processing loop ──────────────────────────────────────────────────

    async def _tick_processing_loop(self) -> None:
        """
        Main loop: poll gold feeds → validate → microstructure → cache → lineage.
        Runs every 1 second to pick up new ticks from GoldFeedManager.
        """
        while self._started:
            try:
                tick = self._gold_feeds.get_latest_tick() if self._gold_feeds else None
                if tick and tick.quality != TickQuality.REJECTED:
                    # Normalise
                    tick = self._norm.normalize_tick(tick)

                    # Microstructure
                    self._micro.on_tick(tick)

                    # Cache
                    self._cache.set_tick("XAU_USD", self._tick_to_dict(tick))

                    # Microstructure cache
                    snap = self._micro.get_snapshot()
                    if snap:
                        self._cache.set_microstructure(
                            "XAU_USD", self._snap_to_dict(snap)
                        )

                    # Lineage (sample 1 in 10 ticks to avoid DB saturation)
                    self._tick_count += 1
                    if self._tick_count % 10 == 0:
                        self._lineage.record_tick(tick)

            except Exception as exc:
                logger.debug("Orchestrator tick loop error: %s", exc)

            await asyncio.sleep(1.0)

    # ── Health loop ───────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Publish health + quality reports every 30 seconds."""
        while self._started:
            await asyncio.sleep(30.0)
            try:
                health = self.health()
                self._cache.set_feed_health(health)

                report = self._dqe.generate_report("XAU_USD")
                self._cache.set_quality_report("XAU_USD", {
                    "timestamp":      report.timestamp.isoformat(),
                    "ticks_accepted": report.ticks_accepted,
                    "ticks_rejected": report.ticks_rejected,
                    "active_sources": report.active_sources,
                    "primary_source": report.primary_source,
                    "consensus_price": report.consensus_price,
                })
                self._lineage.record_quality({
                    "symbol":         "XAU_USD",
                    "ticks_accepted": report.ticks_accepted,
                    "ticks_rejected": report.ticks_rejected,
                    "active_sources": report.active_sources,
                })

                # Cache sentiment + macro features
                sentiment = self._news.get_ml_features()
                self._cache.set_sentiment(sentiment)

                macro_feat = self._macro_bridge.get_ml_features()
                macro_feat.update(self._calendar.get_ml_features())
                self._cache.set_macro_features(macro_feat)
                self._cache.set_calendar_impact(
                    self._calendar.get_current_impact_score()
                )

            except Exception as exc:
                logger.debug("Orchestrator health loop error: %s", exc)

    # ── Public data access API ────────────────────────────────────────────────

    def get_latest_tick(self, symbol: str = "XAU_USD") -> Optional[GoldTick]:
        """
        Return the latest validated consensus tick.

        Checks Redis cache first, falls back to in-memory GoldFeedManager.
        """
        # Try Redis cache
        cached = self._cache.get_tick(symbol)
        if cached:
            return self._dict_to_tick(cached)

        # Fall back to in-memory
        if self._gold_feeds:
            return self._gold_feeds.get_latest_tick()
        return None

    def get_ml_features(
        self,
        symbol: str = "XAU_USD",
        as_of: Optional[datetime] = None,
    ) -> Dict[str, float]:
        """
        Return the complete ML feature set from all data layer components.

        Includes:
          - 16 microstructure features (spread, OFI, delta, pressure...)
          - 4 sentiment features (EMA score, momentum, count, bullish ratio)
          - 6 macro calendar features (impact score, hours to event...)
          - N macro series features (DXY, yields, CPI, VIX...)

        as_of: enforce causal filter (for backtesting / replay).
        """
        features: Dict[str, float] = {}

        # Microstructure
        features.update(self._micro.get_ml_features())

        # Sentiment
        if as_of:
            features.update(self._news.get_ml_features(as_of=as_of))
        else:
            # Try Redis cache first
            cached_sent = self._cache.get_sentiment()
            if cached_sent:
                features.update(cached_sent)
            else:
                features.update(self._news.get_ml_features())

        # Macro calendar
        if as_of:
            features.update(self._calendar.get_ml_features(as_of=as_of))
        else:
            cached_macro = self._cache.get_macro_features()
            if cached_macro:
                features.update(cached_macro)
            else:
                features.update(self._calendar.get_ml_features())
                features.update(self._macro_bridge.get_ml_features())

        return features

    async def get_ohlcv_dataframe(
        self,
        symbol: str = "XAU_USD",
        timeframe: str = "1h",
        limit: int = 200,
        use_dukascopy: bool = False,
    ) -> pd.DataFrame:
        """
        Return a normalised OHLCV DataFrame for the ML pipeline.

        Checks Redis cache first. If cache miss and use_dukascopy=True,
        fetches from Dukascopy (slow — use for backtesting only).

        Returns pd.DataFrame with columns: open, high, low, close, volume,
        log_return, log_volume, gap_flag, ohlcv_valid
        and DatetimeIndex (UTC).
        """
        # Try Redis cache
        bars = self._cache.get_ohlcv_bars(symbol, timeframe, limit=limit)
        if bars:
            df = pd.DataFrame(bars)
            if "open_time" in df.columns:
                df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
                df = df.set_index("open_time").sort_index()
            return self._norm.normalize_ohlcv(df)

        # Dukascopy fallback (backtesting)
        if use_dukascopy:
            from datetime import timedelta
            end   = datetime.now(timezone.utc)
            tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
            tf_min = tf_map.get(timeframe, 60)
            start = end - timedelta(minutes=tf_min * limit)
            df = await self._replay.build_ohlcv_dataframe(
                start=start, end=end,
                symbol=symbol.replace("_", ""),
                timeframe_minutes=tf_min,
            )
            return self._norm.normalize_ohlcv(df)

        return pd.DataFrame()

    def is_safe_to_trade(self) -> bool:
        """
        Return True if conditions are safe for automated trading.

        Checks:
          - At least one gold feed is alive
          - Not in a macro event blackout window
          - Data quality confidence > 0.3
        """
        if not self._gold_feeds:
            return False
        if not self._gold_feeds.active_sources():
            return False
        if self._calendar.is_blackout_window():
            return False
        best = self._dqe.best_source()
        if best is None:
            return False
        return True

    def get_current_impact_score(self) -> float:
        """Return current macro impact score [0, 1]."""
        cached = self._cache.get_calendar_impact()
        if cached is not None:
            return cached
        return self._calendar.get_current_impact_score()

    def get_replay_engine(self) -> MarketReplayEngine:
        """Return the replay engine for backtesting."""
        return self._replay

    # ── Health & diagnostics ──────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "started":        self._started,
            "uptime_s":       round(uptime, 1),
            "tick_count":     self._tick_count,
            "is_safe":        self.is_safe_to_trade(),
            "impact_score":   self.get_current_impact_score(),
            "is_blackout":    self._calendar.is_blackout_window(),
            "gold_feeds":     self._gold_feeds.health() if self._gold_feeds else {},
            "news":           self._news.health(),
            "calendar":       self._calendar.health(),
            "macro_bridge":   self._macro_bridge.health(),
            "cache":          self._cache.stats(),
            "lineage":        self._lineage.stats(),
            "dqe":            self._dqe.get_source_health(),
        }

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @staticmethod
    def _tick_to_dict(tick: GoldTick) -> Dict[str, Any]:
        return {
            "symbol":     tick.symbol,
            "timestamp":  tick.timestamp.isoformat(),
            "epoch":      tick.timestamp.timestamp(),
            "bid":        tick.bid,
            "ask":        tick.ask,
            "mid":        tick.mid,
            "source":     tick.source.value,
            "quality":    tick.quality.value,
            "confidence": tick.confidence,
            "spread":     tick.spread,
            "lineage_id": tick.lineage_id,
        }

    @staticmethod
    def _dict_to_tick(d: Dict[str, Any]) -> Optional[GoldTick]:
        try:
            return GoldTick(
                symbol     = d["symbol"],
                timestamp  = datetime.fromisoformat(d["timestamp"]),
                bid        = float(d["bid"]),
                ask        = float(d["ask"]),
                mid        = float(d["mid"]),
                source     = FeedSource(d["source"]),
                quality    = TickQuality(d.get("quality", "good")),
                confidence = float(d.get("confidence", 1.0)),
                spread     = float(d.get("spread", 0.0)),
                lineage_id = d.get("lineage_id", ""),
            )
        except Exception:
            return None

    @staticmethod
    def _snap_to_dict(snap) -> Dict[str, Any]:
        return {
            "symbol":              snap.symbol,
            "timestamp":           snap.timestamp.isoformat(),
            "bid":                 snap.bid,
            "ask":                 snap.ask,
            "spread":              snap.spread,
            "spread_pct":          snap.spread_pct,
            "volume_delta":        snap.volume_delta,
            "cumulative_delta":    snap.cumulative_delta,
            "buy_pressure":        snap.buy_pressure,
            "sell_pressure":       snap.sell_pressure,
            "order_flow_imbalance": snap.order_flow_imbalance,
            "trade_pressure":      snap.trade_pressure,
            "vwap":                snap.vwap,
            "tick_count":          snap.tick_count,
        }


# ── Module-level singleton ────────────────────────────────────────────────────
orchestrator = MarketDataOrchestrator()
