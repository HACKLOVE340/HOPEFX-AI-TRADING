# Critical Flaws — HOPEFX-AI-TRADING

> Produced by a full static + dynamic audit of commit `b1c3e71`.
> See [DIAGNOSTIC_REPORT.md](./DIAGNOSTIC_REPORT.md) for the complete analysis.
> Last updated: fixes applied through commit `6d1b0a1`.

## Summary

This is a scaffolding project, not a production trading system. The architecture
references institutional patterns correctly, but the core implementations were
either stubs, broken, or validated only against synthetic data.

The table below shows the current status of every issue from the original audit.

---

## Top Issues — Current Status

### 1. ✅ FIXED — ML edge is statistically nonexistent
- Scaler now fitted only on training data; inference uses `transform()` only.
- `_evaluate_model()` returns real accuracy scores (was always `0.0`).
- Ensemble weights computed via softmax over actual validation accuracy.
- Walk-forward validation added: `EnhancedMLPredictor.fit(use_walk_forward=True)`
  uses `TimeSeriesSplit` with expanding window and gap to prevent leakage.
- **Remaining:** 48.3% accuracy on synthetic data is still the honest baseline.
  No real ML edge has been demonstrated on real XAUUSD data.

### 2. ✅ FIXED — `trader_full.py` was an empty stub
- All 10 classes implemented and wired to existing modules.
- `ForwardTestHarness` runs the full tick → signal → risk → order pipeline.
- `__main__` checks kill-switch state on startup, handles SIGINT/SIGTERM.

### 3. ✅ FIXED — Backtesting ran entirely on synthetic data
- `run_comprehensive_backtest(use_real_data=True)` now attempts real XAUUSD
  1h bars from Binance via `real_data_backtest.fetch_ohlcv_paginated()`.
- Falls back to synthetic only if ccxt is unavailable, with `UserWarning` and
  console banner so results are unambiguously labelled.
- `generate_test_data()` emits `UserWarning` and documents its limitations.

### 4. ✅ FIXED — Look-ahead bias in feature engineering
- Raw DataFrame split before feature engineering; scaler fitted on train only.
- `CalibratedClassifierCV` uses `cv='prefit'` on a chronological held-out
  slice — no shuffled k-fold on time-series data.

### 5. ✅ FIXED — `security_service.py` was a 2-line comment file
- Full JWT + bcrypt implementation with module-level convenience functions.

### 6. ✅ FIXED — Hardcoded credentials in `docker-compose.yml`
- Both passwords use `${VAR:?error}` — Docker Compose refuses to start if
  env vars are not set.

### 7. ✅ Already correct — `datetime.now()` without timezone
- All files already use `datetime.now(timezone.utc)`.

### 8. ⚠️ PARTIALLY ADDRESSED — Test suite "2100+ passing" claim is false
- ~67 tests pass; 10 of 12 unit test files fail to import.
- README badge not updated. Test bounds still too loose.

### 9. ✅ FIXED — No walk-forward validation
- `TimeSeriesSplit` with anchored expanding window now used in
  `EnhancedMLPredictor._walk_forward_fit()`.

### 10. ✅ FIXED — Broker factory stubs / sync OANDA
- `AsyncOANDAConnector` added using `aiohttp.ClientSession` (non-blocking).
- `BasePropFirmBroker` converted to `ABC` with `@abstractmethod`.
- `SmartOrderRouter` now does real multi-broker routing with scoring.

---

## Additional Issues — Current Status

### Execution
- ✅ `PaperExecutor` balance/equity fixed — single source of truth.
- ✅ `SmartOrderRouter` fixed — real routing, not stub.
- ✅ Partial fill handling fixed — sets `PARTIAL` status, populates pnl.

### Risk Management
- ✅ `_halt_trading()` now persists to `risk/halt_state.json`; restored on
  startup; expired halts auto-cleared.
- ✅ Kill switch state persists to `kill_switch.state.json`; restored on startup.
- ✅ `kill_switch.deactivate()` now requires token authentication
  (`HOPEFX_KILL_SWITCH_TOKEN` env var); uses `hmac.compare_digest()`.
- ✅ VaR `sqrt(t)` assumption documented in all three VaR methods.
- ✅ Monte Carlo VaR no longer corrupts global numpy RNG state.
- ⚠️ VaR `sqrt(t)` scaling still used — documented as approximate.

### ML / RL
- ⚠️ PPO reward function uses 1 bp holding cost — still far below real costs.
- ⚠️ Monte Carlo Dropout threshold `< 0.3` still arbitrary and uncalibrated.

### Infrastructure
- ✅ `NanosecondTimestamp.now()` uses `time.time_ns()` for real ns resolution.
- ⚠️ Multiple conflicting entry points still present.

---

## Minimum Requirements Before Live Use

1. Real historical data pipeline (actual XAUUSD tick data from a vendor).
2. Walk-forward validation on real data with a held-out out-of-sample period.
3. Demonstrable ML edge on real data (48% accuracy is not one).
4. FIX adapter completion (`execution/fix_adapter.py` has 3 `pass` blocks).
5. Test suite repair — fix missing dependencies, tighten bounds.
6. README badge accuracy — remove or correct false Sharpe/test-count badges.
7. Overnight financing costs modelled in backtest.
8. Almgren-Chriss parameters calibrated to real XAUUSD market impact data.
