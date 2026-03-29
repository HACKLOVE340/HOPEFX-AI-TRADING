# BRUTALLY HONEST HOPEFX DIAGNOSTIC REPORT

> Audited: 2026-03-29 | Commit: 48c1e57 | Auditor: Ona (principal engineer)
> All findings validated by running commands against the live repo.

---

## Executive Summary — Live Trading Readiness

**NOT ready for live money. Paper trading is safe to continue.**

The architecture is sound and the ML model is statistically credible (OOS
accuracy 66.35%, Sharpe 1.52, p=0.0). The infrastructure wiring (FastAPI,
Redis event bus, FIX router, gatekeeper, kill switch) is production-grade in
design. However, six concrete blockers prevent live deployment:

1. **Kill switch is permanently active** — `kill_switch.flag` on disk from a
   prior 12% drawdown event. Every app start logs `CRITICAL: Kill switch
   restored`. Health endpoint returns `"kill_switch": "active"` and
   `"status": "degraded"`. No trading can execute until this is cleared.

2. **ML model is unpicklable** — `advanced_oos.pkl` raises
   `_pickle.UnpicklingError: STACK_GLOBAL requires str` on Python 3.12.
   The model was serialised on a different Python version. The live inference
   engine will silently fall back to EMA crossover — you are not running the
   XGBoost model in production.

3. **Paper trading fills are synthetic** — `data/paper_trading_gate.json`
   shows 10 fills all with `pnl=1.0`. These are test fixtures, not real
   paper-trade results. There is no evidence of a live OANDA paper session
   producing real tick-driven fills.

4. **4 integration tests fail** — `/health` returns `degraded` (not
   `healthy`), and three admin endpoints return 404 because the test URLs
   use a double-prefix (`/api/admin/api/...`) that does not exist in the
   router.

5. **10 undefined-name (F821) lint errors** — runtime NameErrors waiting to
   happen in `api/advanced_trading.py`, `api/backtesting.py`, `api/ml.py`,
   `ml/online_learner.py`, `core/startup_factories.py`,
   `utils/fault_guard.py`.

6. **`deployment_guide.py` is a 25-line stub** — it prompts for DB host and
   API key via `input()` and prints them. It does nothing else. Any operator
   who runs it expecting a deployment wizard gets nothing.

---

## Findings — Prioritised

### P1 — CRITICAL (blocks live trading)

#### P1.1 Stale kill switch flag on disk
- **File**: `kill_switch.flag`
- **Content**: `activated_at=2026-03-29T03:34:05 reason=[risk_manager] Max drawdown reached: 12.00% > 10.00%`
- **Impact**: Every process start restores the kill switch. Health = degraded.
  No orders can be placed. The 12% drawdown that triggered it was from a test
  run, not a real account.
- **Fix**: Delete `kill_switch.flag`. Add it to `.gitignore`. Add a startup
  check that warns if the flag is older than 24 h and prompts for manual
  confirmation before restoring in production.

#### P1.2 ML model unpicklable on Python 3.12
- **File**: `ml/saved_models/advanced_oos.pkl`
- **Error**: `_pickle.UnpicklingError: STACK_GLOBAL requires str`
- **Impact**: `AdvancedModelPredictor` silently falls back to EMA crossover.
  The 66% OOS accuracy claim is irrelevant if the model cannot load.
- **Fix**: Retrain and serialise on Python 3.10 (matches Dockerfile `FROM
  python:3.10-slim`), or migrate to `joblib` with protocol pinning. Add a
  startup assertion that loads the model and logs its feature count.

#### P1.3 FIX adapter has no live broker credentials path
- **File**: `execution/fix_adapter.py`, `fix.cfg`
- **Impact**: `fix.cfg` contains placeholder `SenderCompID=HOPEFX` and
  `TargetCompID=BROKER`. IBKR FIX requires real comp IDs assigned by IBKR.
  The FIX session will never connect to a real broker without these.
- **Fix**: Document the exact IBKR FIX onboarding steps in `DEPLOYMENT.md`.
  Add a startup validator that checks `FIX_SENDER_COMP_ID` and
  `FIX_TARGET_COMP_ID` are non-placeholder values before starting FIXRouter.

---

### P2 — HIGH (test suite / code correctness)

#### P2.1 Integration test failures (4 tests)
- **File**: `tests/integration/test_api.py`
- **Tests**: `test_health_endpoint`, `test_admin_dashboard`,
  `test_admin_settings_page`, `test_admin_monitoring_page`
- **Root causes**:
  - Health: `/health` returns `status=degraded` because kill switch is active
    and Redis/DB are unavailable. Test asserts `status == "healthy"`.
  - Admin: Tests call `/api/admin/api/dashboard-data` (double prefix). Actual
    route is `/api/admin/dashboard-data`.
- **Fix**: Clear kill switch flag; fix test URLs to match actual routes.

