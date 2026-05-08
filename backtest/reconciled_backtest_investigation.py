# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/reconciled_backtest_investigation.py — compatibility shim
===================================================================
Re-exports from backtesting.reconciled_backtest_investigation (canonical).

New code should import directly from backtesting:

    from backtesting.reconciled_backtest_investigation import sweep_confidence_thresholds
"""
from __future__ import annotations

import warnings

warnings.warn(
    "backtest.reconciled_backtest_investigation is a compatibility shim. "
    "Import from backtesting.reconciled_backtest_investigation directly.",
    DeprecationWarning,
    stacklevel=2,
)

from backtesting.reconciled_backtest_investigation import (  # noqa: F401, E402
    load_reconciled_trades,
    sweep_confidence_thresholds,
    sweep_hold_periods,
    sweep_costs,
)

__all__ = [
    "load_reconciled_trades",
    "sweep_confidence_thresholds",
    "sweep_hold_periods",
    "sweep_costs",
]
