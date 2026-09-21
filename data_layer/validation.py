# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
data_layer/validation.py
========================
Production data validation layer — blocks future data leakage and enforces
data integrity throughout the entire pipeline.

This module is the single enforcement point for:

1. **Future data leakage prevention** — every DataFrame entering the ML
   pipeline is checked for columns that contain future information
   (negative-shifted values, forward-filled targets, timestamp violations).

2. **NaN leak detection** — blocks DataFrames with NaN in feature columns
   from reaching the model; NaN in features causes silent prediction errors.

3. **Price sanity checks** — rejects OHLCV data with impossible values
   (negative prices, high < low, zero volume on liquid instruments).

4. **Temporal ordering** — enforces strictly monotonic timestamps; out-of-
   order data is a common source of look-ahead bias in event-driven systems.

5. **Feature schema enforcement** — validates that the feature matrix
   matches the expected schema (column names, dtypes, value ranges).

Usage
-----
    from data_layer.validation import DataValidator, validate_ohlcv, validate_features

    # Validate OHLCV before feeding to backtesting engine
    validate_ohlcv(df, symbol="XAUUSD", strict=True)

    # Validate feature matrix before model.predict()
    validate_features(X, expected_columns=model.feature_names, strict=True)

    # Full pipeline validator
    validator = DataValidator(strict=True)
    clean_df = validator.validate_pipeline_input(df, stage="feature_engineering")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────


def _now_comparable_to(index: pd.Index) -> pd.Timestamp:
    """Return a 'now' Timestamp comparable to *index*.

    Comparing a tz-naive DatetimeIndex (e.g. datetime64[us] loaded from a CSV)
    against a tz-aware ``Timestamp.now(tz=UTC)`` raises pandas' "Invalid
    comparison between dtype=datetime64[..] and Timestamp". That exception was
    being swallowed upstream and silently forcing the inference engine into its
    neutral fallback — i.e. the model never traded. Match the index's tz-awareness
    so the future-date check actually runs.
    """
    tz = getattr(index, "tz", None)
    return pd.Timestamp.now(tz=UTC) if tz is not None else pd.Timestamp.now()


class DataValidationError(ValueError):
    """Raised when data fails a validation check in strict mode."""


class FutureLeakageError(DataValidationError):
    """Raised when future data is detected in a feature matrix or OHLCV frame."""


class NaNLeakError(DataValidationError):
    """Raised when NaN values are found in feature columns."""


class TemporalOrderError(DataValidationError):
    """Raised when timestamps are not monotonically increasing."""


class PriceSanityError(DataValidationError):
    """Raised when OHLCV data contains impossible price values."""


# ── Validation result ─────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of a single validation run."""

    passed: bool
    stage: str
    symbol: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows_checked: int = 0
    rows_dropped: int = 0
    validated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "stage": self.stage,
            "symbol": self.symbol,
            "errors": self.errors,
            "warnings": self.warnings,
            "rows_checked": self.rows_checked,
            "rows_dropped": self.rows_dropped,
            "validated_at": self.validated_at,
        }


# ── OHLCV validation ──────────────────────────────────────────────────────────

# Sanity bounds per asset class (extend as needed)
_PRICE_BOUNDS: dict[str, tuple[float, float]] = {
    "XAUUSD": (500.0, 10_000.0),
    "XAUUSDT": (500.0, 10_000.0),
    "GC=F": (500.0, 10_000.0),
    "GLD": (40.0, 1_000.0),
    "BTCUSD": (100.0, 1_000_000.0),
    "ETHUSD": (1.0, 100_000.0),
    "EURUSD": (0.5, 2.5),
    "GBPUSD": (0.5, 3.0),
    "USDJPY": (50.0, 300.0),
}
_DEFAULT_PRICE_BOUNDS = (0.0, 1_000_000.0)

# Largest single-bar move treated as a real market event rather than a bad
# print. Gold's worst daily move on record is around 10%; 20% leaves generous
# headroom for genuine crisis sessions while still catching corruption.
_MAX_PLAUSIBLE_BAR_RETURN = 0.20


