# backtesting/ — Canonical Backtesting Engine

This is the single canonical backtesting package for HOPEFX.

## Module map

| Module | Purpose |
|---|---|
| `engine.py` | Core event-driven backtest loop |
| `walk_forward.py` | Walk-forward cross-validation |
| `metrics.py` | CVaR, Sharpe, drawdown, all performance metrics |
| `hyperopt.py` | Hyperparameter optimisation |
| `data_handler.py` | Bar data feed abstraction |
| `data_sources.py` | Yahoo Finance, CSV, OANDA data sources |
| `execution.py` | Simulated execution with slippage/commission |
| `portfolio.py` | Multi-asset portfolio tracking |
| `reports.py` | HTML/JSON report generation |
| `plots.py` | Equity curve, drawdown, returns plots |
| `optimizer.py` | Parameter grid/random search |

## Quick start

```python
from backtesting import BacktestEngine, BacktestConfig
from backtesting.data_sources import YahooFinanceSource

engine = BacktestEngine(config)
results = engine.run(strategy, data)
```

## Deprecated alternatives

| File | Status | Replacement |
|---|---|---|
| `backtest/engine.py` | Deprecated — kept for test compat | `backtesting/engine.py` |
| `enhanced_backtest_engine.py` | Prototype — root-level | `backtesting/backtest_engine.py` |
| `real_data_backtest.py` | Standalone script | Run directly, not imported |

Do not add new features to `backtest/` or `enhanced_backtest_engine.py`.
