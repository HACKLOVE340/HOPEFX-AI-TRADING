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
    BacktestConfig,  # noqa: F401
    BacktestEngine,  # noqa: F401
    BacktestResult,  # noqa: F401
    HistoricalDataLoader,  # noqa: F401
    SimulatedBroker,  # noqa: F401
    run_backtest,  # noqa: F401
)
