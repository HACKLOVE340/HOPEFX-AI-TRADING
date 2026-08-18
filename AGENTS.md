# AGENTS.md — HOPEFX AI Trading

Agent and AI-assistant guidance for this repository.

---

## Project Overview

HOPEFX is a Python/FastAPI + React/Vite AI trading platform for XAUUSD (gold).
The backend is a FastAPI application with ML inference, risk management, and
multi-broker execution. The frontend is a React/TypeScript SPA served by Vite.

**Current status:** Paper trading active. Live OANDA run is the next milestone.

---

## Repository Layout

```
app.py                  FastAPI application factory (entry point)
hopefx_engine.py        Standalone trading engine entry point
run.py                  CLI runner (--mode api | engine | backtest)
quickstart.py           One-command paper trading start

api/                    FastAPI routers (REST + WebSocket + GraphQL)
core/                   Decision engine, startup factories
brain/                  Signal aggregation, nuclear supervisor, LLM agent
ml/                     Inference, training, RL agent, drift monitoring
risk/                   GARCH VaR, CVaR, Kelly sizing, kill switch
execution/              OMS, smart router, FIX adapter, TCA
data_layer/             Canonical market data pipeline (use this, not data/)
strategies/             Backtestable strategy classes (use this, not strategy/)
backtesting/            Canonical backtest engine (use this, not backtest/)
frontend/               React + TypeScript + Vite SPA

tests/                  All tests (unit/, integration/, e2e/, system/)
scripts/                Dev utilities (bootstrap_dev.py, etc.)
docs/                   Documentation (archive/ holds superseded docs)
```

### Canonical vs. Legacy Directories

| Domain | Use | Do NOT add code to |
|--------|-----|--------------------|
| Backtesting | `backtesting/` | `backtest/` (re-exports shim) |
| Strategies | `strategies/` | `strategy/` (live ML engine only) |
| Data pipeline | `data_layer/` | `data/` (CSV files + old utilities) |
| WebSocket | `api/ws_live.py` | `websocket/manager.py` (standalone server) |

---

## Development Environment

The devcontainer (`.devcontainer/devcontainer.json`) provides Python 3.12,
Node 20, and Redis. Three automations run on startup:

```bash
gitpod automations service start redis     # Redis on :6379
gitpod automations service start backend   # FastAPI on :8000
gitpod automations service start frontend  # Vite dev server on :5173
```

Bootstrap (run once, idempotent):
```bash
python scripts/bootstrap_dev.py
```
This generates `.env` with random secrets and seeds three dev users:
- `superadmin@hopefx.io` / `admin@hopefx.io` / `trader@hopefx.io`

---

## Key Entry Points

| File | Purpose |
|------|---------|
| `app.py` | FastAPI factory, startup/shutdown lifecycle |
| `hopefx_engine.py` | NuclearStreamer → Brain → Risk → Broker pipeline |
| `data_layer/orchestrator.py` | All price data and ML features flow through here |
| `strategies/strategy_brain.py` | 5-phase signal pipeline |
| `core/decision/HOPEFXDecisionEngine.py` | Central 5-phase decision pipeline |
| `ml/inference_engine.py` | Live inference with stale/drift checks |
| `risk/manager.py` | Pre-trade gate, VaR, CVaR, Kelly, kill switch |
| `execution/oms.py` | Order Management System |
| `api/server.py` | FastAPI router aggregator |

---

## Coding Conventions

### Python
- **Formatter:** `black` (line length 100 for Python, 120 for ruff)
- **Linter:** `ruff` — run `ruff check .` before committing
- **Type checker:** `mypy` — strict on `risk/analytics`, `api/`, `ml/inference_engine`
- **Python version:** 3.12 — it is what `Dockerfile` runs (`python:3.12-slim`) and
  what the retrain workflows use, so committed `.pkl` artifacts are pickled on the
  same interpreter that loads them in production. CI tests 3.11 and 3.12. If you
  change the Dockerfile's Python, change the retrain workflows in the same commit.
- Use `from __future__ import annotations` in all new modules
- Async-first in `api/` — use `async def` for all route handlers
- Domain-specific numeric literals (RSI levels, ATR multipliers, confidence scores)
  do not need named constants — `PLR2004` is suppressed project-wide

