# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/replay/engine.py
=============================
MarketReplayEngine — deterministic historical replay using Dukascopy data.

Responsibilities
----------------
- Fetch historical tick data from Dukascopy (bi5 binary format)
- Replay ticks through the full data pipeline (DQE → Microstructure → Norm)
- Build OHLCV DataFrames for ML backtesting
- Enforce strict causal ordering — no future data ever leaks
- Expose replay_bar() for bar-by-bar backtesting with feature injection

Causal guarantee
----------------
Every tick replayed carries a timestamp from the past. The replay engine
never provides data beyond the current replay cursor position. The ML
pipeline's add_data_layer_features(as_of=cursor) enforces this at the
feature level.

Usage
-----
    engine = MarketReplayEngine()

    # Build OHLCV DataFrame for backtesting
    df = await engine.build_ohlcv_dataframe(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 3, 31, tzinfo=timezone.utc),
        symbol="XAUUSD",
        timeframe_minutes=60,
    )

    # Replay tick-by-tick (for microstructure feature generation)
    async for tick in engine.replay_ticks(start, end, symbol="XAUUSD"):
        features = engine.get_replay_features(tick.timestamp)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Dict, List, Optional

import pandas as pd

from data_layer.normalization.pipeline import normalization_pipeline
from data_layer.replay.dukascopy import DukascopyFetcher, dukascopy_fetcher
from data_layer.types import FeedSource, GoldTick, TickQuality

logger = logging.getLogger(__name__)

import os
_DEFAULT_SYMBOL    = os.getenv("REPLAY_DEFAULT_SYMBOL",    "XAUUSD")
_DEFAULT_TF_MIN    = int(os.getenv("REPLAY_DEFAULT_TF_MIN", "60"))
_MAX_REPLAY_DAYS   = int(os.getenv("REPLAY_MAX_DAYS",       "365"))
_REPLAY_SPEED      = float(os.getenv("REPLAY_SPEED",        "0.0"))  # 0 = as fast as possible


