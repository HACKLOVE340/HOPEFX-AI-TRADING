"""
backtest/ — legacy module alias.

The canonical backtesting package is `backtesting/`.  This package exists
because `backtest/engine.py` has a richer BacktestConfig/SimulatedBroker API
used by the test suite.  Both packages are maintained in parallel until the
test suite is migrated to `backtesting/`.

Do not add new code here.  New backtesting work goes in `backtesting/`.
"""
