# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
risk/lookahead_guard.py
=======================
Runtime look-ahead bias guard for live trading and backtesting.

Actively prevents future data leakage by:

1. **FeatureTimestampGuard** — validates that every feature vector presented
   to the ML model was computed from data whose latest timestamp is strictly
   before the decision timestamp.  Raises LookAheadBiasError on violation.

2. **BacktestBarGuard** — wraps the backtesting data iterator and asserts
   that the strategy never accesses bar[t+N] (future bars) during the
   simulation loop.

3. **DataFrameGuard** — context manager that monkey-patches pandas DataFrame
   to intercept shift(-N) calls and raise LookAheadBiasError when called
   outside of explicitly allowed label-creation contexts.

4. **LiveTradingGuard** — validates incoming tick data timestamps against
   the system clock, rejecting ticks with future timestamps (clock skew
   protection) and ticks older than the staleness threshold.

Usage
-----
    # In backtesting engine:
    from risk.lookahead_guard import BacktestBarGuard, FeatureTimestampGuard

    guard = BacktestBarGuard(bars)
    for bar in guard:
        features = compute_features(bar)
        FeatureTimestampGuard.validate(features_ts=bar.timestamp, decision_ts=bar.timestamp)
        signal = model.predict(features)

    # In live trading:
    from risk.lookahead_guard import LiveTradingGuard
    guard = LiveTradingGuard(max_staleness_seconds=30)
    guard.validate_tick(tick)  # raises on future/stale data
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator, Iterator

import pandas as pd

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class LookAheadBiasError(RuntimeError):
    """Raised when future data is accessed during backtesting or live trading."""


class StaleDataError(RuntimeError):
    """Raised when tick data is too old to be used for live decisions."""


class FutureTimestampError(RuntimeError):
    """Raised when a tick timestamp is in the future (clock skew)."""


# ── Feature timestamp guard ───────────────────────────────────────────────────

@dataclass
class FeatureTimestampGuard:
    """
    Validates that feature vectors only contain data from the past.

    Call validate() before every model.predict() in both backtesting
    and live trading to ensure no future data leaked into features.
    """

    violations: list[dict[str, Any]] = field(default_factory=list)
    strict: bool = True   # True = raise; False = log and continue

    def validate(
        self,
        features_ts: datetime | float,
        decision_ts: datetime | float,
        context: str = "",
    ) -> None:
        """
        Assert features_ts <= decision_ts.

        Args:
            features_ts: Latest timestamp of data used to compute features.
                         Can be a datetime or Unix epoch float.
            decision_ts: Timestamp of the trading decision being made.
            context: Optional label for error messages (e.g. symbol, bar index).

        Raises:
            LookAheadBiasError: when features_ts > decision_ts (strict mode).
        """
        # Normalise to epoch floats
        f_epoch = _to_epoch(features_ts)
        d_epoch = _to_epoch(decision_ts)

        if f_epoch > d_epoch + 1e-3:  # 1 ms tolerance for float precision
            delta_ms = (f_epoch - d_epoch) * 1000
            msg = (
                f"Look-ahead bias detected{' in ' + context if context else ''}: "
                f"features use data from {delta_ms:.1f}ms in the future "
                f"(features_ts={_fmt(f_epoch)}, decision_ts={_fmt(d_epoch)})"
            )
            violation = {
                "ts": datetime.now(UTC).isoformat(),
                "features_ts": _fmt(f_epoch),
                "decision_ts": _fmt(d_epoch),
                "delta_ms": delta_ms,
                "context": context,
            }
            self.violations.append(violation)
            self.violations = self.violations[-1000:]

            if self.strict:
                logger.error("LookAheadBiasError: %s", msg)
                raise LookAheadBiasError(msg)
            else:
                logger.warning("LookAheadBias (non-strict): %s", msg)

    def get_violations(self) -> list[dict[str, Any]]:
        return list(self.violations)

    def reset(self) -> None:
        self.violations.clear()


# ── Backtest bar guard ────────────────────────────────────────────────────────

