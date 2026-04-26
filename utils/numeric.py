# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
utils/numeric.py
================
Numeric safety helpers for trading calculations.

All functions are pure, dependency-free, and safe to call from any context
(signal engine, risk manager, execution engine, ML pipeline).

Design rules
------------
- Never raise on bad input — return the fallback value instead.
- Never return NaN or inf — clamp or substitute with fallback.
- All float inputs are sanitised before arithmetic.
- Logging is intentionally absent — callers log at their own level.
"""

from __future__ import annotations

import math
from typing import Sequence


def safe_divide(
    numerator: float,
    denominator: float,
    fallback: float = 0.0,
) -> float:
    """Return numerator / denominator, or fallback when denominator is zero or
    either operand is NaN / inf.

    Examples
    --------
    >>> safe_divide(10.0, 2.0)
    5.0
    >>> safe_divide(10.0, 0.0)
    0.0
    >>> safe_divide(float('nan'), 1.0)
    0.0
    >>> safe_divide(10.0, 0.0, fallback=1.0)
    1.0
    """
    try:
        n = float(numerator)
        d = float(denominator)
        if not math.isfinite(n) or not math.isfinite(d) or d == 0.0:
            return fallback
        result = n / d
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError, ZeroDivisionError):
        return fallback


def safe_log(value: float, fallback: float = 0.0) -> float:
    """Return math.log(value), or fallback when value <= 0 or non-finite."""
    try:
        v = float(value)
        if not math.isfinite(v) or v <= 0.0:
            return fallback
        result = math.log(v)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def safe_sqrt(value: float, fallback: float = 0.0) -> float:
    """Return math.sqrt(value), or fallback when value < 0 or non-finite."""
    try:
        v = float(value)
        if not math.isfinite(v) or v < 0.0:
            return fallback
        result = math.sqrt(v)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]. Returns lo when value is NaN."""
    try:
        v = float(value)
        if not math.isfinite(v):
            return lo
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return lo


def nan_to_zero(value: float) -> float:
    """Replace NaN or inf with 0.0."""
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalise_weights(weights: Sequence[float], fallback_uniform: bool = True) -> list[float]:
    """Normalise a sequence of non-negative weights to sum to 1.0.

    When the total is zero (all weights are zero or empty sequence):
    - If fallback_uniform=True, returns uniform weights (1/n each).
    - If fallback_uniform=False, returns a list of zeros.

    NaN and inf values are replaced with 0.0 before normalisation.
    """
    cleaned = [nan_to_zero(w) for w in weights]
    total = sum(cleaned)
    if total == 0.0:
        n = len(cleaned)
        if n == 0:
            return []
        return [1.0 / n] * n if fallback_uniform else [0.0] * n
    return [w / total for w in cleaned]


def sharpe_ratio(
    returns: Sequence[float],
    annualise_factor: float = 1.0,
    min_observations: int = 2,
) -> float:
    """Compute Sharpe ratio from a sequence of returns.

    Returns 0.0 when there are fewer than min_observations, std is zero,
    or any input is non-finite.

    Parameters
    ----------
    returns:
        Sequence of per-period returns (e.g. daily P&L fractions).
    annualise_factor:
        Multiply by sqrt(periods_per_year) to annualise.
        E.g. sqrt(252) for daily, sqrt(8760) for hourly.
    min_observations:
        Minimum number of finite observations required.
    """
    finite = [nan_to_zero(r) for r in returns]
    n = len(finite)
    if n < min_observations:
        return 0.0
    mean = sum(finite) / n
    variance = sum((r - mean) ** 2 for r in finite) / n
    std = safe_sqrt(variance)
    return safe_divide(mean, std, fallback=0.0) * annualise_factor


__all__ = [
    "clamp",
    "nan_to_zero",
    "normalise_weights",
    "safe_divide",
    "safe_log",
    "safe_sqrt",
    "sharpe_ratio",
]