### TypeScript / React (frontend/)
- Formatter: Prettier (configured via VSCode settings)
- Component files: PascalCase `.tsx`
- Hooks: `use` prefix, camelCase

### Imports
- Do not import directly from `data_layer/` internal sub-packages.
  Use the public surface: `data_layer.orchestrator`, `data_layer.tick_store`,
  `data_layer.feeds.*`

---

## Testing

```bash
# Run all tests
pytest

# Unit tests only (fast, no external deps)
pytest tests/unit/ -m "not slow"

# Integration tests (requires Redis)
pytest tests/integration/ -m "not e2e"

# Skip slow ML training tests
pytest -m "not slow and not e2e"

# With coverage
pytest --cov=. --cov-report=term-missing
```

Test markers: `unit`, `integration`, `e2e`, `slow`, `requires_redis`, `asyncio`

- `e2e` tests require live broker/network — always skipped in CI
- `slow` tests run real ML training — skipped in CI
- Per-test timeout: 120 s (covers XGBoost walk-forward on CI hardware)

---

## ML Models

| Model | File | Status |
|-------|------|--------|
| XGBoost stacking ensemble | `ml/saved_models/advanced_oos.pkl` | Active production model |
| Nuclear PPO RL agent | `ml/rl_models/nuclear_decision_ppo.zip` | Powers nuclear supervisor |
| LSTM/Transformer/TCN | `research/pipeline/models_deep.py` | Architecture complete, not trained |
| PPO RL (live forex) | `ml/rl_agent.py` | Architecture complete, not trained |

Retrain the production model:
```bash
# Smoke test (~30 s)
python ml/train_advanced.py --smoke

# Full production retrain
python ml/train_advanced.py --years 50 --oos-years 4 --stacking
```

Model staleness and drift are enforced at inference time. `STALE_MODEL_BLOCK=true`
blocks inference when the model exceeds `MODEL_MAX_AGE_DAYS`. `DRIFT_BLOCK=true`
blocks signals when feature drift is detected.

---

## Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_ENV` | `production` | Set `development` in devcontainer |
| `BROKER_TYPE` | `paper` | `paper` / `oanda` / `ibkr` / `mt5` |
| `STALE_MODEL_BLOCK` | `true` | Block inference on stale model |
| `DRIFT_BLOCK` | `true` | Block signals on feature drift |
| `WS_AUTH_REQUIRED` | `true` | Require JWT on WebSocket |
| `REDIS_FORCE_TLS` | `false` | Auto-upgrade to `rediss://` |
| `ML_HOURLY_ENABLED` | `false` | Enable hourly online learning |

Full list: `.env.example`

---

## Security Rules

- **Never commit secrets.** `.env` and `WORDMAP.json` are gitignored
  (`WORDMAP.json.example` is the tracked template). `prop_firm_mode.json` is
  **not** gitignored — `.gitignore` commits it deliberately with placeholder
  credentials so CI has a config to load, and it ships `enabled: true` with the
  FTMO ruleset. Keep real credentials in environment variables, never in that
  tracked file. `detect-secrets` pre-commit hook enforces this.
- **Never log credentials.** The LLM agent (`brain/llm_agent.py`) runs in a
  subprocess sandbox — do not bypass this.
- **Redis TLS:** `REDIS_FORCE_TLS=true` in production. Dev uses plain Redis.
- **WebSocket auth:** `WS_AUTH_REQUIRED=true` — all WS connections require JWT.
- **Prop firm rules** are encoded in `prop_firm_mode.json` — do not hardcode
  drawdown limits in application code.

---

## CI / CD

15 GitHub Actions workflows run on push/PR to `main`:

| Workflow | What it checks |
|----------|---------------|
| `ci.yml` | pre-commit, ruff, bandit, mypy, pytest |
| `tests.yml` | Full test suite with coverage |
| `security-scan.yml` | pip-audit, bandit, detect-secrets |
| `codeql.yml` | CodeQL static analysis |
| `docker-smoke.yml` | Docker build + smoke test |
| `quarterly_retrain.yml` | Scheduled ML model retrain |

CI skips `e2e` and `slow` markers automatically (`-m "not slow and not e2e"`).

`tests.yml` also runs structural quality gates:

| Gate | Script | What it enforces |
|------|--------|-----------------|
| Gate A | `gate_a_auth_coverage.py` | Every mutating route has auth |
| Gate B | `gate_b_env_consistency.py` | `.env.example` matches code expectations |
| Gate C | `gate_c_docker_compose.py` | Compose files are structurally valid |
| Gate D | `gate_d_model_accuracy.py` | ML model meets minimum accuracy threshold |
| Gate E | `gate_e_dead_files.py` | No dead/unreferenced files in guarded packages |
| Gate F | `gate_f_doc_consistency.py` | Class/function names in docs exist in code |
| Gate G | `gate_g_import_discipline.py` | No imports from legacy directories |
| Gate H | `gate_h_wordmap_schema.py` | `WORDMAP.json.example` schema is valid |
| Gate I | `gate_i_migration_chain.py` | Alembic chain is linear with one root and one head |
| Gate J | `gate_j_circular_imports.py` | No module-level circular imports in guarded packages |
| Gate K | `gate_k_requirements_consistency.py` | Lock file covers all direct deps; no CI version downgrades |

---

## Task Workflows

### Run the full stack locally

```bash
gitpod automations service start redis     # must be first
gitpod automations service start backend   # waits for Redis ready probe
gitpod automations service start frontend  # Vite dev server on :5173
```

Check service health:
```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

---

### Add a new API endpoint

1. **Create the router file** in `api/`. Copy the structure of a nearby file
   (e.g. `api/alerts.py`). Use `async def` for all handlers. Include the
   copyright header.

2. **Add plan-gating** if the endpoint is a paid feature:
   ```python
   from monetization.subscription import require_plan
   from fastapi import Depends

   @router.get("/my-endpoint")
   async def my_endpoint(user=Depends(require_plan("professional"))):
       ...
   ```
   Plan tiers: `free`, `starter`, `professional`, `enterprise`, `elite`.

3. **Mount the router** in `api/server.py`:
   ```python
   from api.my_module import router as my_router
   app.include_router(my_router, prefix="/api/my-module", tags=["my-module"])
   ```

4. **Add an integration test** in `tests/integration/`:
   ```python
   @pytest.mark.integration
   async def test_my_endpoint(client):
       response = await client.get("/api/my-module/my-endpoint")
       assert response.status_code == 200
   ```

5. **Verify:** `ruff check api/my_module.py` and `mypy api/my_module.py`.

---

### Add a new trading strategy

1. **Create the strategy file** in `strategies/` (not `strategy/`).
   Subclass `BaseStrategy` from `strategies/base.py`:
   ```python
   from strategies.base import BaseStrategy, Signal, SignalType

   class MyStrategy(BaseStrategy):
       def generate_signal(self, market_data: dict) -> Signal:
           ...
   ```

2. **Register with StrategyBrain** if the strategy should participate in
   consensus voting. In `strategies/strategy_brain.py`, add it to the
   `_load_strategies` method alongside the existing strategies.

3. **Add a backtest** in `backtesting/`. Run it to verify the strategy
   produces sensible results before wiring it into the live engine:
   ```bash
   python backtesting/run_backtest.py --strategy my_strategy --years 5
   ```

4. **Add a unit test** in `tests/unit/`:
   ```python
   @pytest.mark.unit
   def test_my_strategy_generates_signal():
       strategy = MyStrategy(config={})
       signal = strategy.generate_signal(mock_market_data)
       assert signal.signal_type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
   ```

5. **Do not add code to `strategy/`** — that directory is the live ML engine
   and is not the place for new backtestable strategy classes.

---

### Add a new broker connector

1. **Create the connector file** in `brokers/`. Subclass `BaseBroker` from
   `brokers/base.py` and implement all abstract methods:
   ```python
   from brokers.base import BaseBroker, Order, Position

   class MyBroker(BaseBroker):
       async def connect(self) -> None: ...
       async def place_order(self, order: Order) -> str: ...
       async def get_positions(self) -> list[Position]: ...
       async def close_position(self, position_id: str) -> None: ...
   ```

2. **Register with BrokerFactory** in `brokers/factory.py`. Add a lazy-import
   block in `_ensure_registered()` following the existing pattern:
   ```python
   try:
       from brokers.my_broker import MyBroker
       cls._brokers["mybroker"] = MyBroker
   except Exception as exc:
       logger.debug("mybroker unavailable: %s", exc)
   ```

3. **Wire into the smart router** in `execution/smart_router.py` if the broker
   should be eligible for automatic routing decisions.

4. **Add an integration test** using a mock/paper mode:
   ```python
   @pytest.mark.integration
   async def test_my_broker_place_order():
       broker = MyBroker(config={"mode": "paper"})
       await broker.connect()
       order_id = await broker.place_order(mock_order)
       assert order_id is not None
   ```

5. **Document credentials** needed in `.env.example` with a comment block
   following the existing broker sections.

---

### Train or retrain the ML model

```bash
# Smoke test — verifies the pipeline runs end-to-end (~30 s)
python ml/train_advanced.py --smoke

