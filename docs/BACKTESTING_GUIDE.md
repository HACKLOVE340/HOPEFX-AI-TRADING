# Backtesting Guide

> How to run, interpret, and avoid pitfalls in HOPEFX backtests.
> Last updated: 2026-04-01

---

## Overview

HOPEFX uses `backtesting/` as the canonical backtesting engine (event-driven,
walk-forward capable). The `backtest/` directory is deprecated — use `backtesting/`.

---

## Quick Start

### Via CLI

```bash
# Smoke test — synthetic data, ~30 seconds
python ml/train_advanced.py --smoke

# Real data backtest — 5 years of GC=F (gold futures)
python real_data_backtest.py --symbol XAUUSD --years 5

# Multi-symbol backtest — 7 symbols, 10 years
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

### Via API

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Run a backtest
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "XAUUSD",
    "strategy": "ma_crossover",
    "years": 3,
    "initial_capital": 100000,
    "commission_bps": 35,
    "slippage_bps": 5
  }'

# List results
curl http://localhost:8000/api/backtest/results \
  -H "Authorization: Bearer $TOKEN"

# Get a specific result
curl http://localhost:8000/api/backtest/results/{run_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Via Python

```python
from backtesting.engine import BacktestEngine
from backtesting.data_sources import YFinanceDataSource
from strategies.ma_crossover import MovingAverageCrossover
from strategies.base import StrategyConfig

# Load data
data_source = YFinanceDataSource()
df = data_source.fetch("GC=F", period="5y", interval="1d")

# Configure strategy
config = StrategyConfig(
    name="ma_crossover",
    symbol="XAUUSD",
    parameters={"fast_period": 20, "slow_period": 50}
)

# Run backtest
engine = BacktestEngine(
    initial_capital=100_000,
    commission_bps=35,
    slippage_bps=5
)
result = engine.run(MovingAverageCrossover(config), df)

# Print metrics
print(result.summary())
```

---

## Available Strategies

| Strategy | Name | Type | Parameters |
|----------|------|------|------------|
| `ma_crossover` | Moving Average Crossover | Trend | `fast_period`, `slow_period` |
| `ema_crossover` | EMA Crossover | Trend | `fast_period`, `slow_period` |
| `rsi_strategy` | RSI | Momentum | `period`, `overbought`, `oversold` |
| `macd_strategy` | MACD | Momentum | `fast`, `slow`, `signal` |
| `bollinger_bands` | Bollinger Bands | Mean reversion | `period`, `std_dev` |
| `breakout` | Breakout | Trend | `lookback`, `atr_multiplier` |
| `mean_reversion` | Mean Reversion | Statistical | `period`, `z_threshold` |
| `stochastic` | Stochastic | Momentum | `k_period`, `d_period`, `smooth` |
| `smc_ict` | SMC/ICT | Institutional | `ob_lookback`, `fvg_min_size` |
| `strategy_brain` | Strategy Brain | AI consensus | `consensus_threshold` |

---

## Understanding Backtest Results

### Key Metrics

```json
{
  "total_return": 5.52,
  "annualised_return": 3.68,
  "win_rate": 57.8,
  "profit_factor": 2.28,
  "max_drawdown": -0.88,
  "sharpe_ratio": 1.52,
  "sharpe_se": 0.21,
  "sortino_ratio": 2.14,
  "calmar_ratio": 6.26,
  "total_trades": 48,
  "avg_hold_days": 9.2
}
```

**Total Return** — percentage gain over the backtest period.

**Win Rate** — percentage of trades that were profitable. Above 50% is good,
but profit factor matters more (a 40% win rate with 3:1 R/R is profitable).

**Profit Factor** — gross profit / gross loss. > 1.0 is profitable. > 2.0 is strong.

**Max Drawdown** — worst peak-to-trough loss. Keep below your risk tolerance.

**Sharpe Ratio** — annualised risk-adjusted return. > 1.0 is acceptable, > 2.0 is strong.
**Only meaningful when N ≥ 600 trades** (SE ≤ ±0.10).

**Sharpe SE** — standard error of the Sharpe estimate. With N=48 trades, SE ≈ ±0.21.
The true Sharpe could be anywhere from 1.31 to 1.73. Not statistically robust.

**Calmar Ratio** — annualised return / max drawdown. > 3.0 is strong.

---

## Walk-Forward Validation

Walk-forward validation prevents overfitting by testing on data the strategy
has never seen during optimisation.

```bash
# Run walk-forward validation
curl http://localhost:8000/api/backtest/walk-forward/latest \
  -H "Authorization: Bearer $TOKEN"
```

```python
from backtesting.engine import BacktestEngine

engine = BacktestEngine(initial_capital=100_000)
wf_result = engine.walk_forward(
    strategy_class=MovingAverageCrossover,
    data=df,
    n_folds=5,
    oos_fraction=0.3,
    parameter_grid={
        "fast_period": [10, 20, 50],
        "slow_period": [50, 100, 200]
    }
)
print(wf_result.summary())
```

The walk-forward result shows:
- Best parameters per fold (should be consistent across folds)
- OOS performance per fold (should be positive across all folds)
- Degradation ratio: OOS performance / in-sample performance (> 0.5 is acceptable)

---

## Monte Carlo Simulation

Monte Carlo simulation tests strategy robustness by randomly shuffling trade
order and measuring the distribution of outcomes.

```bash
# Run Monte Carlo on a backtest result
curl -X POST http://localhost:8000/api/backtest/{run_id}/monte-carlo \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"n_simulations": 10000, "confidence_level": 0.95}'