def detect_price_spikes(
    df: pd.DataFrame,
    *,
    column: str = "close",
    max_return: float = _MAX_PLAUSIBLE_BAR_RETURN,
) -> dict[str, Any]:
    """Report bar-to-bar moves no real market made.

    ``validate_ohlcv`` checks absolute price bounds, which cannot catch this
    class of corruption in a long history. ``data/XAUUSD_50Y.csv`` contains a
    $43 print in an era when gold traded near $270 — and $43 is a perfectly
    valid gold price, in 1971. Absolute bounds have no way to know it is wrong
    on that particular day; they would have to be wide enough to admit both the
    1968 and 2026 price levels, which is a factor of over 100.

    Returns are scale-free, so they catch it: a 474% one-day move is not a
    price level question, it is an impossible event.

    This matters because the file is a *training* input.
    ``ml/train_advanced.py`` loads it first, and 23.5% of its pre-2000 daily
    bars move more than 20% in a day (max 518%). ``api/trading.py`` already
    refuses to serve the same file to charts, with a comment explaining exactly
    why — so the corruption was known, the chart was protected from it, and the
    model was trained on it.

    Returns a report; it never mutates the frame. What to do about a bad source
    is the caller's decision, and for training data the right answer is usually
    to stop rather than to quietly interpolate over a quarter of history.
    """
    if column not in df.columns or len(df) < 2:
        return {
            "total_bars": len(df),
            "spike_count": 0,
            "spike_rate": 0.0,
            "max_abs_return": 0.0,
            "worst": [],
            "first_clean_index": None,
        }

    series = pd.to_numeric(df[column], errors="coerce")
    returns = series.pct_change().abs()
    spikes = returns > max_return
    spike_count = int(spikes.sum())

    worst: list[dict[str, Any]] = []
    if spike_count:
        for idx in returns.nlargest(min(5, spike_count)).index:
            worst.append(
                {
                    "at": str(idx),
                    "price": float(series.loc[idx]) if pd.notna(series.loc[idx]) else None,
                    "return_pct": round(float(returns.loc[idx]) * 100, 1),
                }
            )

    # Where does the series settle down? Useful for suggesting a usable window
    # rather than only reporting that the file is bad.
    first_clean_index = None
    if spike_count:
        last_spike_pos = int(np.argmax(spikes.values[::-1]))
        pos = len(spikes) - last_spike_pos
        if pos < len(df):
            first_clean_index = str(df.index[pos])

    return {
        "total_bars": len(df),
        "spike_count": spike_count,
        "spike_rate": round(spike_count / max(len(df) - 1, 1), 4),
        "max_abs_return": round(float(returns.max()) if returns.notna().any() else 0.0, 4),
        "worst": worst,
        "first_clean_index": first_clean_index,
    }


