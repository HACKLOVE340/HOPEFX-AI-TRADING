# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/transaction_costs.py — compatibility shim
====================================================
Re-exports from backtesting.transaction_costs (the canonical module).

New code should import directly from backtesting:

    from backtesting.transaction_costs import TransactionCostModel, get_tc_model
"""
from __future__ import annotations

import warnings

warnings.warn(
    "backtest.transaction_costs is a compatibility shim. "
    "Import from backtesting.transaction_costs directly.",
    DeprecationWarning,
    stacklevel=2,
)

from backtesting.transaction_costs import (  # noqa: F401, E402
    TransactionCostModel,
    OvernightSwapModel,
    get_tc_model,
    get_swap_model,
)

__all__ = [
    "TransactionCostModel",
    "OvernightSwapModel",
    "get_tc_model",
    "get_swap_model",
]
