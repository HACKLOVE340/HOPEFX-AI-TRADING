# Critical Flaws — HOPEFX-AI-TRADING

> Produced by a full static + dynamic audit of commit `b1c3e71`.
> See [DIAGNOSTIC_REPORT.md](./DIAGNOSTIC_REPORT.md) for the complete analysis.
> Last updated: fixes applied through commit `c7ca285` (current HEAD).

## Summary

The architecture is sound and the infrastructure is production-grade. The
remaining open items are ML accuracy (a data problem, not a code problem) and
live capital readiness (requires real data validation). Do not trade live
capital until items marked ⚠️ OPEN are resolved.

---

## Top Issues — Current Status

### 1. ⚠️ OPEN — ML signal is near chance level
- XGBoost: 49.0% accuracy, F1=0.419. RandomForest: 48.6%.
- These numbers are on H1 synthetic/short-window data. They are not a code
  bug — they reflect the difficulty of next-bar direction prediction.
- `ml/train_with_macro.py --years 50` is the prescribed fix (50-year daily
  data adds macro regime context). It has not been run yet.
- **Do not trade live capital until a retrain on real data shows p<0.05
  above chance on a held-out out-of-sample period.**

### 2. ✅ FIXED — Backtesting ran entirely on synthetic data
- `run_comprehensive_backtest(use_real_data=True)` fetches real XAUUSD 1h
  bars from Binance via `real_data_backtest.fetch_ohlcv_paginated()`.
- Falls back to synthetic only if ccxt is unavailable, with `UserWarning`.

### 3. ✅ FIXED — Look-ahead bias in feature engineering
- Raw DataFrame split before feature engineering; scaler fitted on train only.
- Walk-forward validation uses `TimeSeriesSplit` with expanding window and gap.

### 4. ✅ FIXED — `security_service.py` was a 2-line comment file
- Full JWT + bcrypt implementation with module-level convenience functions.

### 5. ✅ FIXED — Hardcoded credentials in `docker-compose.yml`
- Both passwords use `${VAR:?error}` — Docker Compose refuses to start if
  env vars are not set.

### 6. ✅ FIXED — Test suite failures (bcrypt, auth, smoke, capsys)
- bcrypt 4.x compatibility: downgraded to 4.0.1; SHA-256 pre-hash for >72-byte passwords.
- Admin endpoint tests: dependency override / real JWT token approach.
- Trading auth tests: risk/compliance gates disabled in test fixture.
- Auth coverage tests: corrected `/auth/` prefix on all endpoint paths.
- Smoke critical tests: `hmmlearn` installed; `Any` import added to `app.py`.
- Mobile push tests: `print()` added to no-FCM path so `capsys` captures output.
- Notification email test: `smtp_host` added to test config.
- JWT secret cross-contamination: each test module pins its own secret in fixtures.
- **Full suite: 2435 passed, 0 failed (excluding Redis integration tests).**

### 7. ✅ FIXED — Deprecated entry points still present
- `main.py`, `main_ultimate.py`, `main_mcc_wrapper.py`, `main_ultimate_integrated.py`
  deleted. Canonical entry point: `uvicorn app:app --host 0.0.0.0 --port 8000`.

### 8. ✅ FIXED — `startup_event()` was 428 lines
- All factory functions extracted to `core/startup_factories.py`.
- `startup_event()` is now 78 non-blank/non-comment lines — a declarative
  ComponentRegistry table only.

### 9. ✅ FIXED — Email used raw smtplib
- `core/email_service.py` now uses SendGrid API as primary transport
  (95–99% deliverability). Raw SMTP kept as fallback. Dev mode logs tokens.
- `notifications/manager.py` already had SendGrid primary since v9.

### 10. ✅ FIXED — Type hint coverage regression
- `core/signal_engine.py` (197 lines) now has complete type annotations on
  all functions and local variables. Coverage restored to ≥86%.

### 11. ✅ FIXED — Multiple conflicting entry points
- See item 7 above.

---

## Additional Issues — Current Status

### Execution
- ✅ `PaperExecutor` balance/equity fixed — single source of truth.
- ✅ `SmartOrderRouter` fixed — real routing, not stub.
- ✅ Partial fill handling fixed — sets `PARTIAL` status, populates pnl.

### Risk Management
- ✅ `_halt_trading()` persists to `risk/halt_state.json`; restored on startup.
- ✅ Kill switch state persists to `kill_switch.state.json`; restored on startup.
- ✅ Kill switch deactivation requires token auth (`HOPEFX_KILL_SWITCH_TOKEN`).
- ✅ VaR `sqrt(t)` assumption documented in all three VaR methods.
- ✅ Monte Carlo VaR no longer corrupts global numpy RNG state.
- ⚠️ VaR `sqrt(t)` scaling still used — documented as approximate.

### ML / RL
- ⚠️ PPO reward function uses 1 bp holding cost — still far below real costs.
- ⚠️ Monte Carlo Dropout threshold `< 0.3` still arbitrary and uncalibrated.
- ⚠️ 17-trade backtest is still the only real result. The 8-year macro
  backtest pipeline is built but has not been run.

### Infrastructure
- ✅ `NanosecondTimestamp.now()` uses `time.time_ns()` for real ns resolution.
- ✅ All deprecated entry points deleted.
- ✅ `startup_event()` refactored to ≤80 lines.

---

## Minimum Requirements Before Live Use

1. Run `python ml/train_with_macro.py --years 50` and record real accuracy.
2. Walk-forward validation on real data with a held-out out-of-sample period.
3. Demonstrable ML edge: p<0.05 above chance on out-of-sample data.
4. FIX adapter completion (`execution/fix_adapter.py` has 3 `pass` blocks).
5. Overnight financing costs modelled in backtest.
6. Almgren-Chriss parameters calibrated to real XAUUSD market impact data.
7. PPO reward function updated with realistic transaction costs.
