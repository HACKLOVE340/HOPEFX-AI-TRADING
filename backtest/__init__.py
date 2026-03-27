# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/ — legacy module alias.

The canonical backtesting package is `backtesting/`.  This package exists
because `backtest/engine.py` has a richer BacktestConfig/SimulatedBroker API
used by the test suite.  Both packages are maintained in parallel until the
test suite is migrated to `backtesting/`.

Do not add new code here.  New backtesting work goes in `backtesting/`.
"""