# Get results
curl http://localhost:8000/api/backtest/{run_id}/monte-carlo \
  -H "Authorization: Bearer $TOKEN"
```

Results include:
- 5th percentile max drawdown (worst-case scenario)
- 95th percentile total return (best-case scenario)
- Probability of ruin (drawdown > 20%)
- Median outcome

---

## Multi-Symbol Backtest

The multi-symbol backtest runs across 7 symbols simultaneously to accumulate
enough trades for statistically robust Sharpe estimates.

```bash
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

Symbols: XAU/USD, BTC/USD, ETH/USD, EUR/USD, GBP/USD, Silver, Oil

Results are pooled across symbols. N>919 trades satisfies the SE ≤ 0.10 gate.

Via API:
```bash
curl http://localhost:8000/api/backtest/multi-symbol \
  -H "Authorization: Bearer $TOKEN"
```

---

## Sharing Backtest Results

```bash
# Share a result (generates a public slug)
curl -X POST http://localhost:8000/api/backtest/{run_id}/share \
  -H "Authorization: Bearer $TOKEN"

# Response
{ "slug": "xauusd-ma-crossover-2026-07-14", "url": "/api/backtest/shared/xauusd-ma-crossover-2026-07-14" }

# Anyone can view it (no auth required)
curl http://localhost:8000/api/backtest/shared/xauusd-ma-crossover-2026-07-14
```

---

## Common Backtesting Pitfalls

### 1. In-sample testing (curve fitting)
**Problem:** Optimising parameters on the same data you test on.
**Fix:** Always use walk-forward validation. Never report in-sample results as performance.

### 2. Look-ahead bias
**Problem:** Using future data in feature calculation (e.g., `df.shift(-1)` in the wrong direction).
**Fix:** HOPEFX's `FeatureEngineer` uses `shift(1)` to ensure all features use only past data.
The raw train/test split happens before feature engineering.

### 3. Survivorship bias
**Problem:** Only testing on assets that still exist (winners).
**Fix:** Use GC=F (gold futures) which has continuous history. Avoid stock backtests without delisted stocks.

### 4. Too few trades
**Problem:** Reporting Sharpe on N=48 trades (SE ≈ ±0.21 — not meaningful).
**Fix:** Use OOS accuracy as the primary metric. Run multi-symbol backtest to accumulate N>600 trades.

### 5. Ignoring transaction costs
**Problem:** Backtest assumes zero spread, commission, and slippage.
**Fix:** Always set `commission_bps=35` and `slippage_bps=5` (or your broker's actual costs).

### 6. Overnight financing costs
**Problem:** Holding positions overnight incurs swap costs (especially for gold).
**Fix:** HOPEFX models overnight financing in `EnhancedBacktestEngine`. Enable with:
```bash
BACKTEST_MODEL_OVERNIGHT_FINANCING=true
OVERNIGHT_FINANCING_RATE_BPS=3  # 3 bps per night
```

### 7. Reporting bar-level Sharpe
**Problem:** Computing Sharpe from the daily equity curve inflates it by suppressing
return std with flat no-trade days.
**Fix:** Always use trade-level Sharpe: `trade_level_sharpe()` in `backtesting/metrics.py`.
The bar-level Sharpe of 4.68 was deprecated — the correct trade-level value is 1.52.

---

## Backtesting vs Live Trading

| Aspect | Backtest | Live |
|--------|----------|------|
| Data | Historical (yfinance) | Real-time (OANDA/IBKR) |
| Execution | Instant at close price | Market order with slippage |
| Spread | Modelled (5 bps) | Real broker spread |
| Commission | Modelled (35 bps) | Real broker commission |
| Slippage | Modelled (5 bps) | Real market impact |
| Overnight financing | Modelled (optional) | Real swap rates |
| Partial fills | Not modelled | Possible on large orders |

The gap between backtest and live performance is called "implementation shortfall".
Expect 10–30% degradation from backtest to live due to real-world frictions.

---

## Data Sources

HOPEFX uses yfinance for historical data:

```python
from backtesting.data_sources import YFinanceDataSource

ds = YFinanceDataSource()

# Gold futures (primary)
df = ds.fetch("GC=F", period="5y", interval="1d")

# Bitcoin
df = ds.fetch("BTC-USD", period="3y", interval="1h")

# EUR/USD
df = ds.fetch("EURUSD=X", period="5y", interval="1d")

# Silver
df = ds.fetch("SI=F", period="5y", interval="1d")
```

For live data, the `DataScheduler` fetches from OANDA (all 9 timeframes: M1→M).

---

## Backtesting Checklist

Before reporting any backtest result:
- [ ] Used walk-forward validation (not in-sample)
- [ ] OOS period is clearly stated (start date, end date, N bars)
- [ ] Transaction costs included (commission + slippage)
- [ ] N trades reported (and Sharpe SE if reporting Sharpe)
- [ ] No look-ahead bias (features use only past data)
- [ ] Results are OOS, not in-sample
- [ ] Compared to a simple benchmark (buy-and-hold)
