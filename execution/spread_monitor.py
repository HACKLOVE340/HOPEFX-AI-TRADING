# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/spread_monitor.py
============================
Real-time broker spread spike detector.

Monitors the bid/ask spread for each symbol tick-by-tick. Computes a rolling
reference spread (EMA over ``SPREAD_BASELINE_WINDOW`` ticks) and compares the
current spread to it.  If the current spread exceeds
``SPREAD_SPIKE_MULTIPLIER × reference``, the ``is_spread_spiking()`` method
returns ``True`` and the execution engine blocks the order.

This protects against:
- Broker spread widening during high-impact news events
- Low-liquidity periods (London/NY session close, overnight)
- Broker manipulation of entry/exit spreads

Usage (from ExecutionEngine)
----------------------------
    monitor = SpreadMonitor()
    monitor.on_tick("XAUUSD", bid=2350.10, ask=2350.40)

    if monitor.is_spread_spiking("XAUUSD"):
        # block order submission
        ...

Environment variables
---------------------
SPREAD_SPIKE_MULTIPLIER   Ratio above which spread is considered abnormal (default: 3.0)
SPREAD_BASELINE_WINDOW    Number of ticks for the EMA reference baseline (default: 50)
SPREAD_MIN_TICKS          Minimum ticks before spike detection activates (default: 20)
SPREAD_ABS_LIMIT_USD      Absolute spread limit in USD — always blocks above this (default: 5.0)
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from typing import NamedTuple

logger = logging.getLogger(__name__)

_SPIKE_MULTIPLIER = float(os.getenv("SPREAD_SPIKE_MULTIPLIER", "3.0"))
_BASELINE_WINDOW = int(os.getenv("SPREAD_BASELINE_WINDOW", "50"))
_MIN_TICKS = int(os.getenv("SPREAD_MIN_TICKS", "20"))
_ABS_LIMIT_USD = float(os.getenv("SPREAD_ABS_LIMIT_USD", "5.0"))

# ── Optional Prometheus ───────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge  # type: ignore[import]

    _spread_spike_counter = Counter(
        "hopefx_spread_spikes_total",
        "Number of spread spike events detected",
        ["symbol"],
    )
    _spread_gauge = Gauge(
        "hopefx_spread_current_usd",
        "Current bid/ask spread in USD",
        ["symbol"],
    )
    _spread_baseline_gauge = Gauge(
        "hopefx_spread_baseline_usd",
        "Rolling EMA baseline spread in USD",
        ["symbol"],
    )
    _PROM_OK = True
except Exception:  # nosec B110
    _PROM_OK = False


class SpreadSnapshot(NamedTuple):
    """Latest spread state for a symbol."""

    symbol: str
    current_spread: float
    baseline_spread: float
    ratio: float
    is_spiking: bool
    tick_count: int