#### P2.2 F821 undefined names — runtime NameErrors
- **Files and errors**:
  - `api/advanced_trading.py:356` — `prices` used but never defined in scope
  - `api/backtesting.py:634` — `BackgroundTasks` used but not imported
  - `api/ml.py:129,229` — `pd` used in type annotations but `pandas` not imported
  - `ml/online_learner.py:347,367,377,420` — same `pd` issue
  - `core/startup_factories.py:1252` — `Optional` used but not imported
  - `utils/fault_guard.py:56` — `os` used inside `if False` branch (dead code)
- **Impact**: Any code path hitting these will raise `NameError` at runtime.
- **Fix**: Add missing imports; fix the `prices` scope bug.

#### P2.3 test_risk_calculations.py — wrong assertions
- **File**: `test_risk_calculations.py`
- **Bugs**:
  - `test_max_drawdown_pause`: asserts `0.10 > 0.10` (boundary off-by-one).
    Drawdown of exactly 10% should trigger pause; test uses `assertGreater`
    instead of `assertGreaterEqual`.
  - `test_edge_cases`: asserts `ZeroDivisionError` from `0 / inf`. Python
    returns `0.0` for this — no exception is raised.
- **Fix**: Fix both assertions to match actual Python semantics.

#### P2.4 test_signal_generation.py — hard import of `talib`
- **File**: `test_signal_generation.py`
- **Impact**: Collection fails with `ModuleNotFoundError: No module named
  'talib'`. TA-Lib requires a C library that is not in `requirements.txt` and
  not installed in the devcontainer. This test is silently excluded from CI.
- **Fix**: Wrap import in `pytest.importorskip("talib")`.

#### P2.5 test_mt5_connection.py — hard import of `MetaTrader5`
- **File**: `test_mt5_connection.py`
- **Impact**: Same as above — MT5 is Windows-only. Collection fails on Linux.
- **Fix**: Wrap import in `pytest.importorskip("MetaTrader5")`.

---

### P3 — MEDIUM (security / compliance)

#### P3.1 k8s ConfigMap contains plaintext credentials
- **File**: `k8s/k8s-configmap.yaml`
- **Content**: `DATABASE_URL: "postgres://user:password@localhost:5432/mydatabase"`,
  `API_KEY: "your_api_key_here"`
- **Impact**: ConfigMaps are not encrypted at rest in most K8s clusters.
  Credentials belong in Secrets (base64) or an external secrets manager.
- **Fix**: Move all credential values to `k8s/k8s-secrets.yaml` or use
  External Secrets Operator. ConfigMap should only hold non-sensitive config.

#### P3.2 `deployment_guide.py` is a non-functional stub
- **File**: `deployment_guide.py`
- **Content**: 25 lines — prompts for DB host/user/password/API key via
  `input()`, prints them, does nothing else. No file write, no validation,
  no deployment logic.
- **Impact**: Misleading. Any operator running this gets a false sense of
  having configured the system.
- **Fix**: Either implement it properly (write `.env`, validate credentials,
  run Alembic migrations) or delete it and point to `deploy.sh`.

#### P3.3 `SECURE ENVIRONMENT FILE TEMPLATE` is a bare file with no extension
- **File**: `SECURE ENVIRONMENT FILE TEMPLATE` (root dir, no extension)
- **Impact**: Confusing. Likely meant to be `.env.example` or a doc. The
  space in the filename causes issues in shell scripts.
- **Fix**: Rename to `SECURE_ENV_TEMPLATE.md` or merge into `.env.example`.

---

### P4 — MEDIUM (structural debt / over-engineering)

#### P4.1 Four parallel backtesting engines
- `backtest/engine.py` (1,127 lines) — "legacy, kept for tests"
- `backtesting/engine.py` (858 lines) — "canonical"
- `enhanced_backtest_engine.py` (2,729 lines) — root-level, no clear owner
- `real_data_backtest.py` (570 lines) — root-level script

  The `backtest/engine.py` docstring says "Do not add new features here" but
  it is still 1,127 lines and actively used by tests. `enhanced_backtest_engine.py`
  duplicates walk-forward, CVaR, and slippage logic already in `backtesting/`.
  This is 5,284 lines of overlapping backtest code.

- **Fix**: Designate `backtesting/` as the single canonical engine. Migrate
  the 3 unique features from `enhanced_backtest_engine.py` into it. Delete
  `backtest/engine.py` after updating the 4 tests that import from it.

#### P4.2 Two parallel strategy packages
- `strategy/` — 1 file (`engine.py`, 341 lines): ML signal engine
- `strategies/` — 14 files: individual strategy implementations

  These serve different purposes but the naming is confusing. `strategy/engine.py`
  is the live signal producer; `strategies/` contains backtestable strategy
  classes. The distinction is not documented anywhere.