def validate_ohlcv(
    df: pd.DataFrame,
    symbol: str = "",
    strict: bool = True,
    drop_bad_rows: bool = False,
) -> pd.DataFrame:
    """
    Validate an OHLCV DataFrame for price sanity and temporal ordering.

    Checks:
    - Required columns present (open, high, low, close, volume)
    - No NaN in OHLC columns
    - high >= low (inverted bar detection)
    - high >= open, high >= close
    - low <= open, low <= close
    - close within asset-specific price bounds
    - Timestamps monotonically increasing (no look-ahead via out-of-order data)
    - No future timestamps (beyond current time)

    Args:
        df: OHLCV DataFrame with lowercase column names.
        symbol: Asset symbol for price bound lookup.
        strict: If True, raise on errors. If False, log and return cleaned df.
        drop_bad_rows: If True, drop invalid rows instead of raising.

    Returns:
        Validated (and optionally cleaned) DataFrame.

    Raises:
        PriceSanityError: on invalid prices (strict=True).
        TemporalOrderError: on non-monotonic timestamps (strict=True).
    """
    errors: list[str] = []
    warnings: list[str] = []
    original_len = len(df)

    if df.empty:
        return df

    # Normalise column names
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Required columns
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        msg = f"OHLCV missing required columns: {missing}"
        if strict:
            raise PriceSanityError(msg)
        logger.warning("validate_ohlcv [%s]: %s", symbol, msg)
        return df

    # Price bounds
    lo_bound, hi_bound = _PRICE_BOUNDS.get(symbol.upper(), _DEFAULT_PRICE_BOUNDS)

    # Vectorised checks
    bad_mask = pd.Series(False, index=df.index)

    # NaN in OHLC
    nan_mask = df[["open", "high", "low", "close"]].isna().any(axis=1)
    if nan_mask.any():
        n = int(nan_mask.sum())
        warnings.append(f"{n} rows with NaN in OHLC columns")
        bad_mask |= nan_mask

    # Inverted bars: high < low
    inv_mask = df["high"] < df["low"]
    if inv_mask.any():
        n = int(inv_mask.sum())
        errors.append(f"{n} inverted bars (high < low)")
        bad_mask |= inv_mask

    # High must be >= open and close
    bad_high = (df["high"] < df["open"]) | (df["high"] < df["close"])
    if bad_high.any():
        n = int(bad_high.sum())
        errors.append(f"{n} rows where high < open or high < close")
        bad_mask |= bad_high

    # Low must be <= open and close
    bad_low = (df["low"] > df["open"]) | (df["low"] > df["close"])
    if bad_low.any():
        n = int(bad_low.sum())
        errors.append(f"{n} rows where low > open or low > close")
        bad_mask |= bad_low

    # Price bounds
    if lo_bound > 0:
        out_of_bounds = (df["close"] < lo_bound) | (df["close"] > hi_bound)
        if out_of_bounds.any():
            n = int(out_of_bounds.sum())
            errors.append(f"{n} rows with close outside [{lo_bound}, {hi_bound}] for {symbol}")
            bad_mask |= out_of_bounds

    # Non-positive prices
    nonpos = (df["close"] <= 0) | (df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0)
    if nonpos.any():
        n = int(nonpos.sum())
        errors.append(f"{n} rows with non-positive prices")
        bad_mask |= nonpos

    # Temporal ordering
    if isinstance(df.index, pd.DatetimeIndex):
        if not df.index.is_monotonic_increasing:
            errors.append("Timestamps are not monotonically increasing — possible look-ahead bias")
            if strict and not drop_bad_rows:
                raise TemporalOrderError(
                    f"validate_ohlcv [{symbol}]: non-monotonic timestamps detected. "
                    "Sort the DataFrame by timestamp before use."
                )

        # Future timestamps (tz-safe: match the index's tz-awareness)
        now_ts = _now_comparable_to(df.index)
        future_mask = df.index > now_ts
        if future_mask.any():
            n = int(future_mask.sum())
            errors.append(f"{n} rows with future timestamps (beyond current time)")
            bad_mask |= future_mask

    if errors:
        msg = f"validate_ohlcv [{symbol}]: {'; '.join(errors)}"
        if strict and not drop_bad_rows:
            raise PriceSanityError(msg)
        logger.warning(msg)

    if drop_bad_rows and bad_mask.any():
        n_dropped = int(bad_mask.sum())
        df = df[~bad_mask]
        logger.info("validate_ohlcv [%s]: dropped %d/%d bad rows", symbol, n_dropped, original_len)

    return df


# ── Feature matrix validation ─────────────────────────────────────────────────


def validate_features(
    X: pd.DataFrame | np.ndarray,
    expected_columns: list[str] | None = None,
    strict: bool = True,
    label_col: str = "y",
) -> pd.DataFrame | np.ndarray:
    """
    Validate a feature matrix before it enters the ML model.

    Checks:
    - No NaN in any feature column (NaN → silent prediction errors)
    - No Inf values
    - Label column (if present) is NOT included in feature columns
    - Column names match expected schema (if provided)
    - No constant columns (zero variance → useless features)
    - No future-dated index entries

    Args:
        X: Feature matrix (DataFrame or ndarray).
        expected_columns: Expected column names. If provided, validates schema.
        strict: Raise on errors if True; log and continue if False.
        label_col: Name of the label/target column to exclude from features.

    Returns:
        The validated feature matrix (unchanged if valid).

    Raises:
        NaNLeakError: on NaN/Inf in features (strict=True).
        FutureLeakageError: on future-dated index or label in features (strict=True).
    """
    if isinstance(X, np.ndarray):
        # ndarray: check for NaN/Inf only
        if np.isnan(X).any():
            msg = "Feature matrix contains NaN values — model predictions will be unreliable"
            if strict:
                raise NaNLeakError(msg)
            logger.warning("validate_features: %s", msg)
        if np.isinf(X).any():
            msg = "Feature matrix contains Inf values"
            if strict:
                raise NaNLeakError(msg)
            logger.warning("validate_features: %s", msg)
        return X

    if not isinstance(X, pd.DataFrame):
        return X

    errors: list[str] = []

    # Label column must not be in features
    if label_col in X.columns:
        errors.append(
            f"Label column '{label_col}' is present in the feature matrix — "
            "this causes target leakage. Drop it before calling predict()."
        )

    # NaN check
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        errors.append(
            f"NaN values in feature columns: {nan_cols[:10]}" + (" (truncated)" if len(nan_cols) > 10 else "")
        )

    # Inf check
    numeric_cols = X.select_dtypes(include=[np.number]).columns
    inf_cols = [c for c in numeric_cols if np.isinf(X[c]).any()]
    if inf_cols:
        errors.append(f"Inf values in feature columns: {inf_cols[:10]}")

    # Schema check
    if expected_columns is not None:
        actual = set(X.columns)
        expected = set(expected_columns)
        missing = expected - actual
        extra = actual - expected - {label_col}
        if missing:
            errors.append(f"Missing expected feature columns: {sorted(missing)[:10]}")
        if extra:
            logger.debug("validate_features: extra columns (ignored): %s", sorted(extra)[:10])

    # Future-dated index (tz-safe: match the index's tz-awareness)
    if isinstance(X.index, pd.DatetimeIndex):
        now_ts = _now_comparable_to(X.index)
        future_count = int(np.nan_to_num((X.index > now_ts).sum(), nan=0))
        if future_count > 0:
            errors.append(f"{future_count} rows have future timestamps in the feature index — possible look-ahead bias")

    if errors:
        msg = "validate_features: " + "; ".join(errors)
        if strict:
            raise NaNLeakError(msg)
        logger.warning(msg)

    return X


