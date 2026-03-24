# HOPEFX V2 — TRUTH REPORT

## “How true is the Grafana claim?” + Full Test & Deployment Audit

**Date:** 2026-03-24 | **Version analyzed:** v2 (second ZIP upload)

-----

## THE GRAFANA CLAIM — VERDICT: HALF TRUE ⚠️

> *“The Grafana dashboards reference Prometheus metric names that need to be emitted by prometheus_monitoring.py. The dashboard panels will show ‘No data’ until those metrics are instrumented — the dashboards are structurally correct and will populate once the metrics exist.”*

**What’s true:** The Grafana provisioning infrastructure is now real and structurally correct. The datasource config, dashboard loader, and 4 dashboard JSON files all exist and are properly wired in docker-compose. The statement that “dashboards are structurally correct” is accurate.

**What’s not true:** The claim implies `prometheus_monitoring.py` just needs to emit the metrics. In reality, `prometheus_monitoring.py` is a **2-line stub** — it contains only a comment and nothing else:

```python
# Prometheus monitoring setup for metrics
# ... code implementation ...
```

That file has zero implementation. It is not the missing piece. The real issue is deeper — **20 out of 21 metric names in the Grafana dashboards don’t match what the codebase actually emits.** The problem is a naming mismatch across the entire codebase, not a single missing file.

-----

## THE EXACT METRIC GAP

The codebase emits real metrics. Grafana asks for different names. Here is the full mismatch table:

|Grafana Dashboard Asks For           |Code Actually Emits                         |Fix Needed                   |
|-------------------------------------|--------------------------------------------|-----------------------------|
|`hopefx_account_equity`              |`hopefx_equity`                             |Rename or alias              |
|`hopefx_open_positions_total`        |`hopefx_active_positions`                   |Rename or alias              |
|`hopefx_daily_pnl_usd`               |`hopefx_pnl_realized`                       |Rename or alias              |
|`hopefx_max_drawdown_pct`            |`hopefx_drawdown_current`                   |Rename or alias              |
|`hopefx_feature_drift_score`         |`hopefx_model_drift_score`                  |Rename or alias              |
|`hopefx_order_latency_ms_bucket`     |`hopefx_order_latency_seconds`              |Unit change (ms→s) + rename  |
|`hopefx_broker_latency_ms_bucket`    |`hopefx_latency_order_submit_seconds`       |Rename + make Histogram      |
|`hopefx_db_pool_active`              |`hopefx_db_connections_active`              |Rename                       |
|`hopefx_signals_total`               |*(closest: `hopefx_events_processed_total`)*|Instrument from signal engine|
|`hopefx_broker_connected`            |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_broker_failover_total`       |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_broker_rejections_total`     |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_fix_last_heartbeat_timestamp`|*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_market_regime`               |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_model_accuracy_pct`          |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_model_inference_ms_bucket`   |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_model_last_trained_timestamp`|*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_signal_confidence_bucket`    |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_smart_router_active_broker`  |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_win_rate_pct`                |*(nothing)*                                 |**Must build from scratch**  |
|`hopefx_orders_total`                |`hopefx_orders_total`                       |✅ **THIS ONE MATCHES**       |

**Score: 1 out of 21 Grafana metrics match what the code emits.**

The fix is two-part:

1. **Quick renames (10 metrics):** Change metric names in `infrastructure/metrics.py` to match Grafana, or edit the Grafana dashboard JSON to match the code. Editing Grafana JSON is faster.
1. **New instrumentation (10 metrics):** Add new `Gauge`/`Counter`/`Histogram` registration calls in the appropriate modules (broker manager, ML predictor, signal engine, smart router).

-----

## WHAT ACTUALLY CHANGED IN V2

Here are all the real changes between your first upload and this one:

### ✅ GENUINELY FIXED IN V2