class MarketReplayEngine:
    """
    Deterministic historical market replay engine.

    Uses Dukascopy bi5 tick data as the ground truth source.
    All replayed ticks pass through the same DQE + normalisation
    pipeline as live ticks — ensuring identical feature generation.
    """

    def __init__(self, fetcher: Optional[DukascopyFetcher] = None) -> None:
        self._fetcher = fetcher or dukascopy_fetcher
        self._replay_cursor: Optional[datetime] = None
        self._replay_ticks: Optional[pd.DataFrame] = None
        self._is_replaying: bool = False

    # ── OHLCV DataFrame builder ───────────────────────────────────────────────

    async def build_ohlcv_dataframe(
        self,
        start: datetime,
        end: datetime,
        symbol: str = _DEFAULT_SYMBOL,
        timeframe_minutes: int = _DEFAULT_TF_MIN,
        normalize: bool = True,
    ) -> pd.DataFrame:
        """
        Build a normalised OHLCV DataFrame from Dukascopy data.

        Parameters
        ----------
        start             : Start datetime (UTC)
        end               : End datetime (UTC)
        symbol            : Dukascopy symbol (e.g. "XAUUSD")
        timeframe_minutes : Bar size in minutes
        normalize         : Apply NormalizationPipeline (log_return, gap_flag, etc.)

        Returns
        -------
        pd.DataFrame with UTC DatetimeIndex and columns:
          open, high, low, close, volume, [log_return, log_volume, gap_flag, ohlcv_valid]
        """
        # Enforce max range
        max_end = start + timedelta(days=_MAX_REPLAY_DAYS)
        if end > max_end:
            logger.warning(
                "MarketReplayEngine: clamping end from %s to %s (%d day limit)",
                end.isoformat(), max_end.isoformat(), _MAX_REPLAY_DAYS,
            )
            end = max_end

        logger.info(
            "MarketReplayEngine: fetching %s %dmin bars %s → %s",
            symbol, timeframe_minutes,
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
        )

        df = await self._fetcher.fetch_ohlcv(
            symbol=symbol,
            start=start,
            end=end,
            timeframe_minutes=timeframe_minutes,
        )

        if df.empty:
            logger.warning(
                "MarketReplayEngine: no data returned for %s %s→%s",
                symbol, start.date(), end.date(),
            )
            return pd.DataFrame()

        if normalize:
            df = normalization_pipeline.normalize_ohlcv(df)

        logger.info(
            "MarketReplayEngine: built %d bars for %s", len(df), symbol
        )
        return df

    # ── Tick replay ───────────────────────────────────────────────────────────

    async def load_replay_ticks(
        self,
        start: datetime,
        end: datetime,
        symbol: str = _DEFAULT_SYMBOL,
    ) -> int:
        """
        Pre-load tick data for replay. Returns number of ticks loaded.

        Call this before replay_ticks() to avoid streaming latency.
        """
        ticks = await self._fetcher.fetch_ticks(symbol, start, end)
        self._replay_ticks  = ticks
        self._replay_cursor = start
        self._is_replaying  = False
        logger.info(
            "MarketReplayEngine: loaded %d ticks for replay (%s → %s)",
            len(ticks), start.date(), end.date(),
        )
        return len(ticks)

    async def replay_ticks(
        self,
        start: datetime,
        end: datetime,
        symbol: str = _DEFAULT_SYMBOL,
        speed: float = _REPLAY_SPEED,
    ) -> AsyncIterator[GoldTick]:
        """
        Async generator that yields GoldTicks in chronological order.

        Causal guarantee: yields ticks in strict timestamp order.
        speed=0 → as fast as possible (backtesting)
        speed=1 → real-time (1 second per second)
        speed=N → N× real-time

        Each tick passes through DQE validation and normalisation.
        """
        from data_layer.quality.engine import dqe

        if self._replay_ticks is None or self._replay_ticks.empty:
            await self.load_replay_ticks(start, end, symbol)

        if self._replay_ticks is None or self._replay_ticks.empty:
            return

        self._is_replaying = True
        prev_ts: Optional[datetime] = None

        for ts, row in self._replay_ticks.iterrows():
            if ts < pd.Timestamp(start, tz="UTC"):
                continue
            if ts > pd.Timestamp(end, tz="UTC"):
                break

            self._replay_cursor = ts.to_pydatetime()

            bid = float(row.get("bid", 0))
            ask = float(row.get("ask", 0))
            mid = float(row.get("mid", (bid + ask) / 2.0))

            if bid <= 0 or ask <= 0:
                continue

            raw_tick = GoldTick(
                symbol     = "XAU_USD",
                timestamp  = self._replay_cursor,
                bid        = round(bid, 4),
                ask        = round(ask, 4),
                mid        = round(mid, 4),
                source     = FeedSource.REPLAY,
                spread     = round(ask - bid, 4),
            )

            # Pass through DQE
            validated = dqe.validate_tick(raw_tick, received_at=ts.timestamp())
            # Pass through normalisation
            normalised = normalization_pipeline.normalize_tick(validated)

            # Speed control for real-time simulation
            if speed > 0 and prev_ts is not None:
                dt_s = (self._replay_cursor - prev_ts).total_seconds()
                await asyncio.sleep(dt_s / speed)

            prev_ts = self._replay_cursor
            yield normalised

        self._is_replaying = False

    # ── Replay state ──────────────────────────────────────────────────────────

    @property
    def replay_cursor(self) -> Optional[datetime]:
        """Current replay position (UTC). None if not replaying."""
        return self._replay_cursor

    @property
    def is_replaying(self) -> bool:
        return self._is_replaying

    def get_replay_features(self, as_of: datetime) -> Dict[str, float]:
        """
        Return ML features at a specific historical time.

        Delegates to orchestrator.get_ml_features(as_of=as_of) which
        enforces causal filtering on all sub-components.
        """
        try:
            from data_layer.orchestrator import orchestrator
            return orchestrator.get_ml_features(as_of=as_of)
        except Exception as exc:
            logger.debug("MarketReplayEngine.get_replay_features error: %s", exc)
            return {}

    def health(self) -> dict:
        return {
            "is_replaying":   self._is_replaying,
            "replay_cursor":  self._replay_cursor.isoformat() if self._replay_cursor else None,
            "ticks_loaded":   len(self._replay_ticks) if self._replay_ticks is not None else 0,
        }


# Module-level singleton
market_replay_engine = MarketReplayEngine()
