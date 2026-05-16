# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/aggregator/ohlcv_builder.py
========================================
Real-time OHLCV bar builder from a tick stream with multiple timeframes.

Architecture
------------
``OHLCVBuilder`` maintains one ``BarState`` per (symbol, timeframe) pair.
Each call to ``on_tick()`` updates the current open bar and, when the bar
period expires, closes it and emits a completed ``OHLCVBar``.

Supported timeframes
--------------------
  "1s"   — 1 second
  "5s"   — 5 seconds
  "10s"  — 10 seconds
  "30s"  — 30 seconds
  "1m"   — 1 minute
  "3m"   — 3 minutes
  "5m"   — 5 minutes
  "15m"  — 15 minutes
  "30m"  — 30 minutes
  "1h"   — 1 hour
  "4h"   — 4 hours
  "1d"   — 1 day

Custom timeframes can be registered via ``TimeframeConfig``.

Bar close callbacks
-------------------
Register async or sync callbacks via ``register_on_bar_close()``.  Each
closed bar is dispatched to all registered callbacks.  Errors in callbacks
are logged but never propagate.

VWAP and tick count
-------------------
Each bar tracks cumulative (price × volume) and total volume for VWAP
computation.  Tick count is also tracked per bar.

Gap handling
------------
If a tick arrives with a timestamp more than one bar period after the last
tick, intermediate empty bars are synthesised (close-to-close) so downstream
consumers always receive a contiguous bar series.

Thread safety
-------------
``OHLCVBuilder`` is designed for use inside a single asyncio event loop.
All state mutations happen in ``on_tick()`` which must be called from the
same event loop.  Use ``asyncio.run_in_executor`` if calling from threads.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Timeframe registry ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeframeConfig:
    """Definition of a single timeframe."""

    name: str  # e.g. "1m"
    seconds: int  # bar duration in seconds


STANDARD_TIMEFRAMES: dict[str, TimeframeConfig] = {
    "1s": TimeframeConfig("1s", 1),
    "5s": TimeframeConfig("5s", 5),
    "10s": TimeframeConfig("10s", 10),
    "30s": TimeframeConfig("30s", 30),
    "1m": TimeframeConfig("1m", 60),
    "3m": TimeframeConfig("3m", 180),
    "5m": TimeframeConfig("5m", 300),
    "15m": TimeframeConfig("15m", 900),
    "30m": TimeframeConfig("30m", 1800),
    "1h": TimeframeConfig("1h", 3600),
    "4h": TimeframeConfig("4h", 14400),
    "1d": TimeframeConfig("1d", 86400),
}


# ── Bar state ─────────────────────────────────────────────────────────────────


@dataclass
class BarState:
    """
    Mutable state for a single open OHLCV bar.

    All prices are in the instrument's native units (USD for XAUUSD).
    ``vwap`` is computed lazily from ``_cum_pv / _cum_vol``.
    """

    symbol: str
    timeframe: str
    bar_open_ts: float  # Unix timestamp of bar open
    bar_close_ts: float  # Unix timestamp of bar close (exclusive)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0
    buy_volume: float = 0.0  # Lee-Ready classified buy volume
    sell_volume: float = 0.0  # Lee-Ready classified sell volume
    _cum_pv: float = field(default=0.0, repr=False)  # Σ(price × volume)
    _cum_vol: float = field(default=0.0, repr=False)  # Σ(volume)

    @property
    def vwap(self) -> float:
        """Volume-weighted average price for this bar."""
        return self._cum_pv / self._cum_vol if self._cum_vol > 0 else self.close

    @property
    def delta(self) -> float:
        """Buy volume minus sell volume (order flow delta)."""
        return self.buy_volume - self.sell_volume

    def update(
        self,
        price: float,
        volume: float = 0.0,
        trade_side: str = "unknown",
    ) -> None:
        """Apply a single tick to this bar."""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.tick_count += 1
        if volume > 0:
            self._cum_pv += price * volume
            self._cum_vol += volume
        if trade_side == "buy":
            self.buy_volume += volume
        elif trade_side == "sell":
            self.sell_volume += volume

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_open_ts": self.bar_open_ts,
            "bar_close_ts": self.bar_close_ts,
            "open_time": datetime.fromtimestamp(self.bar_open_ts, tz=UTC).isoformat(),
            "close_time": datetime.fromtimestamp(self.bar_close_ts, tz=UTC).isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": round(self.vwap, 6),
            "tick_count": self.tick_count,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "delta": round(self.delta, 6),
        }


# ── OHLCV builder ─────────────────────────────────────────────────────────────

BarCloseCallback = Callable[[BarState], Any]