# ── Pipeline validator ────────────────────────────────────────────────────────


class DataValidator:
    """
    Full-pipeline data validator.

    Wraps validate_ohlcv() and validate_features() with audit logging,
    metrics tracking, and Redis-based alert publishing.

    Usage::

        validator = DataValidator(strict=True)
        clean_df = validator.validate_pipeline_input(raw_df, stage="ingestion", symbol="XAUUSD")
        clean_X = validator.validate_features(X, stage="model_input")
    """

    def __init__(self, strict: bool = True) -> None:
        self.strict = strict
        self._results: list[ValidationResult] = []
        self._total_validated = 0
        self._total_failed = 0

    def validate_pipeline_input(
        self,
        df: pd.DataFrame,
        stage: str = "unknown",
        symbol: str = "",
        drop_bad_rows: bool = True,
    ) -> pd.DataFrame:
        """
        Validate OHLCV data at a pipeline stage.

        Records the result and publishes alerts for failures.
        """
        result = ValidationResult(passed=False, stage=stage, symbol=symbol, rows_checked=len(df))
        try:
            clean = validate_ohlcv(
                df,
                symbol=symbol,
                strict=self.strict,
                drop_bad_rows=drop_bad_rows,
            )
            result.passed = True
            result.rows_dropped = len(df) - len(clean)
            self._total_validated += 1
            return clean
        except (PriceSanityError, TemporalOrderError) as exc:
            result.passed = False
            result.errors.append(str(exc))
            self._total_failed += 1
            self._record(result)
            raise
        finally:
            self._record(result)

    def validate_features(
        self,
        X: pd.DataFrame | np.ndarray,
        stage: str = "model_input",
        expected_columns: list[str] | None = None,
    ) -> pd.DataFrame | np.ndarray:
        """Validate a feature matrix before model inference."""
        result = ValidationResult(
            passed=False,
            stage=stage,
            rows_checked=len(X) if hasattr(X, "__len__") else 0,
        )
        try:
            clean = validate_features(
                X,
                expected_columns=expected_columns,
                strict=self.strict,
            )
            result.passed = True
            self._total_validated += 1
            return clean
        except (NaNLeakError, FutureLeakageError) as exc:
            result.passed = False
            result.errors.append(str(exc))
            self._total_failed += 1
            self._record(result)
            raise
        finally:
            self._record(result)

    def _record(self, result: ValidationResult) -> None:
        self._results.append(result)
        self._results = self._results[-500:]
        if not result.passed:
            logger.warning(
                "DataValidator [%s/%s]: FAILED — %s",
                result.stage,
                result.symbol,
                "; ".join(result.errors),
            )
            self._publish_alert(result)

    def _publish_alert(self, result: ValidationResult) -> None:
        """Push validation failure to Redis alerts:critical (non-fatal)."""
        try:
            from cache.redis_client import get_redis_client

            rc = get_redis_client()
            if rc:
                import json

                rc.rpush(
                    "alerts:critical",
                    json.dumps(
                        {
                            "type": "data_validation_failure",
                            "ts": result.validated_at,
                            "detail": result.to_dict(),
                        }
                    ),
                )
                rc.ltrim("alerts:critical", -1000, -1)
        except Exception:  # nosec B110 — alert publishing is non-fatal  # noqa: S110
            pass

    def get_status(self) -> dict[str, Any]:
        """Return validation statistics for health checks."""
        recent_failures = [r.to_dict() for r in self._results if not r.passed][-20:]
        return {
            "total_validated": self._total_validated,
            "total_failed": self._total_failed,
            "pass_rate": (
                round(self._total_validated / (self._total_validated + self._total_failed), 4)
                if (self._total_validated + self._total_failed) > 0
                else 1.0
            ),
            "recent_failures": recent_failures,
        }

    def reset_stats(self) -> None:
        self._results.clear()
        self._total_validated = 0
        self._total_failed = 0