- **Fix**: Rename `strategy/` to `signal_engine/` or document the distinction
  clearly in both `__init__.py` files.

#### P4.3 Root-level test files duplicate `tests/` structure
- Root contains: `test_auth.py`, `test_integration.py`, `test_market_data.py`,
  `test_mt5_connection.py`, `test_performance.py`, `test_redis_connection.py`,
  `test_risk_calculations.py`, `test_signal_generation.py`, `test_trading.py`
- These are separate from `tests/unit/` and `tests/integration/`.
- `test_performance.py` collects 0 items. `test_redis_connection.py` collects
  0 items. These are dead files.
- **Fix**: Move valid tests into `tests/`. Delete dead files.

#### P4.4 Excessive meta-documentation
- 20+ markdown files at root: `CRITICAL_FLAWS.md`, `PRODUCTION_FIXES.md`,
  `DIAGNOSTIC_REPORT.md`, `ENHANCEMENT_PLAN.md`, `ENTERPRISE_ARCHITECTURE.md`,
  `ANALYSIS_AND_ROADMAP.md`, `IMPLEMENTATION_SUMMARY.md`, `DEBUGGING.md`,
  `DEPLOYMENT_CHECKLIST.md`, `DEPLOYMENT_INFRASTRUCTURE.md`, `FEATURES.md`,
  `WORDMAP.md`, `banner.md`, `PULL_REQUEST.md`, `CLA.md`, etc.
- These are iterative fix notes, not user-facing docs. They create noise and
  contradict each other (CRITICAL_FLAWS.md says "V14: 2560 passed, 0 failed"
  but the actual run shows 2,371 unit + 4 integration failures).
- **Fix**: Consolidate into `docs/`. Keep only `README.md`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `DEPLOYMENT.md` at root.

---

### P5 — LOW (performance / scalability)

#### P5.1 XGBoost `__del__` AttributeError on Python 3.12
- **Observed**: 6 `AttributeError: 'NoneType' object has no attribute
  'XGBoosterFree'` errors during test teardown.
- **Impact**: Cosmetic in tests; in production this means XGBoost objects are
  not being freed cleanly. Memory leak risk in long-running processes.
- **Fix**: Pin `xgboost>=2.0.0,<2.1.0` or upgrade to Python 3.10 (Dockerfile
  already uses 3.10 but devcontainer uses 3.12).

#### P5.2 Devcontainer Python version mismatch
- **Devcontainer**: Python 3.12.1
- **Dockerfile**: `FROM python:3.10-slim`
- **Impact**: Code that works in devcontainer may fail in Docker (and vice
  versa). The pickle error above is a direct consequence of this mismatch.
- **Fix**: Align devcontainer to Python 3.10, or pin all serialised artifacts
  to a version-agnostic format.

#### P5.3 Redis unavailable in devcontainer
- Every test run logs 4+ Redis connection failures. EventBus falls back to
  in-memory. This means pub/sub between strategy engine, gatekeeper, and FIX
  router is untested in the devcontainer environment.
- **Fix**: Add Redis to `.devcontainer/devcontainer.json` as a feature or
  Docker-in-Docker service.

---

### P6 — INFORMATIONAL (solid parts)

- **Auth system**: JWT + refresh tokens + 2FA + role-based access is
  well-implemented. 69 auth/pentest tests all pass.
- **Risk gatekeeper**: `risk/gatekeeper.py` correctly implements daily DD,
  max DD, news blackout, trade count, and confidence floor checks.
- **Kill switch**: Multi-trigger (file, env var, API, event bus) design is
  correct. The problem is stale state, not the implementation.
- **OANDA connector**: Both sync and async implementations exist with circuit
  breaker integration. Region routing is documented.
- **Watchlist flow**: 8 integration tests all pass including isolation,
  duplicate detection, and auth.
- **Alembic migrations**: Present and wired. DB schema is versioned.
- **Prometheus/Grafana**: docker-compose wires both with provisioning.
- **Unit test suite**: 2,371 tests, 9 skipped, 0 failures. Solid.

---

## VPS/Docker Deployment Notes

- `docker-compose.yml` is production-ready: health checks, named volumes,
  non-root user, Prometheus + Grafana wired.
- `POSTGRES_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` correctly use `:?` syntax
  (compose fails fast if unset). Good.
- The `trading` service healthcheck checks for a checkpoint file that only
  exists after a clean shutdown — it will always fail on first start.
  Change to a process-alive check instead.
- `libquickfix-dev` in Dockerfile: verify this package exists in Debian slim.
  It may need to be `libquickfix-dev` from a custom apt source.
- No resource limits (`mem_limit`, `cpus`) on any service. On a 2-core VPS,
  the ML training task will starve the API.

---

*This report supersedes CRITICAL_FLAWS.md, PRODUCTION_FIXES.md, and the
previous DIAGNOSTIC_REPORT.md. Those files are archived in `docs/archive/`.*