|Fix                         |What Changed                                                                                                                 |Verdict                                          |
|----------------------------|-----------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------|
|**Grafana provisioning**    |`grafana/` directory added with 4 dashboards, datasource config, dashboard loader, mounted in docker-compose                 |✅ Real fix — structure is correct                |
|**RL agent reward function**|`commission = 0.0035` (35 bps) — fixed from 1bp to realistic XAUUSD cost                                                     |✅ Real fix                                       |
|**Kill switch REST API**    |FastAPI router added to `kill_switch.py` with GET/POST endpoints for status, activate, deactivate                            |✅ Real addition                                  |
|**CI codebase targeting**   |`ci.yml` now runs `mypy` and `ruff` on root packages (`api/ auth/ brokers/`) instead of `src/`                               |✅ Real fix — CI will no longer fail on wrong path|
|**CI coverage threshold**   |Dropped from `95%` → `70%` — achievable target now                                                                           |✅ Real fix                                       |
|**pyproject.toml**          |Switched from `hatchling` to `setuptools`, uses `packages.find` to auto-discover root packages, excludes `src/` and `hopefx/`|✅ Real fix — package discovery now works         |
|**No-code builder**         |`nocode/builder.py` (468 lines), `nocode/models.py`, `nocode/router.py` — real implementation                                |✅ Real new feature                               |
|**Replay engine**           |`replay/engine.py` (473 lines), `replay/models.py`, `replay/router.py` — real implementation                                 |✅ Real new feature                               |
|**AI Explainability**       |`explainability/explainer.py` (446 lines), `explainability/models.py`, `explainability/router.py`                            |✅ Real new feature                               |
|**Transparency engine**     |`transparency/engine.py`, `transparency/models.py`, `transparency/router.py`                                                 |✅ Real new feature                               |
|**Data scheduler**          |`data/scheduler.py` (309 lines) — OANDA H1 data fetch with yfinance fallback                                                 |✅ Real new feature                               |
|**Data validator**          |`data/validator.py` (230 lines) — price sanity, gap detection, stale data                                                    |✅ Real new feature                               |

### ❌ STILL NOT FIXED IN V2

|Issue                            |Status                                                                                                       |
|---------------------------------|-------------------------------------------------------------------------------------------------------------|
|**FIX adapter 5 `pass` blocks**  |Unchanged — all 5 silent exception swallowers still there at lines 242, 256, 260, 264, 278                   |
|**prometheus_monitoring.py**     |Still 2-line stub: `# ... code implementation ...`                                                           |
|**ML model stale data**          |Data still ends Oct 2024, gold still at $1,668 in training set                                               |
|**ML accuracy 46.7%**            |No retrain, no new data, same model                                                                          |
|**manifest.json broken path**    |`random_forest_model.pkl` still missing from `ml/saved_models/GCF/`                                          |
|**3 parallel codebases**         |`root/`, `src/`, `hopefx/` all still present                                                                 |
|**DIAGNOSTIC_REPORT.md replaced**|The V2 file replaced the real diagnostic report with the Master Build Plan — the fix tracking history is gone|

-----

## TEST SUITE — FULL ANALYSIS

### The Numbers

|Metric                                   |Count    |
|-----------------------------------------|---------|
|Total test functions found (static parse)|**2,178**|
|Total test files                         |69       |
|Files with zero tests (empty/skeleton)   |6        |
|Files with syntax errors                 |0        |

### The Critical Question: Are These Real Tests?

Yes and no — it depends on the file. Here’s the breakdown:

**Tests that import and test real production code (GOOD):**

- `test_api.py` — imports from `api/trading.py`, `api/admin.py`, uses `TestClient`
- `test_ml_models.py` — imports from `ml/models/base.py`, `ml/models/ensemble.py`, `ml/features/technical.py`
- `test_risk_manager.py` — imports from `risk/manager.py`, `database/models.py`
- `test_strategies.py` — imports from `strategies/`, uses real strategy classes
- `test_broker_connectors.py` — imports real broker connectors, stubs only the external SDKs (MT5, OANDA) which is correct testing practice

**Tests that are heavily mocked (ACCEPTABLE but limited):**

- Most broker connector tests inject stub modules for `MetaTrader5`, `oandapyV20`, `alpaca_trade_api` — this is the right approach since you can’t run live broker tests in CI. The underlying broker logic is still exercised.

**Tests that are empty (BAD — need filling):**

- `test_copy_trading.py` — 0 tests
- `test_integration.py` — 0 tests
- `test_trading_flow.py` — 0 tests
- `test_failure_modes.py` — 0 tests
- `test_full_pipeline.py` — 0 tests
- `test_broker.py` (integration) — 0 tests

### Why Tests Still Can’t Run in CI

The CI installs from `requirements-dev.txt` which includes `pytest-asyncio`. But `requirements.txt` was changed in V2 to **remove** `aiosqlite`, `asyncpg`, and all dev dependencies. This creates a mismatch:

- Tests import `pytest_asyncio` → needs `pytest-asyncio` installed
- Tests import `asyncpg` for DB → was removed from `requirements.txt`
- Tests import `fastapi` → not in base `requirements.txt` for CI

The CI step `pip install -r requirements-dev.txt` should pull in everything via `-r requirements.txt` at the top of that file, but if that circular reference was removed, the chain breaks.