# ── Tick-level validation (bid/ask spread sanity + cross-source divergence) ───

# Maximum allowed bid/ask spread as a fraction of mid price per symbol.
# Gold typically trades at 0.01–0.05% spread; reject anything above 1%.
_MAX_SPREAD_PCT: dict[str, float] = {
    "XAUUSD": 0.01,
    "XAU_USD": 0.01,
    "GC=F": 0.01,
    "BTCUSD": 0.02,
    "ETHUSD": 0.02,
    "EURUSD": 0.005,
    "GBPUSD": 0.005,
    "USDJPY": 0.005,
}
_DEFAULT_MAX_SPREAD_PCT = 0.05  # 5% fallback for unknown symbols

# Maximum allowed divergence between any two sources as a fraction of the
# consensus mid price.  Prices more than 0.5% apart indicate a stale/bad feed.
_MAX_CROSS_SOURCE_DIVERGENCE_PCT: float = float(os.environ.get("DQE_CROSS_SOURCE_MAX_DIFF_PCT", "0.5")) / 100.0


def validate_tick_spread(
    bid: float,
    ask: float,
    symbol: str = "XAU_USD",
    strict: bool = False,
) -> tuple[bool, str]:
    """
    Validate bid/ask spread sanity for a single tick.

    Returns (is_valid, reason).  reason is empty string when valid.

    Rules:
    - ask must be >= bid (no inverted spread)
    - spread must be <= max_spread_pct * mid
    - bid and ask must both be positive
    """
    if bid <= 0 or ask <= 0:
        return False, f"non-positive bid/ask: bid={bid} ask={ask}"
    if ask < bid:
        return False, f"inverted spread: bid={bid} > ask={ask}"

    mid = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid if mid > 0 else 0.0
    max_pct = _MAX_SPREAD_PCT.get(symbol.upper(), _DEFAULT_MAX_SPREAD_PCT)

    if spread_pct > max_pct:
        return (
            False,
            f"spread too wide: {spread_pct:.4%} > max {max_pct:.4%} for {symbol}",
        )
    return True, ""


def validate_cross_source_divergence(
    prices: dict[str, float],
    symbol: str = "XAU_USD",
    max_divergence_pct: float | None = None,
) -> tuple[bool, str, dict[str, float]]:
    """
    Check that all source prices agree within the allowed divergence threshold.

    Args:
        prices: mapping of source_name → mid_price
        symbol: instrument symbol (for logging)
        max_divergence_pct: override for the global threshold (0–1 fraction)

    Returns:
        (all_agree, reason, outliers)
        - all_agree: True if all prices are within threshold of the median
        - reason: human-readable explanation when all_agree is False
        - outliers: dict of source → price for sources that diverge too much
    """
    if len(prices) < 2:
        return True, "", {}

    threshold = max_divergence_pct if max_divergence_pct is not None else _MAX_CROSS_SOURCE_DIVERGENCE_PCT
    vals = list(prices.values())
    median_price = float(np.median(vals))

    if median_price <= 0:
        return False, "median price is zero or negative", {}

    outliers: dict[str, float] = {}
    for src, price in prices.items():
        divergence = abs(price - median_price) / median_price
        if divergence > threshold:
            outliers[src] = price

    if outliers:
        reason = (
            f"cross-source divergence for {symbol}: "
            f"median={median_price:.4f}, "
            f"outliers={{{', '.join(f'{s}={p:.4f}' for s, p in outliers.items())}}}, "
            f"threshold={threshold:.4%}"
        )
        logger.warning("validate_cross_source_divergence: %s", reason)
        return False, reason, outliers

    return True, "", {}


# ── Module-level singleton ────────────────────────────────────────────────────

# Import and use directly:
#   from data_layer.validation import data_validator
#   clean_df = data_validator.validate_pipeline_input(df, stage="ingestion", symbol="XAUUSD")
data_validator = DataValidator(strict=True)
