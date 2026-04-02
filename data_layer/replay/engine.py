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
from datetime import datetime, timedelta
from typing import Any
from collections.abc import AsyncIterator

import pandas as pd

from data_layer.normalization.pipeline import normalization_pipeline
from data_layer.replay.dukascopy import (
    DukascopyFetcher,
    dukascopy_fetcher,
    _parse_timeframe,
)
import os

from data_layer.types import FeedSource, GoldTick

logger = logging.getLogger(__name__)

_DEFAULT_SYMBOL = os.getenv("REPLAY_DEFAULT_SYMBOL", "XAUUSD")
_DEFAULT_TF_MIN = int(os.getenv("REPLAY_DEFAULT_TF_MIN", "60"))
_MAX_REPLAY_DAYS = int(os.getenv("REPLAY_MAX_DAYS", "365"))
_REPLAY_SPEED = float(os.getenv("REPLAY_SPEED", "0.0"))  # 0 = as fast as possible


class MarketReplayEngine:
    """
    Deterministic historical market replay engine.

    Uses Dukascopy bi5 tick data as the ground truth source.
    All replayed ticks pass through the same DQE + normalisation
    pipeline as live ticks — ensuring identical feature generation.
    """

    def __init__(self, fetcher: DukascopyFetcher | None = None) -> None:
        self._fetcher = fetcher or dukascopy_fetcher
        self._replay_cursor: datetime | None = None
        self._replay_ticks: pd.DataFrame | None = None
        self._is_replaying: bool = False

    # ── OHLCV DataFrame builder ───────────────────────────────────────────────

    async def build_ohlcv_dataframe(
        self,
        start: datetime,
        end: datetime,
        symbol: str = _DEFAULT_SYMBOL,
        timeframe_minutes=_DEFAULT_TF_MIN,
        timeframe: str = None,
        normalize: bool = True,
    ) -> pd.DataFrame:
        """
        Build a normalised OHLCV DataFrame from Dukascopy data.

        Parameters
        ----------
        start             : Start datetime (UTC)
        end               : End datetime (UTC)
        symbol            : Dukascopy symbol (e.g. "XAUUSD")
        timeframe_minutes : Bar size — int (minutes) or string ("H1", "M5", etc.)
        timeframe         : Alias for timeframe_minutes (broker-style string).
                            When both are provided, timeframe takes precedence.
        normalize         : Apply NormalizationPipeline (log_return, gap_flag, etc.)

        Returns
        -------
        pd.DataFrame with UTC DatetimeIndex and columns:
          open, high, low, close, volume, [log_return, log_volume, gap_flag, ohlcv_valid]
        """
        # Resolve timeframe — accept both parameter names
        tf_spec = timeframe if timeframe is not None else timeframe_minutes
        tf_min = _parse_timeframe(tf_spec)

        # Enforce max range
        max_end = start + timedelta(days=_MAX_REPLAY_DAYS)
        if end > max_end:
            logger.warning(
                "MarketReplayEngine: clamping end from %s to %s (%d day limit)",
                end.isoformat(),
                max_end.isoformat(),
                _MAX_REPLAY_DAYS,
            )
            end = max_end

        logger.info(
            "MarketReplayEngine: fetching %s %dmin bars %s → %s",
            symbol,
            tf_min,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )

        df = await self._fetcher.fetch_ohlcv(
            symbol=symbol,
            start=start,
            end=end,
            timeframe_minutes=tf_min,
        )

        if df.empty:
            logger.warning(
                "MarketReplayEngine: no data returned for %s %s→%s",
                symbol,
                start.date(),
                end.date(),
            )
            return pd.DataFrame()

        if normalize:
            df = normalization_pipeline.normalize_ohlcv(df)

        logger.info("MarketReplayEngine: built %d bars for %s", len(df), symbol)
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
        self._replay_ticks = ticks
        self._replay_cursor = start
        self._is_replaying = False
        logger.info(
            "MarketReplayEngine: loaded %d ticks for replay (%s → %s)",
            len(ticks),
            start.date(),
            end.date(),
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
        # Import DQE once before the loop — not inside the generator body
        # to avoid repeated module lookups on every tick.
        from data_layer.quality.engine import dqe

        if self._replay_ticks is None or self._replay_ticks.empty:
            await self.load_replay_ticks(start, end, symbol)

        if self._replay_ticks is None or self._replay_ticks.empty:
            return

        # Pre-compute Timestamp bounds once (not on every iteration)
        ts_start = pd.Timestamp(start, tz="UTC")
        ts_end = pd.Timestamp(end, tz="UTC")

        self._is_replaying = True
        prev_ts: datetime | None = None

        for ts, row in self._replay_ticks.iterrows():
            if ts < ts_start:
                continue
            # Causal hard stop: never yield a tick at or after end
            if ts >= ts_end:
                break

            self._replay_cursor = ts.to_pydatetime()

            bid = float(row.get("bid", 0))
            ask = float(row.get("ask", 0))
            mid = float(row.get("mid", (bid + ask) / 2.0))

            if bid <= 0 or ask <= 0:
                continue

            # Sanity: reject ticks with inverted spread
            if ask < bid:
                logger.debug(
                    "MarketReplayEngine: inverted spread at %s bid=%.4f ask=%.4f — skipped",
                    ts,
                    bid,
                    ask,
                )
                continue

            raw_tick = GoldTick(
                symbol="XAU_USD",
                timestamp=self._replay_cursor,
                bid=round(bid, 4),
                ask=round(ask, 4),
                mid=round(mid, 4),
                source=FeedSource.REPLAY,
                spread=round(ask - bid, 4),
            )

            # Pass through DQE then normalisation — same pipeline as live ticks
            validated = dqe.validate_tick(raw_tick, received_at=ts.timestamp())
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
    def replay_cursor(self) -> datetime | None:
        """Current replay position (UTC). None if not replaying."""
        return self._replay_cursor

    @property
    def is_replaying(self) -> bool:
        return self._is_replaying

    def get_replay_features(self, as_of: datetime) -> dict[str, float]:
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

    async def replay_ohlcv_with_features(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "H1",
        macro_df: Any | None = None,
    ) -> Any | None:
        """
        Build a fully-featured OHLCV DataFrame for backtesting.

        Fetches Dukascopy OHLCV data for the given range, normalises it,
        then injects all data-layer ML features (microstructure, sentiment,
        macro calendar) at each bar using causal as_of filtering.

        This is the primary entry point for the backtesting pipeline.
        Zero look-ahead bias: features at bar t use only data available
        strictly before bar t's close time.

        Parameters
        ----------
        symbol    : Instrument symbol (e.g. 'XAUUSD')
        start     : Replay start (UTC, inclusive)
        end       : Replay end (UTC, inclusive)
        timeframe : Dukascopy timeframe string (default 'H1')
        macro_df  : Optional pre-loaded macro DataFrame to merge

        Returns a pd.DataFrame with OHLCV + all ML features, or None on error.
        """
        try:
            from ml.features_extended import build_extended_features_with_data_layer

            logger.info(
                "MarketReplayEngine: building replay OHLCV %s %s→%s [%s]",
                symbol,
                start.date(),
                end.date(),
                timeframe,
            )

            # 1. Fetch raw OHLCV from Dukascopy
            ohlcv = await self.build_ohlcv_dataframe(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
            )
            if ohlcv is None or ohlcv.empty:
                logger.warning(
                    "MarketReplayEngine: no OHLCV data for %s %s→%s",
                    symbol,
                    start.date(),
                    end.date(),
                )
                return None

            # 2. Normalise
            ohlcv = normalization_pipeline.normalize_ohlcv(ohlcv)

            # 3. Inject extended ML features (causal)
            featured = build_extended_features_with_data_layer(
                ohlcv=ohlcv,
                macro_df=macro_df,
            )

            logger.info(
                "MarketReplayEngine: replay complete — %d bars, %d features",
                len(featured),
                len(featured.columns),
            )
            return featured

        except Exception as exc:
            logger.error("MarketReplayEngine.replay_ohlcv_with_features error: %s", exc)
            return None

    async def replay_bar_by_bar(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "H1",
        callback: Any | None = None,
    ) -> int:
        """
        Replay OHLCV bars one at a time, calling `callback(bar, features)` for each.

        Enforces strict causal ordering: features injected at bar t use only
        data with timestamp < bar t's open time.

        Parameters
        ----------
        symbol    : Instrument symbol
        start     : Replay start (UTC)
        end       : Replay end (UTC)
        timeframe : Dukascopy timeframe string
        callback  : Async or sync callable(bar: pd.Series, features: dict).
                    If None, bars are counted but not processed.

        Returns the number of bars replayed.
        """
        import inspect

        try:

            ohlcv = await self.build_ohlcv_dataframe(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
            )
            if ohlcv is None or ohlcv.empty:
                return 0

            ohlcv = normalization_pipeline.normalize_ohlcv(ohlcv)
            count = 0

            for ts, bar in ohlcv.iterrows():
                self._replay_cursor = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                features = self.get_replay_features(as_of=self._replay_cursor)

                if callback is not None:
                    try:
                        if inspect.iscoroutinefunction(callback):
                            await callback(bar, features)
                        else:
                            callback(bar, features)
                    except Exception as cb_exc:
                        logger.debug(
                            "MarketReplayEngine.replay_bar_by_bar callback error at %s: %s",
                            ts,
                            cb_exc,
                        )
                count += 1

            self._replay_cursor = None
            logger.info(
                "MarketReplayEngine.replay_bar_by_bar: replayed %d bars for %s",
                count,
                symbol,
            )
            return count

        except Exception as exc:
            logger.error("MarketReplayEngine.replay_bar_by_bar error: %s", exc)
            return 0

    def get_feature_snapshot(self, as_of: datetime | None = None) -> dict[str, float]:
        """
        Return a complete ML feature snapshot at a given time.

        If as_of is None, returns current live features from the orchestrator.
        If as_of is set, returns causally-filtered historical features.

        This is the canonical method for feature retrieval in both live
        inference and backtesting — callers should never import individual
        engines directly.
        """
        target = as_of or self._replay_cursor
        if target is not None:
            return self.get_replay_features(as_of=target)
        try:
            from data_layer.orchestrator import orchestrator

            return orchestrator.get_ml_features()
        except Exception as exc:
            logger.debug("MarketReplayEngine.get_feature_snapshot error: %s", exc)
            return {}

    def health(self) -> dict:
        return {
            "is_replaying": self._is_replaying,
            "replay_cursor": self._replay_cursor.isoformat() if self._replay_cursor else None,
            "ticks_loaded": len(self._replay_ticks) if self._replay_ticks is not None else 0,
        }


# Module-level singleton
market_replay_engine = MarketReplayEngine()