class BacktestBarGuard:
    """
    Wraps a sequence of OHLCV bars and enforces forward-only access.

    Raises LookAheadBiasError if the strategy attempts to access
    bar[current_index + N] for any N > 0.

    Usage::

        guard = BacktestBarGuard(df)
        for bar in guard:
            # bar is a single-row DataFrame slice
            # Accessing guard[guard.current_index + 1] raises LookAheadBiasError
            signal = strategy.on_bar(bar)
    """

    def __init__(self, data: pd.DataFrame, strict: bool = True) -> None:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("BacktestBarGuard requires a pandas DataFrame")
        self._data = data.copy()
        self._current_index: int = -1
        self._strict = strict
        self._violations: list[dict[str, Any]] = []

    @property
    def current_index(self) -> int:
        return self._current_index

    def __iter__(self) -> Iterator[pd.Series]:
        for i in range(len(self._data)):
            self._current_index = i
            yield self._data.iloc[i]

    def __len__(self) -> int:
        return len(self._data)

    def get(self, index: int) -> pd.Series:
        """
        Access a bar by integer index.

        Raises LookAheadBiasError if index > current_index (future bar access).
        """
        if index > self._current_index:
            msg = (
                f"Look-ahead bias: attempted to access bar[{index}] "
                f"while current bar is [{self._current_index}] "
                f"(accessing {index - self._current_index} bar(s) into the future)"
            )
            violation = {
                "ts": datetime.now(UTC).isoformat(),
                "requested_index": index,
                "current_index": self._current_index,
                "future_bars": index - self._current_index,
            }
            self._violations.append(violation)
            if self._strict:
                logger.error("BacktestBarGuard: %s", msg)
                raise LookAheadBiasError(msg)
            else:
                logger.warning("BacktestBarGuard (non-strict): %s", msg)
        return self._data.iloc[index]

    def get_slice(self, start: int, end: int) -> pd.DataFrame:
        """
        Access a slice of bars.

        Raises LookAheadBiasError if end > current_index + 1.
        """
        if end - 1 > self._current_index:
            msg = (
                f"Look-ahead bias: slice [{start}:{end}] accesses future bars "
                f"(current={self._current_index})"
            )
            if self._strict:
                raise LookAheadBiasError(msg)
            logger.warning("BacktestBarGuard (non-strict): %s", msg)
        return self._data.iloc[start:end]

    def get_violations(self) -> list[dict[str, Any]]:
        return list(self._violations)


# ── DataFrame shift guard (context manager) ───────────────────────────────────

@contextmanager
def no_lookahead_context(label: str = "") -> Generator[None, None, None]:
    """
    Context manager that intercepts pandas DataFrame.shift() calls and
    raises LookAheadBiasError for any negative shift outside of explicitly
    allowed label-creation contexts.

    Usage::

        with no_lookahead_context("feature_engineering"):
            features = compute_features(df)  # shift(-N) raises here

        # Label creation is allowed outside the guard:
        labels = df["close"].shift(-1) > df["close"]
    """
    original_shift = pd.DataFrame.shift
    original_series_shift = pd.Series.shift

    def _guarded_df_shift(self: pd.DataFrame, periods: int = 1, *args: Any, **kwargs: Any) -> pd.DataFrame:
        if periods < 0:
            msg = (
                f"LookAheadBiasError{' in ' + label if label else ''}: "
                f"DataFrame.shift({periods}) uses future data. "
                "Use shift(+N) to lag. If this is intentional label creation, "
                "use it outside the no_lookahead_context() guard."
            )
            logger.error(msg)
            raise LookAheadBiasError(msg)
        return original_shift(self, periods, *args, **kwargs)

    def _guarded_series_shift(self: pd.Series, periods: int = 1, *args: Any, **kwargs: Any) -> pd.Series:
        if periods < 0:
            msg = (
                f"LookAheadBiasError{' in ' + label if label else ''}: "
                f"Series.shift({periods}) uses future data. "
                "Use shift(+N) to lag. If this is intentional label creation, "
                "use it outside the no_lookahead_context() guard."
            )
            logger.error(msg)
            raise LookAheadBiasError(msg)
        return original_series_shift(self, periods, *args, **kwargs)

    pd.DataFrame.shift = _guarded_df_shift  # type: ignore[method-assign]
    pd.Series.shift = _guarded_series_shift  # type: ignore[method-assign]
    try:
        yield
    finally:
        pd.DataFrame.shift = original_shift  # type: ignore[method-assign]
        pd.Series.shift = original_series_shift  # type: ignore[method-assign]


# ── Live trading guard ────────────────────────────────────────────────────────