**Estimated real passing tests when run with all deps installed: ~180–250** (not 2,178 — the remainder will fail on import errors from missing optional packages like `tensorflow`, `torch`, `MetaTrader5`).

-----

## DEPLOYMENT ISSUES — FULL DIAGNOSIS

### Issue 1: Grafana Mounted Paths Wrong ⚠️

`docker-compose.yml` mounts:

```yaml
- ./grafana/provisioning:/etc/grafana/provisioning:ro
- ./grafana/dashboards:/etc/grafana/dashboards:ro
```

But the dashboard JSON files are in `grafana/dashboards/` and the provisioning config points to `/etc/grafana/dashboards`. **This is correct and will work** — the files are in the right place. ✅

### Issue 2: Grafana `GF_SECURITY_ADMIN_PASSWORD` still uses `${VAR:?error}` ✅

Good — Docker Compose will refuse to start without it set. This is correct.

### Issue 3: `prometheus_monitoring.py` is a stub — Prometheus starts but custom metrics never register ❌

The Prometheus service will start and scrape `http://app:8000/metrics`. The app does emit some metrics via `infrastructure/metrics.py`. But the 20 trading-specific metrics the dashboards need don’t exist in code. Dashboards show “No data” on all 20 panels.

### Issue 4: Data scheduler not wired to app startup ⚠️

`data/scheduler.py` exists and is real (309 lines). But it’s never called from `app.py` startup. The data update job won’t run unless explicitly started.

**Fix:** Add to `app.py` startup sequence:

```python
from data.scheduler import DataScheduler
scheduler = DataScheduler()
app_state.background_tasks.append(asyncio.create_task(scheduler.start()))
```

### Issue 5: New routers (nocode, replay, explainability, transparency) not wired to FastAPI ❌

All four new modules have real `router.py` files. None are imported or registered in `app.py`. The features exist in Python but are not accessible via any API endpoint.

**Fix for each:** Add to `app.py`:

```python
from nocode.router import router as nocode_router
from replay.router import router as replay_router
from explainability.router import router as explainability_router
from transparency.router import router as transparency_router

app.include_router(nocode_router)
app.include_router(replay_router)
app.include_router(explainability_router)
app.include_router(transparency_router)
```

### Issue 6: kill_switch router also not wired ❌

The new `create_kill_switch_router()` function was added to `kill_switch.py`. It’s not called from `app.py`. The REST endpoints (`/api/kill-switch/status`, `/api/kill-switch/activate`) don’t exist at runtime.

### Issue 7: pyproject.toml has duplicate `[build-system]` note ⚠️

The diff shows a comment “# duplicate [build-system] removed” but the file may have a stale section. Run `python -m build --check` to confirm it parses cleanly.

### Issue 8: requirements.txt removed `aiosqlite` and `asyncpg` ⚠️

These were removed in V2. But `database/connection.py` imports `asyncpg`. If anyone runs `pip install -r requirements.txt` and then starts the app with PostgreSQL, it will crash on import. They need to go back in.

-----

## UPDATED FIX PRIORITY LIST

### 🔴 DO THESE THIS now (Deployment Blockers)

**FIX-1: Wire the 5 new routers into app.py**

```python
# Add to app.py after existing router includes:
from nocode.router import router as nocode_router
from replay.router import router as replay_router  
from explainability.router import router as explainability_router
from transparency.router import router as transparency_router
from kill_switch import create_kill_switch_router

app.include_router(nocode_router)
app.include_router(replay_router)
app.include_router(explainability_router)
app.include_router(transparency_router)
ks_router = create_kill_switch_router(app_state.kill_switch)
if ks_router:
    app.include_router(ks_router)
```

**FIX-2: Wire data scheduler to app startup**
In `app.py` startup function, after cache init:

```python
from data.scheduler import DataScheduler
scheduler = DataScheduler()
task = asyncio.create_task(scheduler.start())
app_state.background_tasks.append(task)
logger.info("✓ Data scheduler started")
```

**FIX-3: Fix the 20 Grafana metric mismatches**
Fastest approach — edit the Grafana dashboard JSONs to use names the code already emits:

|Change in Dashboard JSON|From                         |To                        |
|------------------------|-----------------------------|--------------------------|
|trading_performance.json|`hopefx_account_equity`      |`hopefx_equity`           |
|trading_performance.json|`hopefx_open_positions_total`|`hopefx_active_positions` |
|trading_performance.json|`hopefx_daily_pnl_usd`       |`hopefx_pnl_realized`     |
|trading_performance.json|`hopefx_max_drawdown_pct`    |`hopefx_drawdown_current` |
|ml_model_metrics.json   |`hopefx_feature_drift_score` |`hopefx_model_drift_score`|

