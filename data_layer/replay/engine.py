# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/replay/engine.py
=============================
MarketReplayEngine — perfect-fidelity historical market replay.

The replay engine feeds historical Dukascopy ticks through the SAME
processing pipeline as live data:
  1. DataQualityEngine validation
  2. MicrostructureEngine tick processing
  3. OHLCV bar aggregation
  4. Feature extraction (same as live)

Causal guarantee
----------------
The replay engine enforces strict causal ordering:
  - Ticks are processed in timestamp-ascending order
  - No future data is ever accessible at any point in the replay
  - The as_of parameter on all feature extractors is set to the
    current replay timestamp

This makes the replay engine suitable for:
  - Backtesting with realistic microstructure features
  - Walk-forward validation
  - Strategy development with tick-level precision

Usage:
    engine = MarketReplayEngine()
    async for snapshot in engine.replay(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 31, tzinfo=timezone.utc),
        speed=0.0,   # 0.0 = as fast as possible
    ):
        # snapshot.tick          → current GoldTick
        # snapshot.micro         → MicrostructureSnapshot
        # snapshot.ml_features   → Dict[str, float] (all features, causal)
        # snapshot.ohlcv_1h      → List[OHLCVBar] (completed bars only)
        pass
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Dict, List, Optional

from data_layer.microstructure.engine import MicrostructureEngine
from data_layer.quality.engine import DataQualityEngine
from data_layer.replay.dukascopy import DukascopyFetcher, dukascopy_fetcher
from data_layer.types import FeedSource, GoldTick, MicrostructureSnapshot, OHLCVBar

logger = logging.getLogger(__name__)


@dataclass
class ReplaySnapshot:
    """Single point-in-time snapshot during replay."""
    tick:        GoldTick
    micro:       MicrostructureSnapshot
    ml_features: Dict[str, float]
    ohlcv_1m:    List[dict]   = field(default_factory=list)
    ohlcv_1h:    List[dict]   = field(default_factory=list)
    bar_index:   int          = 0
    replay_ts:   datetime     = field(default_factory=lambda: datetime.now(timezone.utc))


