# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/ — compatibility shim package.

All backtesting code now lives in backtesting/ (canonical).
This package re-exports from backtesting.engine_config so that
existing imports (from backtest.engine import ...) continue to work.

New code should import from backtesting directly:

    from backtesting.engine_config import BacktestConfig, BacktestEngine, SimulatedBroker
    from backtesting import BacktestConfig, BacktestEngine, SimulatedBroker
"""

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

# Re-export modules that have been migrated to backtesting/
# These lazy imports keep the shim lightweight while providing backward compatibility.
from backtesting import data_validator  # noqa: F401
from backtesting import multi_symbol_backtest  # noqa: F401
from backtesting import reconciled_backtest_investigation  # noqa: F401
from backtesting import transaction_costs  # noqa: F401
