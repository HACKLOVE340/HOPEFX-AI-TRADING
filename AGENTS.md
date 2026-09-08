# AGENTS.md — HOPEFX AI Trading

Agent and AI-assistant guidance for this repository.

---

## Project Overview

HOPEFX is a Python/FastAPI + React/Vite AI trading platform for XAUUSD (gold).
The backend is a FastAPI application with ML inference, risk management, and
multi-broker execution. The frontend is a React/TypeScript SPA served by Vite.

**Current status:** Paper trading active. Live OANDA run is the next milestone.

### Joining work already in progress? Start with these three

```bash
python scripts/backlog_report.py     # what is left to build or fix, measured now
python scripts/gate_evidence.py      # which safety gates are proven able to fail
```

| I need to know | Where it is answered |
|---|---|
| What should I work on? | `python scripts/backlog_report.py`, then `docs/ai/MASTER_OUTSTANDING.md` §B |
| What is blocked on the owner? | `docs/ai/MASTER_OUTSTANDING.md` §A — four decisions, each costed both ways |
| What rules bind every change? | `docs/ai/specs/GROUP4_CONSTITUTION.md` — **T0**, twelve Articles, INV-01…21 |
| How is the specification organised? | `docs/ai/BACKLOG_GROUPS.md` — four groups, one-group rule |
| How do I recover the database? | `docs/runbooks/database-restore.md` |
| Which skills apply, and when? | `CLAUDE.md` — all 61, with trigger conditions |

**A document's numbers are a snapshot; a script's numbers are today's.** Where
they disagree the script is right — fix the document, do not work around it.

### The four rules that govern this repository

They are stated in full in `docs/ai/specs/GROUP2_platform_engineering_operations_governance.md`
§0, and they decide most arguments:

1. **A control that cannot fail is not a control.** Every gate ships with evidence
   it can return a negative result, produced by injecting the defect it exists to
   catch. Eight controls here have been found unable to fail; every one was found
   by breaking it, none by reading it.
2. **An unmeasured value is absent, never zero.** Report `unmeasured` and why —
   never render a missing measurement as `0`, which looks like success.
3. **Fail closed on anything that spends, trades or exposes.** If a control cannot
   determine that an action is safe, it refuses.
4. **Evidence that resolves is not evidence that runs.** A registry entry that
   points at real code says nothing about whether anything calls it.

### And a fifth, from the owner: documentation ships with every push

**Never push code without updating the documents it makes stale.** The failure
this guards against is not a missing file — it is a document that still looks
current while carrying a figure that stopped being true, which a reader then
acts on without checking.

`python scripts/doc_metrics.py --check` runs in pre-commit and blocks when a
living document states a figure that no longer matches its measuring script. It
covers arithmetic; the rest is yours:

| You changed | Update |
|---|---|
| What a gate, registry or ledger measures | Every document stating its figure — `doc_metrics.py --check` blocks on the verifiable ones |
| A file a contributor must be able to find | `CLAUDE.md` routing table and `ARCHITECTURE.md` entry points |
| A ranked gap you closed | Strike it through **with its evidence** in the Group 2/3 gap list, and update `docs/ai/MASTER_OUTSTANDING.md` |
| A safety control | `docs/GATE_EVIDENCE.toml` — see *Add a gate, guard, or any other safety control* below |

The commit message carries the reasoning; the documents carry the state. A
successor gets both or neither.

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
| Data pipeline | `data_layer/` for market-data *access* | *(nothing — `data/` is live; see CLAUDE.md)* |
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
| Gate L | `gate_l_safety_invariants.py` | Safety-critical env defaults stay safe (`BROKER_TYPE`, `FEATURE_LIVE_TRADING`, `DRIFT_BLOCK`, `STALE_MODEL_BLOCK`, `WS_AUTH_REQUIRED`, `REDIS_FORCE_TLS`) |
| Gate M | `gate_m_ml_edge.py` | ML still beats the rule baseline on the leakage-safe OOS split |

| Broken imports | `gate_broken_imports.py` | No `from x import Y` where `Y` is undefined in `x` |

