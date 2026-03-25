# Critical Flaws — HOPEFX-AI-TRADING

> Produced by a full static + dynamic audit of commit `b1c3e71`.
> See [DIAGNOSTIC_REPORT.md](./DIAGNOSTIC_REPORT.md) for the complete analysis.
> Last updated: fixes applied through commit `968f6bd` (current HEAD).

## Summary

The architecture is sound and the infrastructure is production-grade. All
previously open items have been addressed. The remaining constraint before
live capital deployment is demonstrating p<0.05 ML edge on a held-out OOS
period — current models are near chance level (50.3–50.7% accuracy).

---

## Top Issues — Current Status

### 1. ⚠️ OPEN — ML signal is near chance level on held-out OOS data
- 50-year macro walk-forward (5,609 bars, GC=F + DXY/VIX/yields/SPX):
  - XGBoost: WF acc=50.3% ± 1.8%, p=0.720 (not significant)
  - RandomForest: WF acc=50.7% ± 2.6%, p=0.612 (not significant)
- 3-year held-out OOS (2023-03-22 → 2026-03-24, n=756 bars, never seen in training):
  - XGBoost: acc=50.5%, F1=0.421, p=0.400 (not significant)
  - RandomForest: acc=48.4%, F1=0.323, p=0.818 (not significant)
- These are real results on real GC=F data. Neither model shows p<0.05 edge.
- **Do not trade live capital until p<0.05 is demonstrated on a held-out OOS period.**
- Reproduce: `python ml/train_with_macro.py --years 50 --oos-years 3`

### 2. ✅ FIXED — Backtesting ran entirely on synthetic data
- `generate_proof_artifacts.py` now fetches 5 years of real GC=F daily bars
  from Yahoo Finance. Falls back to synthetic GBM only if yfinance fails,
  with a clear `UserWarning` and label in the plot title and performance.json.
- Real backtest (2024-10-14 → 2026-03-24, 31 trades): return=+6.17%,
  win rate=67.7%, profit factor=3.553, max DD=−0.83%, ML acc=52.9%.
- `examples/results/equity_curve.png` and `performance.json` updated.

### 3. ✅ FIXED — Look-ahead bias in feature engineering
- Raw DataFrame split before feature engineering; scaler fitted on train only.
- Walk-forward validation uses `TimeSeriesSplit` with expanding window and gap.

### 4. ✅ FIXED — `security_service.py` was a 2-line comment file
- Full JWT + bcrypt implementation with module-level convenience functions.

### 5. ✅ FIXED — Hardcoded credentials in `docker-compose.yml`
- Both passwords use `${VAR:?error}` — Docker Compose refuses to start if
  env vars are not set.

### 6. ✅ FIXED — Test suite failures (bcrypt, auth, smoke, capsys)
- Full suite: 2435 passed, 0 failed (excluding Redis integration tests).

### 7. ✅ FIXED — Deprecated entry points still present
- `main.py`, `main_ultimate.py`, `main_mcc_wrapper.py`, `main_ultimate_integrated.py`
  deleted. Canonical entry point: `uvicorn app:app --host 0.0.0.0 --port 8000`.

### 8. ✅ FIXED — `startup_event()` was 428 lines
- All factory functions extracted to `core/startup_factories.py`.
- `startup_event()` is now 78 non-blank/non-comment lines.

### 9. ✅ FIXED — Email used raw smtplib
- `core/email_service.py` uses SendGrid API as primary transport. SMTP fallback.

### 10. ✅ FIXED — Type hint coverage regression
- `core/signal_engine.py` has complete type annotations. Coverage ≥86%.

---

## Additional Issues — Current Status

### Execution
- ✅ `PaperExecutor` balance/equity fixed — single source of truth.
- ✅ `SmartOrderRouter` fixed — real routing, not stub.
- ✅ Partial fill handling fixed — sets `PARTIAL` status, populates pnl.
- ✅ FIX adapter completed — `_start_pyfixmsg()`, `_send_pyfixmsg()`, and
  `_reject_pending()` all implemented. `_dispatch_exec_report()` now raises
  `RuntimeError` on REJECTED fills instead of silently resolving the future.
  Module imports cleanly without quickfix/pyfixmsg installed (simulation mode).

