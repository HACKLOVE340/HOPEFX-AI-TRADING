# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/engine.py — compatibility shim
========================================
All classes have moved to backtesting/engine_config.py (canonical).

This shim re-exports everything so existing imports continue to work
without modification. New code should import from backtesting directly:

    from backtesting.engine_config import (
        BacktestConfig, BacktestEngine, SimulatedBroker, BacktestResult
    )
"""

import warnings

warnings.warn(
    "backtest.engine is a compatibility shim. Import from backtesting directly.",
    DeprecationWarning,
    stacklevel=2,
)

from backtesting.engine_config import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    HistoricalDataLoader,
    SimulatedBroker,
    run_backtest,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "HistoricalDataLoader",
    "SimulatedBroker",
    "run_backtest",
]