class SpreadMonitor:
    """
    Per-symbol spread spike detector using exponential moving average baseline.

    Thread-safe for concurrent tick ingestion (pure Python, no locks needed for
    the deque operations since asyncio is single-threaded).
    """

    def __init__(
        self,
        spike_multiplier: float = _SPIKE_MULTIPLIER,
        baseline_window: int = _BASELINE_WINDOW,
        min_ticks: int = _MIN_TICKS,
        abs_limit_usd: float = _ABS_LIMIT_USD,
    ) -> None:
        self._spike_mult = spike_multiplier
        self._baseline_window = baseline_window
        self._min_ticks = min_ticks
        self._abs_limit = abs_limit_usd

        # Per-symbol state
        self._spreads: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._baseline_window)
        )
        self._tick_counts: dict[str, int] = defaultdict(int)
        self._ema: dict[str, float] = {}  # EMA of spread per symbol

    # ── Tick ingestion ────────────────────────────────────────────────────────

    def on_tick(self, symbol: str, bid: float, ask: float) -> SpreadSnapshot:
        """
        Record a new tick for *symbol* and return the current spread snapshot.

        Parameters
        ----------
        symbol:
            Trading symbol (e.g. ``"XAUUSD"``).
        bid:
            Best bid price.
        ask:
            Best ask price.

        Returns
        -------
        :class:`SpreadSnapshot` with current spread, baseline, ratio, and spike flag.
        """
        if bid <= 0 or ask <= 0 or ask < bid:
            if ask < bid and bid > 0 and ask > 0:
                logger.debug(
                    "SpreadMonitor: crossed market for %s (bid=%.5f > ask=%.5f) — skipping tick",
                    symbol,
                    bid,
                    ask,
                )
            return SpreadSnapshot(
                symbol=symbol,
                current_spread=0.0,
                baseline_spread=0.0,
                ratio=0.0,
                is_spiking=False,
                tick_count=self._tick_counts[symbol],
            )

        spread = ask - bid
        self._tick_counts[symbol] += 1
        self._spreads[symbol].append(spread)

        # Update EMA
        alpha = 2.0 / (min(self._tick_counts[symbol], self._baseline_window) + 1)
        if symbol not in self._ema:
            self._ema[symbol] = spread
        else:
            self._ema[symbol] = alpha * spread + (1 - alpha) * self._ema[symbol]

        baseline = self._ema[symbol]
        ratio = spread / max(baseline, 1e-10)
        spiking = self._is_spiking(symbol, spread, baseline, ratio)

        if _PROM_OK:
            try:
                _spread_gauge.labels(symbol=symbol).set(spread)
                _spread_baseline_gauge.labels(symbol=symbol).set(baseline)
                if spiking:
                    _spread_spike_counter.labels(symbol=symbol).inc()
            except Exception:  # nosec B110
                pass

        if spiking:
            logger.warning(
                "SpreadMonitor: SPREAD SPIKE on %s | current=%.5f baseline=%.5f ratio=%.1fx",
                symbol,
                spread,
                baseline,
                ratio,
            )

        return SpreadSnapshot(
            symbol=symbol,
            current_spread=spread,
            baseline_spread=baseline,
            ratio=ratio,
            is_spiking=spiking,
            tick_count=self._tick_counts[symbol],
        )

    def on_tick_obj(self, symbol: str, tick) -> SpreadSnapshot:
        """
        Convenience wrapper accepting a tick object with ``.bid`` and ``.ask``
        (or ``.mid`` as a fallback for synthetic half-spread estimate).
        """
        bid = getattr(tick, "bid", None)
        ask = getattr(tick, "ask", None)
        if bid is not None and ask is not None:
            return self.on_tick(symbol, float(bid), float(ask))
        mid = getattr(tick, "mid", None)
        if mid is not None:
            # Fallback: estimate 1-pip half-spread (conservative)
            return self.on_tick(symbol, float(mid) - 0.5, float(mid) + 0.5)
        return SpreadSnapshot(
            symbol=symbol,
            current_spread=0.0,
            baseline_spread=0.0,
            ratio=0.0,
            is_spiking=False,
            tick_count=self._tick_counts[symbol],
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def is_spread_spiking(self, symbol: str) -> bool:
        """
        Return ``True`` if the most recent spread for *symbol* is abnormally wide.

        Returns ``False`` if fewer than ``min_ticks`` have been observed (not
        enough history to establish a baseline).
        """
        if self._tick_counts[symbol] < self._min_ticks:
            return False
        spreads = list(self._spreads[symbol])
        if not spreads:
            return False
        current = spreads[-1]
        baseline = self._ema.get(symbol, current)
        ratio = current / max(baseline, 1e-10)
        return self._is_spiking(symbol, current, baseline, ratio)

    def get_snapshot(self, symbol: str) -> SpreadSnapshot:
        """Return the current spread snapshot for *symbol*."""
        spreads = list(self._spreads[symbol])
        current = spreads[-1] if spreads else 0.0
        baseline = self._ema.get(symbol, current)
        ratio = current / max(baseline, 1e-10)
        return SpreadSnapshot(
            symbol=symbol,
            current_spread=current,
            baseline_spread=baseline,
            ratio=ratio,
            is_spiking=self.is_spread_spiking(symbol),
            tick_count=self._tick_counts[symbol],
        )

    def get_all_snapshots(self) -> dict[str, SpreadSnapshot]:
        """Return snapshots for all tracked symbols."""
        return {sym: self.get_snapshot(sym) for sym in self._tick_counts}

    # ── Internals ─────────────────────────────────────────────────────────────

    def _is_spiking(self, symbol: str, spread: float, baseline: float, ratio: float) -> bool:
        """Return True if *spread* qualifies as a spike."""
        # Absolute hard limit (always blocks regardless of baseline or tick count)
        if spread > self._abs_limit:
            return True
        # Relative limit requires sufficient history
        if self._tick_counts[symbol] < self._min_ticks:
            return False
        return ratio > self._spike_mult


# ── Module-level singleton ────────────────────────────────────────────────────

_SINGLETON: SpreadMonitor | None = None


def get_spread_monitor() -> SpreadMonitor:
    """Return the global :class:`SpreadMonitor` singleton."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = SpreadMonitor()
    return _SINGLETON
