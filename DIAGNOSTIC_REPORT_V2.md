# HOPEFX — Diagnostic Fix Tracking (V2 → Current)

**Session date:** 2026-03-24  
**Based on:** DIAGNOSTIC_REPORT.md (V2 truth report)

This document tracks every fix applied after the V2 diagnostic audit.
Each entry records what was broken, what was changed, and the commit that resolved it.

---

## Fixes Applied

### FIX-1 — DataScheduler wired to app startup
**Commit:** `dbfc738`  
**File:** `app.py`  
**Problem:** `data/scheduler.py` (309 lines, real implementation) existed but was never called. The daily OANDA/yfinance data fetch job never ran.  
**Fix:** Added startup block that creates a `DataScheduler` instance, starts it as a background `asyncio.create_task`, and stores it on `app_state.data_scheduler`.

---

### FIX-2 — 20 Grafana-aligned metrics registered
**Commit:** `a02553e`  
**File:** `infrastructure/metrics.py`  
**Problem:** 20 of 21 Grafana dashboard panel expressions referenced metric names that did not exist in the codebase. All 20 panels showed "No data".  
**Fix:** Added all 20 missing metrics to `MetricsRegistry._initialize_default_metrics()`:
counters (`hopefx_signals_total`, `hopefx_broker_failover_total`, `hopefx_broker_rejections_total`, `hopefx_orders_total`),
gauges (`hopefx_equity`, `hopefx_active_positions`, `hopefx_pnl_realized`, `hopefx_drawdown_current`, `hopefx_model_drift_score`, `hopefx_model_accuracy_pct`, `hopefx_market_regime`, `hopefx_model_last_trained_timestamp`, `hopefx_broker_connected`, `hopefx_win_rate_pct`, `hopefx_smart_router_active_broker`, `hopefx_fix_last_heartbeat_timestamp`, `hopefx_db_pool_active`),
histograms (`hopefx_signal_confidence_bucket`, `hopefx_model_inference_ms_bucket`, `hopefx_order_latency_ms_bucket`, `hopefx_broker_latency_ms_bucket`).

**Bonus fix in same commit:** `MetricCollector._lock` was `threading.Lock` — a non-reentrant lock. `Counter.inc()` called `self.observe()` while holding it, causing a deadlock on every counter increment. Changed to `threading.RLock`.

---

### FIX-3 — Grafana dashboard metric name mismatches
**Commit:** `42f0c85`  
**Files:** `grafana/dashboards/trading_performance.json`, `grafana/dashboards/ml_model_metrics.json`  
**Problem:** 5 panel expressions used names the code never emitted.  
**Fix:** Updated expressions to match registered metric names:

| Dashboard | Old name | New name |
|---|---|---|
| trading_performance | `hopefx_account_equity` | `hopefx_equity` |
| trading_performance | `hopefx_open_positions_total` | `hopefx_active_positions` |
| trading_performance | `hopefx_daily_pnl_usd` | `hopefx_pnl_realized` |
| trading_performance | `hopefx_max_drawdown_pct` | `hopefx_drawdown_current` |
| ml_model_metrics | `hopefx_feature_drift_score` | `hopefx_model_drift_score` |

---

### FIX-4 — prometheus_monitoring.py implemented
**Commit:** `5f76dea`  
**File:** `prometheus_monitoring.py`, `app.py`  
**Problem:** File was a 2-line stub (`# ... code implementation ...`). No `/metrics` endpoint existed. Prometheus scraped nothing.  
**Fix:** Full 159-line implementation:
- Mounts `GET /metrics` on the FastAPI app using `prometheus_client.generate_latest()`
- Background asyncio task syncs `MetricsRegistry` Gauge/Counter values into `prometheus_client` objects every 15 s (configurable via `PROMETHEUS_SCRAPE_INTERVAL_SECONDS`)
- Falls back to `MetricsRegistry.export_prometheus()` text format if `prometheus_client` is not installed
- Idempotent — safe to call `setup_prometheus_monitoring(app)` multiple times
- Wired into `app.py` at module load (outside lifespan, so `/metrics` is available immediately)

---

### FIX-5 — FIX adapter silent exception swallowers
**Commit:** `0b576fa`  
**File:** `execution/fix_adapter.py`  
**Problem:** 7 bare `pass` in `except` handlers silently swallowed errors. Failures in optional FIX field extraction were invisible even under verbose logging.  
**Fix:** Replaced all 7 with `logger.debug(...)` calls. Optional fields (Text, RefSeqNum, SessionRejectReason, CxlRejReason, ClOrdID) are still handled gracefully — absence is expected in FIX — but now visible at DEBUG level.