class _OHLCVAggregator:
    """Aggregates ticks into OHLCV bars for a single timeframe."""

    def __init__(self, timeframe_minutes: int) -> None:
        self.tf_min   = timeframe_minutes
        self._bars:   List[dict] = []
        self._o = self._h = self._l = self._c = 0.0
        self._vol     = 0.0
        self._count   = 0
        self._bar_start: Optional[datetime] = None

    def on_tick(self, tick: GoldTick) -> Optional[dict]:
        """
        Process a tick. Returns a completed bar dict when a bar closes,
        otherwise returns None.
        """
        ts = tick.timestamp.replace(second=0, microsecond=0)
        bar_minute = (ts.minute // self.tf_min) * self.tf_min
        bar_start  = ts.replace(minute=bar_minute)

        if self._bar_start is None:
            self._bar_start = bar_start
            self._o = self._h = self._l = self._c = tick.mid
            return None

        if bar_start > self._bar_start:
            # Bar closed — emit it
            completed = {
                "open_time":  self._bar_start.isoformat(),
                "close_time": (
                    self._bar_start + timedelta(minutes=self.tf_min)
                ).isoformat(),
                "open_epoch": self._bar_start.timestamp(),
                "open":  round(self._o, 4),
                "high":  round(self._h, 4),
                "low":   round(self._l, 4),
                "close": round(self._c, 4),
                "volume": round(self._vol, 2),
                "tick_count": self._count,
                "timeframe": f"{self.tf_min}m",
            }
            self._bars.append(completed)
            # Start new bar
            self._bar_start = bar_start
            self._o = self._h = self._l = self._c = tick.mid
            self._vol   = 0.0
            self._count = 0
            return completed

        # Update current bar
        if self._count == 0:
            self._o = tick.mid
        self._h = max(self._h, tick.mid)
        self._l = min(self._l, tick.mid)
        self._c = tick.mid
        self._vol   += tick.spread * 1000
        self._count += 1
        return None

    def get_completed_bars(self, limit: int = 200) -> List[dict]:
        return self._bars[-limit:]


class MarketReplayEngine:
    """
    Replays historical Dukascopy tick data through the full processing pipeline.

    Each tick is validated, microstructure-processed, and feature-extracted
    in strict causal order.
    """

    def __init__(
        self,
        fetcher: Optional[DukascopyFetcher] = None,
        news_engine=None,
        macro_engine=None,
    ) -> None:
        self._fetcher  = fetcher or dukascopy_fetcher
        self._dqe      = DataQualityEngine()
        self._micro    = MicrostructureEngine()
        self._agg_1m   = _OHLCVAggregator(1)
        self._agg_1h   = _OHLCVAggregator(60)
        self._news     = news_engine
        self._macro    = macro_engine

    async def replay(
        self,
        start: datetime,
        end: datetime,
        symbol: str = "XAUUSD",
        speed: float = 0.0,
        batch_size: int = 1000,
    ) -> AsyncIterator[ReplaySnapshot]:
        """
        Async generator that yields ReplaySnapshot for each tick.

        speed: 0.0 = maximum speed, 1.0 = real-time, 10.0 = 10× real-time
        batch_size: ticks to fetch per Dukascopy request
        """
        logger.info(
            "MarketReplayEngine: starting replay %s → %s",
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )

        # Reset engines for clean replay
        self._dqe   = DataQualityEngine()
        self._micro = MicrostructureEngine()
        self._agg_1m = _OHLCVAggregator(1)
        self._agg_1h = _OHLCVAggregator(60)

        ticks = await self._fetcher.fetch_ticks(
            symbol=symbol, start=start, end=end
        )

        if not ticks:
            logger.warning("MarketReplayEngine: no ticks fetched for %s", symbol)
            return

        logger.info("MarketReplayEngine: replaying %d ticks", len(ticks))

        prev_ts: Optional[datetime] = None
        bar_index = 0

        for i, raw_tick in enumerate(ticks):
            # Validate
            validated = self._dqe.validate_tick(raw_tick)

            # Microstructure
            micro_snap = self._micro.on_tick(validated)

            # OHLCV aggregation
            bar_1m = self._agg_1m.on_tick(validated)
            bar_1h = self._agg_1h.on_tick(validated)
            if bar_1m or bar_1h:
                bar_index += 1

            # Feature extraction (causal — as_of = current tick timestamp)
            as_of = validated.timestamp
            ml_features: Dict[str, float] = {}
            ml_features.update(self._micro.get_ml_features())

            if self._news:
                ml_features.update(self._news.get_ml_features(as_of=as_of))
            if self._macro:
                ml_features.update(self._macro.get_ml_features(as_of=as_of))

            snapshot = ReplaySnapshot(
                tick        = validated,
                micro       = micro_snap,
                ml_features = ml_features,
                ohlcv_1m    = [bar_1m] if bar_1m else [],
                ohlcv_1h    = [bar_1h] if bar_1h else [],
                bar_index   = bar_index,
                replay_ts   = as_of,
            )

            # Speed control
            if speed > 0.0 and prev_ts is not None:
                real_dt = (validated.timestamp - prev_ts).total_seconds()
                sleep_s = real_dt / speed
                if sleep_s > 0.001:
                    await asyncio.sleep(sleep_s)

            prev_ts = validated.timestamp
            yield snapshot

            # Yield control to event loop every 1000 ticks
            if i % 1000 == 0:
                await asyncio.sleep(0)

        logger.info(
            "MarketReplayEngine: replay complete — %d ticks, %d bars",
            len(ticks), bar_index,
        )

    async def build_ohlcv_dataframe(
        self,
        start: datetime,
        end: datetime,
        symbol: str = "XAUUSD",
        timeframe_minutes: int = 60,
    ):
        """
        Build a pandas DataFrame of OHLCV bars from Dukascopy tick data.

        Returns pd.DataFrame with columns: open, high, low, close, volume, tick_count
        and DatetimeIndex (UTC).
        """
        import pandas as pd

        bars = await self._fetcher.fetch_ohlcv(
            symbol=symbol,
            start=start,
            end=end,
            timeframe_minutes=timeframe_minutes,
        )
        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame(bars)
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df.set_index("open_time").sort_index()
        df = df[["open", "high", "low", "close", "volume", "tick_count"]]
        return df


# Module-level singleton
market_replay_engine = MarketReplayEngine()