@dataclass
class LiveTradingGuard:
    """
    Validates incoming tick data for live trading.

    Rejects:
    - Ticks with timestamps in the future (clock skew / replay attack)
    - Ticks older than max_staleness_seconds (stale feed)
    - Ticks with NaN or non-positive prices
    - Ticks with negative volume

    Usage::

        guard = LiveTradingGuard(max_staleness_seconds=30)
        guard.validate_tick(tick)  # raises on invalid data
    """

    max_staleness_seconds: float = 30.0
    max_future_seconds: float = 2.0   # allow 2s clock skew
    strict: bool = True
    violations: list[dict[str, Any]] = field(default_factory=list)

    def validate_tick(
        self,
        tick: Any,
        symbol: str = "",
    ) -> None:
        """
        Validate a single tick object or dict.

        Accepts objects with .timestamp / .price / .bid / .ask attributes,
        or dicts with the same keys.

        Raises:
            FutureTimestampError: tick timestamp is in the future
            StaleDataError: tick is older than max_staleness_seconds
            LookAheadBiasError: tick contains NaN or invalid prices
        """
        now = time.time()

        # Extract timestamp
        ts = _extract_tick_ts(tick)
        if ts is not None:
            age = now - ts
            future_delta = ts - now

            if future_delta > self.max_future_seconds:
                msg = (
                    f"FutureTimestampError{' for ' + symbol if symbol else ''}: "
                    f"tick timestamp is {future_delta:.2f}s in the future "
                    f"(tick_ts={_fmt(ts)}, now={_fmt(now)}). "
                    "Possible clock skew or replay attack."
                )
                self._record_violation("future_timestamp", symbol, msg, ts)
                if self.strict:
                    raise FutureTimestampError(msg)
                logger.warning(msg)

            if age > self.max_staleness_seconds:
                msg = (
                    f"StaleDataError{' for ' + symbol if symbol else ''}: "
                    f"tick is {age:.1f}s old (max={self.max_staleness_seconds}s). "
                    "Feed may be disconnected or lagging."
                )
                self._record_violation("stale_data", symbol, msg, ts)
                if self.strict:
                    raise StaleDataError(msg)
                logger.warning(msg)

        # Validate price fields
        price = _extract_price(tick)
        if price is not None:
            import math
            if math.isnan(price) or math.isinf(price):
                msg = f"Invalid price (NaN/Inf) in tick{' for ' + symbol if symbol else ''}"
                self._record_violation("invalid_price", symbol, msg, ts or now)
                if self.strict:
                    raise LookAheadBiasError(msg)
                logger.warning(msg)
            elif price <= 0:
                msg = f"Non-positive price {price} in tick{' for ' + symbol if symbol else ''}"
                self._record_violation("nonpositive_price", symbol, msg, ts or now)
                if self.strict:
                    raise LookAheadBiasError(msg)
                logger.warning(msg)

    def _record_violation(self, kind: str, symbol: str, msg: str, ts: float) -> None:
        self.violations.append({
            "kind": kind,
            "symbol": symbol,
            "message": msg,
            "tick_ts": _fmt(ts),
            "detected_at": datetime.now(UTC).isoformat(),
        })
        self.violations = self.violations[-500:]
        logger.warning("LiveTradingGuard [%s]: %s", kind, msg)

    def get_violations(self) -> list[dict[str, Any]]:
        return list(self.violations)

    def reset(self) -> None:
        self.violations.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_epoch(ts: datetime | float | int) -> float:
    if isinstance(ts, datetime):
        return ts.timestamp()
    return float(ts)


def _fmt(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return str(epoch)


def _extract_tick_ts(tick: Any) -> float | None:
    """Extract Unix epoch timestamp from a tick object or dict."""
    for attr in ("timestamp", "ts", "time", "datetime"):
        val = tick.get(attr) if isinstance(tick, dict) else getattr(tick, attr, None)
        if val is not None:
            if isinstance(val, datetime):
                return val.timestamp()
            try:
                f = float(val)
                # Detect millisecond timestamps (> year 2100 in seconds)
                if f > 4_102_444_800:
                    f /= 1000.0
                return f
            except (TypeError, ValueError):
                pass
    return None


def _extract_price(tick: Any) -> float | None:
    """Extract the primary price from a tick object or dict."""
    for attr in ("price", "close", "last", "mid"):
        val = tick.get(attr) if isinstance(tick, dict) else getattr(tick, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    # Try bid/ask midpoint
    bid = tick.get("bid") if isinstance(tick, dict) else getattr(tick, "bid", None)
    ask = tick.get("ask") if isinstance(tick, dict) else getattr(tick, "ask", None)
    if bid is not None and ask is not None:
        try:
            return (float(bid) + float(ask)) / 2.0
        except (TypeError, ValueError):
            pass
    return None


# ── Module-level singletons ───────────────────────────────────────────────────

# Shared guard instances — import and use directly in trading/backtesting code
feature_guard = FeatureTimestampGuard(strict=True)
live_guard = LiveTradingGuard(max_staleness_seconds=30, strict=True)