# Full retrain with OOS evaluation (takes 10–60 min depending on hardware)
python ml/train_advanced.py --years 50 --oos-years 4 --stacking

# Multi-symbol backtest to verify generalisation
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

After retraining:
- New model is saved to `ml/saved_models/advanced_oos.pkl`
- Metadata is written to `ml/saved_models/advanced_oos_meta.json`
- **Update `ARCHITECTURE.md`** — ML Model Facts table — with the new OOS
  accuracy, AUC, Sharpe, N, and training date from the meta file.
- Restart the backend so the inference engine loads the new model:
  ```bash
  gitpod automations service stop backend
  gitpod automations service start backend
  ```

The source of truth for current model metrics is always
`ml/saved_models/advanced_oos_meta.json`, not README or ARCHITECTURE.md.

---

### Debug a failing CI workflow

1. **Find the failing step** in the GitHub Actions log. The workflow files are
   in `.github/workflows/`.

2. **Reproduce locally** using the same command the workflow runs:
   ```bash
   # ci.yml — lint
   ruff check .

   # ci.yml — type check
   mypy risk/analytics.py api/ ml/inference_engine.py

   # tests.yml — test suite
   pytest -m "not e2e and not slow" --tb=short

   # security-scan.yml — secrets
   pre-commit run detect-secrets --all-files
   ```

3. **Common failure causes:**
   - `ruff` failure: run `ruff check --fix .` to auto-fix, then review diffs
   - `mypy` failure on `api/` or `risk/`: these modules are strict — add type
     annotations rather than suppressing with `# type: ignore`
   - `pytest` import error: check that new modules have `__init__.py` and that
     optional dependencies are guarded with `try/except ImportError`
   - `detect-secrets`: a new high-entropy string was committed — either remove
     it or add a `.secrets.baseline` allowlist entry with justification

4. **Pre-commit hooks** can be run locally before pushing:
   ```bash
   pre-commit run --all-files
   ```

---

### Update the WORDMAP.json keyword scorer

`WORDMAP.json` is gitignored. To set it up locally:
```bash
cp WORDMAP.json.example WORDMAP.json
```

Edit `WORDMAP.json` to add or adjust severity weights (0.0–10.0). The scorer
merges your file with built-in defaults — you only need to include keys you
want to override. See `ARCHITECTURE.md` — WORDMAP.json section for details.

---

## Agent Skills

Two skills are installed in `.claude/skills/` and version-locked together at
`2.0.1`. Both must stay present — the orchestrator cannot complete its UI/UX
approval gate without its sibling.

| Skill | Use for |
|-------|---------|
| `flow-by-flow` | Any development task: features, bugs, refactors, audits, micro changes. Start here. |
| `flow-prototype` | Throwaway, read-only interactive model of a UI flow, required before any major UI/UX change reaches production code. |

`flow-by-flow` reads `references/orchestration.md` on every task, then loads only
the route that applies (`foundation`, `audit`, `build`, `delivery`, `review`,
`verification`). Its conflict hierarchy defers to this file: user instruction >
repository constitution (`AGENTS.md`) > security and data rules > flow contracts >
backend and design references > individual flow notes > builder judgment.

Two skill rules bind especially hard in this repository, which moves money:

- Never weaken a risk gate, kill switch, or staleness/drift check to make a flow
  pass. That is a stop condition, not a judgment call.
- Live broker activation, real-money order placement, production deployment, and
  destructive actions on real trade data are stop conditions requiring explicit
  authority for that exact action and target.

---

## Architecture Reference

See `ARCHITECTURE.md` for the canonical module map, ML model facts, component
status, and key environment variable flags.

See `docs/architecture.md` for the full system architecture diagram.
