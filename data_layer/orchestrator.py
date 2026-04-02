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
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# ── Component imports ─────────────────────────────────────────────────────────
from data_layer.cache.redis_store import DataLayerRedisStore, dl_redis_store
from data_layer.calendar.engine import MacroCalendarEngine, macro_calendar_engine
from data_layer.feeds.gold.manager import GoldFeedManager
from data_layer.feeds.macro.store_bridge import MacroStoreBridge, macro_store_bridge
from data_layer.lineage.store import DataLineageStore, lineage_store
from data_layer.microstructure.engine import MicrostructureEngine, microstructure_engine
from data_layer.normalization.pipeline import (
    NormalizationPipeline,
    normalization_pipeline,
)
from data_layer.quality.engine import DataQualityEngine, dqe
from data_layer.replay.engine import MarketReplayEngine, market_replay_engine
from data_layer.sentiment.engine import NewsSentimentEngine, news_sentiment_engine
from data_layer.types import GoldTick, QualityReport, TickQuality
import contextlib

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


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

        # Core components
        self._gold_feed: GoldFeedManager | None = None
        self._dqe: DataQualityEngine = dqe
        self._micro: MicrostructureEngine = microstructure_engine
        self._sentiment: NewsSentimentEngine = news_sentiment_engine
        self._calendar: MacroCalendarEngine = macro_calendar_engine
        self._macro_bridge: MacroStoreBridge = macro_store_bridge
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

        # Prometheus
        self._prom_uptime = None
        self._prom_tick_rate = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, REGISTRY

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
            logger.info("MarketDataOrchestrator: Redis connected (%s)", _REDIS_URL)
        except Exception as exc:
            logger.warning(
                "MarketDataOrchestrator: Redis unavailable (%s) — caching disabled, continuing without Redis",
                exc,
            )

        # 2. Lineage store
        try:
            self._lineage.start()
            self._sentiment._lineage = self._lineage
            logger.info("MarketDataOrchestrator: DataLineageStore started")
        except Exception as exc:
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

        # 6. FRED → MacroStore bridge
        try:
            await self._macro_bridge.start()
            logger.info("MarketDataOrchestrator: MacroStoreBridge started")
        except Exception as exc:
            logger.warning("MarketDataOrchestrator: macro bridge error: %s", exc)

        # 7. Ensure macro CSV fallback is loaded so features are never zero
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
        # 1. Macro bridge (FRED sessions)
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
                    from data_layer.types import FeedSource

                    # Require source to be present and a known FeedSource value.
                    # Missing or unrecognised source → fall through to live feed
                    # rather than labelling the tick with a fabricated origin.
                    raw_source = cached.get("source")
                    if not raw_source:
                        raise ValueError(f"Cached tick for {symbol} has no 'source' field")
                    return GoldTick(
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
        """Side-effects on every tick: microstructure, cache, lineage."""
        # Microstructure
        snap = self._micro.on_tick(tick)

        # Redis cache — tick
        if self._redis_store._r:
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
            self._redis_store.set_tick(tick.symbol, tick_dict)

            # Cache microstructure snapshot
            if snap:
                try:
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
                    )
                except Exception as _exc:
                    logger.debug("Orchestrator: micro cache error: %s", _exc)

        # Lineage — only accepted ticks
        if tick.quality != TickQuality.REJECTED:
            try:
                self._lineage.record_tick(tick)
            except Exception as _exc:
                logger.debug("Orchestrator: lineage record_tick error: %s", _exc)

        self._tick_count += 1
        if self._prom_tick_rate:
            try:
                self._prom_tick_rate.inc()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # Fire registered tick callbacks (non-blocking)
        for _name, _cb in list(self._tick_callbacks.items()):
            try:
                _cb(tick)
            except Exception as _exc:
                logger.debug("Orchestrator: tick callback %s error: %s", _name, _exc)

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

        Causal guarantee: as_of parameter is passed to every sub-component
        that supports it (sentiment, calendar). Microstructure features are
        always computed from past ticks only.

        Returns empty dict on error — never raises.
        """
        features: dict[str, float] = {}

        # 1. Microstructure (16 features)
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
            else:
                features["tick_confidence"] = 0.0
                features["tick_spread_pct"] = 0.0

            if self._gold_feed:
                features["tick_source_count"] = float(len(self._gold_feed.active_sources()))
            else:
                features["tick_source_count"] = 0.0
        except Exception as exc:
            logger.debug("Orchestrator: tick quality features error: %s", exc)

        return features

    # ── Convenience accessors ─────────────────────────────────────────────────

    def get_current_gold_price(self) -> float | None:
        """Return current consensus gold mid price, or None if unavailable."""
        tick = self.get_latest_tick()
        return tick.mid if tick else None

    def get_macro_impact_score(self) -> float:
        """Return current macro calendar impact score [0, 1]."""
        try:
            return self._calendar.get_current_impact_score()
        except Exception:  # nosec B110
            return 0.0

    def is_blackout_window(self) -> bool:
        """True if within a HIGH-impact event blackout window."""
        try:
            return self._calendar.is_blackout_window()
        except Exception:  # nosec B110
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

        # Check tick quality
        tick = self.get_latest_tick()
        if tick is not None and tick.confidence < 0.30:  # noqa: PLR2004
            return False

        # Check at least one feed alive
        if self._gold_feed and not self._gold_feed.active_sources():
            # No active sources — but only block if we've been running > 30s
            import time

            if self._started and (time.time() - self._start_ts) > 30.0:  # noqa: PLR2004
                return False

        return True

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
            if len(raw_ticks) < 2:  # noqa: PLR2004
                return None

            from datetime import datetime
            from data_layer.types import FeedSource, TickQuality

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
                except Exception:  # nosec B112 - skip malformed tick record during replay
                    continue

            if len(ticks) < 2:  # noqa: PLR2004
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
            print(tick.mid)

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
        if df is not None and len(df) >= 10:  # noqa: PLR2004
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

        # NOTE: Redis caching of this snapshot is handled by _uptime_loop
        # (every 10s via run_in_executor). Do NOT write to Redis here —
        # health() is called from both sync API endpoints and the async
        # _uptime_loop; a direct Redis write here would either block the
        # event loop (async context) or duplicate the write (sync context).

        return h


# ── Module-level singleton ────────────────────────────────────────────────────
orchestrator = MarketDataOrchestrator()
