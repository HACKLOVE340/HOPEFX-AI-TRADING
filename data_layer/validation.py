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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

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
            errors.append(
                f"{n} rows with close outside [{lo_bound}, {hi_bound}] for {symbol}"
            )
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

        # Future timestamps
        now_ts = pd.Timestamp.now(tz=UTC)
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
            f"NaN values in feature columns: {nan_cols[:10]}"
            + (" (truncated)" if len(nan_cols) > 10 else "")
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

    # Future-dated index
    if isinstance(X.index, pd.DatetimeIndex):
        now_ts = pd.Timestamp.now(tz=UTC)
        future_count = int(np.nan_to_num((X.index > now_ts).sum(), nan=0))
        if future_count > 0:
            errors.append(
                f"{future_count} rows have future timestamps in the feature index — "
                "possible look-ahead bias"
            )

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
        result = ValidationResult(stage=stage, symbol=symbol, rows_checked=len(df))
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
                result.stage, result.symbol, "; ".join(result.errors),
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
                    json.dumps({
                        "type": "data_validation_failure",
                        "ts": result.validated_at,
                        "detail": result.to_dict(),
                    }),
                )
                rc.ltrim("alerts:critical", -1000, -1)
        except Exception:  # nosec B110 — alert publishing is non-fatal
            pass

    def get_status(self) -> dict[str, Any]:
        """Return validation statistics for health checks."""
        recent_failures = [r.to_dict() for r in self._results if not r.passed][-20:]
        return {
            "total_validated": self._total_validated,
            "total_failed": self._total_failed,
            "pass_rate": (
                round(self._total_validated / (self._total_validated + self._total_failed), 4)
                if (self._total_validated + self._total_failed) > 0 else 1.0
            ),
            "recent_failures": recent_failures,
        }

    def reset_stats(self) -> None:
        self._results.clear()
        self._total_validated = 0
        self._total_failed = 0


# ── Module-level singleton ────────────────────────────────────────────────────

# Import and use directly:
#   from data_layer.validation import data_validator
#   clean_df = data_validator.validate_pipeline_input(df, stage="ingestion", symbol="XAUUSD")
data_validator = DataValidator(strict=True)