class OHLCVBuilder:
    """
    Real-time OHLCV bar builder from a tick stream.

    Maintains one open ``BarState`` per (symbol, timeframe) pair.
    Closed bars are dispatched to registered callbacks.

    Parameters
    ----------
    timeframes:
        List of timeframe names to build bars for (e.g. ``["1m", "5m", "1h"]``).
        Defaults to all standard timeframes.
    max_gap_bars:
        Maximum number of synthetic gap-fill bars to emit when a tick arrives
        after a long silence.  Set to 0 to disable gap filling.
    custom_timeframes:
        Additional ``TimeframeConfig`` objects to register alongside the
        standard set.

    Usage::

        builder = OHLCVBuilder(timeframes=["1m", "5m"])
        builder.register_on_bar_close(my_async_handler)

        # Feed ticks:
        await builder.on_tick("XAUUSD", price=1905.5, volume=1.0,
                              timestamp=time.time(), trade_side="buy")
    """

    def __init__(
        self,
        timeframes: list[str] | None = None,
        max_gap_bars: int = 10,
        custom_timeframes: list[TimeframeConfig] | None = None,
    ) -> None:
        # Build the active timeframe registry.
        self._tf_registry: dict[str, TimeframeConfig] = dict(STANDARD_TIMEFRAMES)
        if custom_timeframes:
            for tf in custom_timeframes:
                self._tf_registry[tf.name] = tf

        self._active_timeframes: list[str] = timeframes or list(STANDARD_TIMEFRAMES.keys())
        for tf in self._active_timeframes:
            if tf not in self._tf_registry:
                raise ValueError(
                    f"Unknown timeframe '{tf}'. "
                    f"Register it via custom_timeframes or use one of: "
                    f"{list(self._tf_registry.keys())}"
                )

        self._max_gap_bars = max_gap_bars

        # (symbol, timeframe) → BarState
        self._open_bars: dict[tuple[str, str], BarState] = {}

        class _SliceableBarHistory(deque[BarState]):
            """Deque-backed history that preserves slice access for callers."""

            def __getitem__(
                self, index: int | slice
            ) -> BarState | list[BarState]:
                if isinstance(index, slice):
                    return list(self)[index]
                return super().__getitem__(index)

        # Closed bar history per (symbol, timeframe): bounded deque of BarState
        self._max_history: int = 500
        self._closed_bars: dict[
            tuple[str, str], _SliceableBarHistory
        ] = defaultdict(lambda: _SliceableBarHistory(maxlen=self._max_history))

        # Callbacks
        self._callbacks: list[BarCloseCallback] = []

        # Metrics
        self.tick_count: int = 0
        self.bars_closed: int = 0
        self.gap_bars_emitted: int = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def register_on_bar_close(self, callback: BarCloseCallback) -> None:
        """Register a sync or async callback invoked when a bar closes."""
        self._callbacks.append(callback)

    async def on_tick(
        self,
        symbol: str,
        price: float,
        volume: float = 0.0,
        timestamp: float | None = None,
        trade_side: str = "unknown",
    ) -> list[BarState]:
        """
        Process a single tick and update all active timeframe bars.

        Parameters
        ----------
        symbol:
            Instrument symbol (e.g. ``"XAUUSD"``).
        price:
            Trade or mid price.
        volume:
            Trade size (0 for quote ticks).
        timestamp:
            Unix timestamp of the tick.  Defaults to ``time.time()``.
        trade_side:
            ``"buy"``, ``"sell"``, or ``"unknown"`` for Lee-Ready classification.

        Returns
        -------
        list[BarState]
            List of bars that were closed by this tick (may be empty).
        """
        if timestamp is None:
            timestamp = time.time()

        self.tick_count += 1
        closed: list[BarState] = []

        for tf_name in self._active_timeframes:
            tf = self._tf_registry[tf_name]
            key = (symbol, tf_name)
            bar = self._open_bars.get(key)

            if bar is None:
                # First tick for this (symbol, timeframe) — open a new bar.
                bar = self._open_bar(symbol, tf_name, tf.seconds, price, timestamp)
                self._open_bars[key] = bar
                bar.update(price, volume, trade_side)
                continue

            if timestamp < bar.bar_open_ts:
                # Out-of-order tick — update current bar but don't close.
                bar.update(price, volume, trade_side)
                continue

            if timestamp < bar.bar_close_ts:
                # Tick belongs to the current bar.
                bar.update(price, volume, trade_side)
                continue

            # Tick is past the current bar's close — close it (and any gaps).
            gap_bars = await self._close_and_advance(key, bar, tf, price, volume, timestamp, trade_side)
            closed.extend(gap_bars)

        return closed

    def get_open_bar(self, symbol: str, timeframe: str) -> BarState | None:
        """Return the currently open (incomplete) bar, or None."""
        return self._open_bars.get((symbol, timeframe))

    def get_closed_bars(
        self,
        symbol: str,
        timeframe: str,
        n: int = 100,
    ) -> list[BarState]:
        """Return the last *n* closed bars in chronological order."""
        history = self._closed_bars.get((symbol, timeframe), [])
        return history[-n:]

    def get_latest_closed_bar(self, symbol: str, timeframe: str) -> BarState | None:
        """Return the most recently closed bar, or None."""
        history = self._closed_bars.get((symbol, timeframe), [])
        return history[-1] if history else None

    def symbols(self) -> list[str]:
        """Return all symbols with at least one open bar."""
        return list({sym for sym, _ in self._open_bars})

    def stats(self) -> dict[str, Any]:
        return {
            "tick_count": self.tick_count,
            "bars_closed": self.bars_closed,
            "gap_bars_emitted": self.gap_bars_emitted,
            "open_bars": len(self._open_bars),
            "active_timeframes": self._active_timeframes,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _bar_open_ts(timestamp: float, period_seconds: int) -> float:
        """Align *timestamp* to the start of its bar period."""
        return float(int(timestamp) // period_seconds * period_seconds)

    def _open_bar(
        self,
        symbol: str,
        tf_name: str,
        period_seconds: int,
        price: float,
        timestamp: float,
    ) -> BarState:
        """Create a new open bar aligned to the bar period."""
        open_ts = self._bar_open_ts(timestamp, period_seconds)
        close_ts = open_ts + period_seconds
        return BarState(
            symbol=symbol,
            timeframe=tf_name,
            bar_open_ts=open_ts,
            bar_close_ts=close_ts,
            open=price,
            high=price,
            low=price,
            close=price,
        )

    async def _close_and_advance(
        self,
        key: tuple[str, str],
        bar: BarState,
        tf: TimeframeConfig,
        price: float,
        volume: float,
        timestamp: float,
        trade_side: str,
    ) -> list[BarState]:
        """
        Close *bar* and open a new one for *timestamp*.

        If the gap between the closed bar and *timestamp* spans multiple
        periods, synthetic gap-fill bars are emitted (up to ``_max_gap_bars``).
        """
        symbol, tf_name = key
        closed: list[BarState] = []

        # Close the current bar.
        await self._emit_closed_bar(key, bar)
        closed.append(bar)

        # Determine how many bar periods were skipped.
        next_open_ts = bar.bar_close_ts
        target_open_ts = self._bar_open_ts(timestamp, tf.seconds)
        gap_count = int((target_open_ts - next_open_ts) / tf.seconds)

        # Emit synthetic gap-fill bars (close-to-close, zero volume).
        if gap_count > 0 and self._max_gap_bars > 0:
            emit_count = min(gap_count, self._max_gap_bars)
            for i in range(emit_count):
                gap_open_ts = next_open_ts + i * tf.seconds
                gap_close_ts = gap_open_ts + tf.seconds
                gap_bar = BarState(
                    symbol=symbol,
                    timeframe=tf_name,
                    bar_open_ts=gap_open_ts,
                    bar_close_ts=gap_close_ts,
                    open=bar.close,
                    high=bar.close,
                    low=bar.close,
                    close=bar.close,
                    volume=0.0,
                    tick_count=0,
                )
                await self._emit_closed_bar(key, gap_bar)
                closed.append(gap_bar)
                self.gap_bars_emitted += 1

        # Open the new bar for the current tick.
        new_bar = self._open_bar(symbol, tf_name, tf.seconds, price, timestamp)
        new_bar.update(price, volume, trade_side)
        self._open_bars[key] = new_bar

        return closed

    async def _emit_closed_bar(
        self,
        key: tuple[str, str],
        bar: BarState,
    ) -> None:
        """Store the closed bar and dispatch to callbacks."""
        history = self._closed_bars[key]
        history.append(bar)  # deque with maxlen auto-evicts oldest

        self.bars_closed += 1

        for cb in self._callbacks:
            try:
                result = cb(bar)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "OHLCVBuilder callback error for %s/%s: %s",
                    bar.symbol,
                    bar.timeframe,
                    exc,
                )

    async def flush(self, symbol: str | None = None) -> list[BarState]:
        """
        Force-close all open bars for *symbol* (or all symbols if None).

        Useful for graceful shutdown or end-of-session processing.
        The bars are closed at the current wall-clock time.
        """
        now = time.time()
        flushed: list[BarState] = []

        keys = [k for k in list(self._open_bars.keys()) if symbol is None or k[0] == symbol]
        for key in keys:
            bar = self._open_bars.pop(key, None)
            if bar is None:
                continue
            # Set close timestamp to now.
            bar.bar_close_ts = now
            await self._emit_closed_bar(key, bar)
            flushed.append(bar)

        return flushed
