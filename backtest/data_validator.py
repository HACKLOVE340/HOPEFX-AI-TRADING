# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/data_validator.py — compatibility shim
================================================
Re-exports from backtesting.data_validator (the canonical module).

New code should import directly from backtesting:

    from backtesting.data_validator import MultiSourceValidator, fetch_validated_ohlcv
"""
from __future__ import annotations

import warnings

warnings.warn(
    "backtest.data_validator is a compatibility shim. "
    "Import from backtesting.data_validator directly.",
    DeprecationWarning,
    stacklevel=2,
)

from backtesting.data_validator import (  # noqa: F401, E402
    BarValidationResult,
    ValidationReport,
    MultiSourceValidator,
    fetch_validated_ohlcv,
)

__all__ = [
    "BarValidationResult",
    "ValidationReport",
    "MultiSourceValidator",
    "fetch_validated_ohlcv",
]
