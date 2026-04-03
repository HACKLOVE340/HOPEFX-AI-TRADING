# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data/validator.py — Market data quality validation

Checks incoming OHLCV bars for:
- Price sanity bounds (reject physically impossible prices)
- Intra-bar consistency (high >= low, close within high/low, etc.)
- Weekday gap detection (>5% move on a weekday is suspicious)
- Stale data detection (no new bar within expected interval)

Usage::

    from data.validator import DataValidator, ValidationResult

    validator = DataValidator(symbol="XAUUSD")
    result = validator.validate_bar(bar)
    if not result.ok:
        logger.warning("Bad bar: %s", result.errors)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sanity bounds per symbol (extend as needed)
# ---------------------------------------------------------------------------

_PRICE_BOUNDS: dict[str, tuple[float, float]] = {
    # (min_price, max_price)
    "XAUUSD": (500.0, 10_000.0),  # Gold: $500–$10,000 per troy oz
    "EURUSD": (0.5, 2.5),
    "GBPUSD": (0.5, 3.0),
    "USDJPY": (50.0, 300.0),
    "BTCUSD": (100.0, 1_000_000.0),
    "AUDUSD": (0.3, 1.5),
    "USDCHF": (0.5, 2.5),
}

_DEFAULT_BOUNDS = (0.0001, 1_000_000.0)

# Weekday gap threshold — a move larger than this on a weekday triggers a warning
_WEEKDAY_GAP_PCT = 0.05  # 5%

# Stale data: alert if no new bar arrives within this many multiples of the timeframe
_STALE_MULTIPLIER = 2.0


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class DataValidator:
    """
    Validates OHLCV bars for a given symbol.

    Args:
        symbol:           Trading symbol (e.g. "XAUUSD").
        timeframe_secs:   Expected bar interval in seconds (3600 = H1).
                          Used for stale-data detection.
    """

    def __init__(self, symbol: str = "XAUUSD", timeframe_secs: int = 3600) -> None:
        self.symbol = symbol.upper()
        self.timeframe_secs = timeframe_secs
        self._price_min, self._price_max = _PRICE_BOUNDS.get(self.symbol, _DEFAULT_BOUNDS)
        self._last_bar_time: datetime | None = None
        self._last_close: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_bar(self, bar: dict) -> ValidationResult:
        """
        Validate a single OHLCV bar dict.

        Expected keys: open, high, low, close, volume, timestamp (optional).
        Returns a ValidationResult with ok=True if all checks pass.
        """
        result = ValidationResult(ok=True)

        try:
            o = float(bar["open"])
            h = float(bar["high"])
            l = float(bar["low"])
            c = float(bar["close"])
            v = float(bar.get("volume", 0))
        except (KeyError, TypeError, ValueError) as exc:
            result.add_error(f"Missing or non-numeric OHLCV field: {exc}")
            return result

        # ── Price sanity bounds ──────────────────────────────────────────
        for label, price in [("open", o), ("high", h), ("low", l), ("close", c)]:
            if not (self._price_min <= price <= self._price_max):
                result.add_error(
                    f"{label}={price} outside sanity bounds [{self._price_min}, {self._price_max}] for {self.symbol}"
                )

        # ── Intra-bar consistency ────────────────────────────────────────
        if h < l:
            result.add_error(f"high={h} < low={l}")
        if not (l <= o <= h):
            result.add_error(f"open={o} outside [low={l}, high={h}]")
        if not (l <= c <= h):
            result.add_error(f"close={c} outside [low={l}, high={h}]")
        if v < 0:
            result.add_error(f"volume={v} is negative")

        # ── Weekday gap detection ────────────────────────────────────────
        if self._last_close is not None and self._last_close > 0:
            gap_pct = abs(o - self._last_close) / self._last_close
            ts = bar.get("timestamp")
            is_weekend_open = False
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
                    # Monday open after weekend gap is expected
                    is_weekend_open = dt.weekday() == 0
                except Exception as exc:
                    logger.debug(
                        "validate_bar: could not parse timestamp for gap check: %r — %s",
                        ts,
                        exc,
                    )
            if gap_pct > _WEEKDAY_GAP_PCT and not is_weekend_open:
                result.add_warning(
                    f"Large gap detected: open={o} vs prev_close={self._last_close:.4f} "
                    f"({gap_pct:.1%}) — possible bad tick or news event"
                )

        # ── Stale data detection ─────────────────────────────────────────
        ts = bar.get("timestamp")
        if ts and self._last_bar_time is not None:
            try:
                dt = datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                expected_max_gap = timedelta(seconds=self.timeframe_secs * _STALE_MULTIPLIER)
                actual_gap = dt - self._last_bar_time
                if actual_gap > expected_max_gap:
                    result.add_warning(f"Stale data gap: {actual_gap} between bars (expected <= {expected_max_gap})")
            except Exception as exc:
                logger.debug(
                    "validate_bar: could not parse timestamp for stale check: %r — %s",
                    ts,
                    exc,
                )

        # ── Update state for next call ───────────────────────────────────
        if result.ok:
            self._last_close = c
            ts = bar.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    self._last_bar_time = dt
                except Exception as exc:
                    logger.debug(
                        "validate_bar: could not parse timestamp for state update: %r — %s",
                        ts,
                        exc,
                    )

        return result

    def validate_bars(self, bars: list[dict]) -> list[ValidationResult]:
        """Validate a sequence of bars in order. State is carried between bars."""
        return [self.validate_bar(b) for b in bars]

    def reset(self) -> None:
        """Reset stateful checks (last close, last bar time)."""
        self._last_bar_time = None
        self._last_close = None


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def validate_ohlcv(
    bars: list[dict],
    symbol: str = "XAUUSD",
    timeframe_secs: int = 3600,
    raise_on_error: bool = False,
) -> list[ValidationResult]:
    """
    Validate a list of OHLCV bars and optionally raise on the first error.

    Args:
        bars:             List of OHLCV dicts.
        symbol:           Trading symbol for bounds lookup.
        timeframe_secs:   Expected bar interval for stale-data detection.
        raise_on_error:   If True, raise ValueError on the first invalid bar.

    Returns:
        List of ValidationResult, one per bar.
    """
    validator = DataValidator(symbol=symbol, timeframe_secs=timeframe_secs)
    results = []
    for i, bar in enumerate(bars):
        r = validator.validate_bar(bar)
        if not r.ok:
            logger.warning("Bar %d validation failed: %s", i, r.errors)
            if raise_on_error:
                raise ValueError(f"Bar {i} failed validation: {r.errors}")
        elif r.warnings:
            logger.warning("Bar %d warnings: %s", i, r.warnings)
        results.append(r)
    return results