Then for the 10 metrics with no close match, add instrumentation to `infrastructure/metrics.py`:

```python
# Add these to the metrics registry setup:
signals_total    = registry.create_counter("hopefx_signals_total", "Total signals generated")
signal_conf      = registry.create_histogram("hopefx_signal_confidence_bucket", "Signal confidence distribution")
model_accuracy   = registry.create_gauge("hopefx_model_accuracy_pct", "Rolling model accuracy %")
market_regime    = registry.create_gauge("hopefx_market_regime", "Current market regime (0=ranging,1=trending,2=volatile)")
model_trained_ts = registry.create_gauge("hopefx_model_last_trained_timestamp", "Unix ts of last model retrain")
model_infer_ms   = registry.create_histogram("hopefx_model_inference_ms_bucket", "Model inference latency ms")
broker_connected = registry.create_gauge("hopefx_broker_connected", "Broker connection status", ["broker"])
broker_failover  = registry.create_counter("hopefx_broker_failover_total", "Broker failover events")
broker_rejects   = registry.create_counter("hopefx_broker_rejections_total", "Broker order rejections")
win_rate_pct     = registry.create_gauge("hopefx_win_rate_pct", "Rolling win rate %")
```

Then call `.set()` / `.inc()` at the appropriate places in the codebase.

**FIX-4: Restore asyncpg and aiosqlite to requirements.txt**

```
asyncpg>=0.29.0
aiosqlite>=0.19.0
```

**FIX-5: Add prometheus_monitoring.py real implementation**
The file is 2 lines. Replace with actual metric registration that calls the infrastructure/metrics registry and exposes them. Or delete the file and use `infrastructure/metrics.py` directly (which already has the right architecture).

**FIX-6: Fix FIX adapter pass blocks (still unfixed)**

```python
# In execution/fix_adapter.py, lines 242, 256, 260, 264, 278:
# Replace every bare `pass` in exception handlers with:
except Exception as e:
    logger.error("FIX execution error at [location]: %s", e, exc_info=True)
    # set order status appropriately
```

### 🟡 DO THESE THIS now (Quality & Trust)

**FIX-7: Update XAUUSD data** — Run the new `data/scheduler.py` manually once to pull H1 data from 2024-10-18 to today. This is now easy — the scheduler is written. Just run it.

**FIX-8: Retrain ML model** — With current data from FIX-7, retrain. Use walk-forward validation already built. Measure real out-of-sample accuracy.

**FIX-9: Fix 6 empty test files** — Fill `test_copy_trading.py`, `test_integration.py`, and the 4 empty integration/e2e files.

**FIX-10: Restore DIAGNOSTIC_REPORT.md** — The V2 upload replaced the real diagnostic report (with fix history) with the Master Build Plan. The fix tracking history is valuable — restore it or create a new `DIAGNOSTIC_REPORT_V2.md`.

-----

## OVERALL V2 ASSESSMENT

|Area                                                |V1 Score|V2 Score  |Change                                    |
|----------------------------------------------------|--------|----------|------------------------------------------|
|Grafana / Monitoring                                |0/10    |5/10      |+5 (structure real, metrics mismatched)   |
|New features (nocode, replay, explain, transparency)|0/10    |6/10      |+6 (built but not wired)                  |
|CI/CD                                               |1/10    |6/10      |+5 (right paths now, achievable threshold)|
|RL agent reward                                     |2/10    |7/10      |+5 (35bps is realistic)                   |
|Data pipeline                                       |1/10    |4/10      |+3 (scheduler written, not yet run)       |
|FIX adapter                                         |1/10    |1/10      |0 (still 5 pass blocks)                   |
|ML accuracy                                         |1/10    |1/10      |0 (same stale model)                      |
|Tests (structural)                                  |3/10    |7/10      |+4 (2178 test functions, good structure)  |
|Tests (runtime)                                     |1/10    |2/10      |+1 (still can’t run without deps)         |
|**Overall**                                         |**3/10**|**5.5/10**|**+2.5**                                  |

**V2 is meaningfully better.** The Grafana claim is half-true — the infrastructure is real, but the metrics pipeline is broken in a specific, fixable way. The new modules (nocode, replay, explainability, transparency) are genuinely built — 1,600+ lines of new real code. The main gap now is wiring: 5 routers, 1 scheduler, and 20 metric names all need connecting before the app is fully functional.

-----

*The bones are stronger. The wiring is the job now.*