`gate_broken_imports.py` carries a `KNOWN_BROKEN` baseline of imports that are
still broken on purpose or awaiting implementation (see S-41/S-42 in
`docs/HARDENING_BACKLOG.md`). Every entry needs a reason and a backlog
reference. Fixing an import means **deleting its entry in the same change** — a
stale entry fails the gate, so the list cannot quietly become an excuse list.

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

### Add a gate, guard, or any other safety control

**Rule 1 applies and it is enforced, not advisory.** `scripts/gate_evidence.py`
runs in pre-commit, discovers gates rather than reading a list, and blocks a new
one that arrives without evidence.

1. Write the control.
2. **Inject the defect it exists to catch** — against a copied tree, never the
   working files. Watch it refuse. If it does not, you have a control-shaped
   object, not a control.
3. Make that injection a test, and assert the injection actually applied. An
   injection that silently fails to apply leaves the gate passing, which is
   indistinguishable from a gate that cannot fail. That mistake has been made
   here twice.
4. Add a row to `docs/GATE_EVIDENCE.toml` naming the test and the defect
   injected. `python scripts/gate_evidence.py --generate` adds the row skeleton.
5. Run `python scripts/gate_evidence.py --check`.

Worked examples: `tests/unit/test_gate_l_safety_injections.py` (seven trading
incidents), `tests/unit/test_check_secrets_injections.py` (a real bypass found
and closed), `tests/unit/test_database_restore.py` (six fail-closed refusals).

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

**61 skills are installed** in `.claude/skills/`. CLAUDE.md carries the full
list grouped by when to reach for each; `.claude/skills/README.md` carries the
provenance, licences, and local patches. This section previously said "two
skills are installed", naming only the two below — that was wrong in the way
that matters: a skill nobody can see is a skill nobody loads, and the other 59
include every Python-craft, observability, threat-modelling, and incident skill
in the set.

**The owner's standing instruction (2026-09-06) is to use the relevant skills on
every task, always** — not when it seems worth it. Start with `flow-by-flow`.

These two are version-locked together at `2.0.1` and must both stay present —
the orchestrator cannot complete its UI/UX approval gate without its sibling:

| Skill | Use for |
|-------|---------|
| `flow-by-flow` | Any development task: features, bugs, refactors, audits, micro changes. Start here. |
| `flow-prototype` | Throwaway, read-only interactive model of a UI flow, required before any major UI/UX change reaches production code. |

Four of the 61 are **custom to this repository** — `hopefx-money-precision`,
`hopefx-invariants`, `hopefx-dead-controls`, `hopefx-fix-bridge`. Each encodes a
defect class already made here, and every mechanically checkable claim in them is
verified against the codebase by `scripts/verify_skill_claims.py`, which runs in
CI. Re-run it after any refactor that moves a cited line:

```bash
python scripts/verify_skill_claims.py
```

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

### The governance layer above both

| Document | Tier | What it settles |
|---|---|---|
| `docs/ai/specs/GROUP4_CONSTITUTION.md` | **T0** | Twelve Articles and INV-01…21. Above the specifications, and above code on the Articles: where code violates one, the code is the defect |
| `docs/ai/specs/GROUP4_VOLUME_INDEX.md` | T1 | All 304 titles from both Group 4 sources, routed to the group that owns each |
| `docs/ai/specs/GROUP1_advanced_intelligence_architecture.txt` | T1 | Intelligence: cognition, memory, perception, evolution |
| `docs/ai/specs/GROUP2_platform_engineering_operations_governance.md` | T1 | Platform: 35 chapters, nine Parts, and the four rules |
| `docs/ai/specs/GROUP3_documentation_knowledge_architecture_governance.md` | T1 | Knowledge: 18 chapters — how documents are governed |
| `docs/REGISTRY.toml` | T2 | Which document is authoritative on which subject, and who owns it |

Relationship rule across all of them: where an item touches another group, the
owning group is **referenced, never copied**. That is the whole defence against
duplicate specifications that disagree.