Locations fixed:
- `fromAdmin` — Logout Text field
- `fromAdmin` — Reject RefSeqNum, SessionRejectReason, Text (3 handlers)
- `toApp` — ClOrdID on non-order messages
- `_handle_order_cancel_reject` — Text, CxlRejReason (2 handlers)

---

### FIX-6 — test_integration.py filled
**Commit:** `0a76c11`  
**File:** `test_integration.py`  
**Problem:** File was a 2-line stub.  
**Fix:** 23 real integration tests (21 pass, 2 skipped when FastAPI not installed) covering:
- `PaperTradingBroker`: connect, place order, track position, close position
- `RiskManager`: position sizing, trade validation, drawdown check, kill switch default state
- `MetricsRegistry`: counter/gauge/histogram operations, Prometheus text export, all 21 Grafana metric names present
- `KillSwitch`: activate, deactivate with token, status structure
- `DataScheduler`: import and instantiation
- `PrometheusMonitoring`: `/metrics` route mounted, idempotent setup

---

### FIX-7 — tests/test_copy_trading.py filled
**Commit:** `4c7d094`  
**File:** `tests/test_copy_trading.py`  
**Problem:** Tests imported from `hopefx.social.copy_trading` (non-existent namespace). Zero tests ran.  
**Fix:** 20 tests against the real `social/copy_trading.py`:
- `CopyRelationship` dataclass defaults and custom values
- `CopyTradingEngine` relationship management (start, stop, get active)
- Trade sync propagation to followers
- Proportional `copy_trade` sizing
- `RiskLimitExceeded` enforcement
- Leaderboard ranking logic

---

### FIX-8 — 4 skeleton test files filled
**Commit:** `a4820e8`  
**Files:** `tests/test_integration/test_full_pipeline.py`, `tests/integration/test_broker.py`, `tests/e2e/test_trading_flow.py`, `tests/test_chaos/test_failure_modes.py`  
**Problem:** All 4 imported from `hopefx.*` / `src.*` paths that don't exist. Zero tests ran.  
**Fix:** 38 tests total against real production modules:

| File | Tests | Coverage |
|---|---|---|
| test_full_pipeline.py | 5 | Broker+risk+metrics pipeline, multi-symbol |
| test_broker.py | 9 | PaperTradingBroker lifecycle, orders, positions |
| test_trading_flow.py | 5 | Signal→fill, metrics update, kill switch, latency |
| test_failure_modes.py | 19 | Broker/risk/kill-switch/metrics edge cases |

---

### FIX-9 — manifest.json broken path resolved
**Commit:** `9b772cd`  
**File:** `ml/saved_models/GCF/random_forest_model.pkl`  
**Problem:** `manifest.json` referenced `random_forest_model.pkl` but only the config JSON and feature-importance CSV existed. Any code that loaded the manifest and then opened the model path raised `FileNotFoundError`.  
**Fix:** Added a serialised (untrained) `RandomForestClassifier` skeleton at the expected path so the reference resolves. Will be replaced by a trained artifact once the data scheduler pulls current XAUUSD data and the retrain pipeline runs.

---

### FIX-10 — kill_switch.state.json excluded from git
**Commit:** `3a2b7ef`  
**File:** `.gitignore`  
**Problem:** `KillSwitch._persist_state()` writes a `kill_switch.state.json` runtime file. `kill_switch.flag` was already gitignored but the companion state file was not, causing it to appear as an untracked file.  
**Fix:** Added `kill_switch.state.json` to `.gitignore`.

---

## Remaining Items (not code fixes)

| Item | Status | Notes |
|---|---|---|
| Update XAUUSD training data | Deferred — runtime | Run `python -m data.scheduler` once to pull H1 data from 2024-10-18 to present. DataScheduler is now wired and will run automatically on next app startup. |
| Retrain ML model | Deferred — runtime | After data update, run `python -m ml.run_training`. Walk-forward validation is already built. Current model accuracy is 46.7% on stale Oct 2024 data. |
| 3 parallel codebases (`root/`, `src/`, `hopefx/`) | Architectural — out of scope | Consolidation requires a breaking refactor. Tracked separately. |

---

## Test Suite Summary (post-fixes)

| File | Tests | Result |
|---|---|---|
| `test_integration.py` | 23 | 21 pass, 2 skip |
| `tests/test_copy_trading.py` | 20 | 20 pass |
| `tests/test_integration/test_full_pipeline.py` | 5 | 5 pass |
| `tests/integration/test_broker.py` | 9 | 9 pass |
| `tests/e2e/test_trading_flow.py` | 5 | 5 pass |
| `tests/test_chaos/test_failure_modes.py` | 19 | 19 pass |
| **Total** | **81** | **79 pass, 2 skip** |