### Risk Management
- ✅ `_halt_trading()` persists to `risk/halt_state.json`; restored on startup.
- ✅ Kill switch state persists to `kill_switch.state.json`; restored on startup.
- ✅ Kill switch deactivation requires token auth (`HOPEFX_KILL_SWITCH_TOKEN`).
- ✅ VaR `sqrt(t)` scaling: all three VaR methods now set `scaling_approximate=True`
  and emit `RuntimeWarning` when the normality/i.i.d. assumption is used.
  `VaRResult` gains `scaling_approximate` and `scaling_note` fields.
  `calculate_var_monte_carlo()` gains `use_historical_bootstrap=True` mode
  which resamples 1-day returns without assuming normality.
  `calculate_var_parametric()` runs Jarque-Bera and warns when normality is rejected.
- ✅ Monte Carlo VaR no longer corrupts global numpy RNG state.

### ML / RL
- ✅ PPO reward function updated with realistic transaction costs:
  - `slippage_bps=0.0005` (5 bps per trade, market-order fill on H1)
  - `commission=0.0035` (35 bps round-trip: spread ~20 bps + broker ~15 bps)
  - `overnight_cost_daily=0.0002` (2 bps/day ≈ 7.3% p.a., XAUUSD swap)
  - Reward clipped to `[-10, +10]` before scaling to prevent gradient explosions.
  - `info` dict now includes `delta_pnl` and `raw_reward` for diagnostics.
- ✅ Monte Carlo Dropout / ensemble confidence thresholds calibrated:
  - `RobustPredictor.calibrate_thresholds(oos_probs, oos_outcomes)` derives
    data-driven confidence boundaries from held-out OOS predictions.
  - `PredictionResult.thresholds_calibrated=False` flags uncalibrated signals.
  - Default thresholds (0.3/0.4/0.6/0.7) unchanged until calibration is called.
- ✅ 50-year macro backtest pipeline run and results recorded (see item 1).
- ✅ Walk-forward validation with strict held-out OOS period implemented
  (`--oos-years` flag). One-sided binomial p-value test (H0: acc ≤ 0.5).

### Backtest Engine
- ✅ Overnight financing costs modelled in `EnhancedBacktestEngine`:
  - `TransactionCostModel` gains `overnight_rate_long_annual=0.004` (0.40% p.a.)
    and `overnight_rate_short_annual=-0.002` (−0.20% p.a.) for XAUUSD.
  - `process_tick()` charges financing every bar on open position notional.
  - `Position.total_financing_paid` accumulates running financing cost.
  - `get_performance_report()` includes `total_financing_paid` and `financing_drag_pct`.
- ✅ Almgren-Chriss parameters calibrated to XAUUSD market impact data:
  - `eta=0.050` (was 0.142), `gamma=0.100` (was 0.314), `beta=0.55` (was 0.60).
  - Sources: Almgren & Chriss (2001), Kissell & Glantz (2003),
    Frazzini/Israel/Moskowitz (2018), WFE/LBMA Gold Market Structure (2019).
  - `TransactionCostModel.calibrate_xauusd()` classmethod for pre-configured model.
  - `calibrate_from_executions()` fits η/γ/β to observed fill data via OLS.

### Infrastructure
- ✅ `NanosecondTimestamp.now()` uses `time.time_ns()` for real ns resolution.
- ✅ All deprecated entry points deleted.
- ✅ `startup_event()` refactored to ≤80 lines.
- ✅ `docs/WORLD_MONITOR_INTEGRATION.json` wiring corrected:
  - `registered_in` was `app.py startup` — corrected to `core/startup_factories.py`.
  - Line counts and class lists verified against actual source files.
  - `wiring_audit` section added for future re-audits.

---

## Minimum Requirements Before Live Use

| # | Requirement | Status |
|---|---|---|
| 1 | Run `ml/train_with_macro.py --years 50` and record real accuracy | ✅ Done — acc=50.3–50.7%, p>0.05 |
| 2 | Walk-forward validation with held-out OOS period | ✅ Done — `--oos-years 3` flag |
| 3 | Demonstrable ML edge: p<0.05 above chance on OOS data | ⚠️ **NOT MET** — p=0.40–0.82 |
| 4 | FIX adapter completion | ✅ Done — all 3 stubs implemented |
| 5 | Overnight financing costs modelled in backtest | ✅ Done |
| 6 | Almgren-Chriss parameters calibrated to real XAUUSD data | ✅ Done |
| 7 | PPO reward function with realistic transaction costs | ✅ Done |

**The only remaining blocker for live capital is item 3: p<0.05 ML edge on OOS data.**
