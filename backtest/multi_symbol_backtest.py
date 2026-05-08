# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/multi_symbol_backtest.py — compatibility shim
=======================================================
Re-exports from backtesting.multi_symbol_backtest (the canonical module).

New code should import directly from backtesting:

    from backtesting.multi_symbol_backtest import run_backtest, compute_pooled_metrics
"""
from __future__ import annotations

import warnings

warnings.warn(
    "backtest.multi_symbol_backtest is a compatibility shim. "
    "Import from backtesting.multi_symbol_backtest directly.",
    DeprecationWarning,
    stacklevel=2,
)

from backtesting.multi_symbol_backtest import (  # noqa: F401, E402
    fetch_ohlcv,
    build_features,
    backtest_symbol,
    compute_pooled_metrics,
    run_backtest,
    _max_drawdown,
    main,
)

__all__ = [
    "fetch_ohlcv",
    "build_features",
    "backtest_symbol",
    "compute_pooled_metrics",
    "run_backtest",
    "_max_drawdown",
    "main",
]
