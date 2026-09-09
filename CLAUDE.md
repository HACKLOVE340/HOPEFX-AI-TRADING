# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

This file is intentionally short. The authoritative, detailed guides are:

- **[AGENTS.md](AGENTS.md)** — full agent guide: layout, conventions, testing, ML, workflows.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — canonical module map, key entry points, env flags.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — contribution workflow.
- **`.claude/skills/flow-by-flow/SKILL.md`** — start every development task here;
  its sibling `flow-prototype` owns the UI/UX approval surface. Both are installed
  and version-locked at `2.0.1`; see the Agent Skills section of AGENTS.md.

Read those before any non-trivial change. The notes below are the high-signal subset.

---

## Picking up mid-programme — start here

If you are joining this work rather than starting it, **run this first**:

```bash
python scripts/backlog_report.py        # what is left, measured from the code
```

It reads the registries, the specifications and the working tree, so its answer
is always today's. Everything below is the shape; that command is the state.

| Question | Where it is answered |
|---|---|
| What is outstanding, and what must the owner decide? | `docs/ai/MASTER_OUTSTANDING.md` — §A is decisions only the owner can make |
| What is left, in what order, and how long? | `docs/ai/PROGRAMME_PLAN.md` — audit, sequence and effort, measured 2026-09-09 |
| Which spec capabilities are live, staged or planned? | `python scripts/backlog_report.py` · `ai/hub/capabilities.py` |
| Which safety gates have been proven able to fail? | `python scripts/gate_evidence.py` · `docs/GATE_EVIDENCE.toml` |
| How are the four specification groups organised? | `docs/ai/BACKLOG_GROUPS.md` |
| What binds every group? | `docs/ai/specs/GROUP4_CONSTITUTION.md` — T0, twelve Articles, INV-01…21 |
| How do I recover the database? | `docs/runbooks/database-restore.md` |
| How do I run the model without a market feed? | `python scripts/predict_offline.py` · `ml/cached_series.py` |
| Which committed price history is safe to train on? | `ml.cached_series.CLEAN_SINCE` — 2020+ for XAUUSD; `scripts/clamp_ohlc.py` for the rest |
| Which documents are authoritative, and who owns them? | `docs/REGISTRY.toml` |
| Why is it like this? Who decided, and what was rejected? | `python scripts/adr.py --list` · `docs/decisions/` |
| What did the platform decide today, and what did it refuse? | `ai/ledger/decisions.py::summary()` · refusals are first-class entries |
| What was this release *for*? | `python -m deployment.change_records --report` · trading-path commits should carry an `Expected-Effect:` trailer — a warning, not a block |

**Every number in those documents is a snapshot; every number the scripts print
is current.** Where they disagree, the script is right and the document is stale
— fix the document.

The ratcheted checks below run in `pre-commit`, so a regression blocks rather
than accumulating: document registry, documentation freshness, Group 4 source
preservation, volume-index drift, gate injection evidence, and stated-figure
drift.

**They only block once the hook is installed.** Until 2026-09-09 nothing
installed it, so on a fresh clone that sentence described something that was not
happening — every one of those gates protected only whoever remembered
`pre-commit run --all-files` by hand. `python scripts/bootstrap_dev.py` now runs
`pre-commit install`; if you cloned before that, run it, or run `pre-commit
install` directly. See MASTER_OUTSTANDING §E20.

### Standing rule from the owner — documentation ships with every push

**Never push code without updating the documents it makes stale.** Not "when it
seems worth it" — every push. A document that still looks current while carrying
a number that stopped being true is worse than no document, because a reader
acts on it without checking.

Concretely, before every commit:

1. If you changed what a gate, registry or ledger measures, run the script and
   update every document that states its figure.
   `python scripts/doc_metrics.py --check` blocks on the ones it can verify.
2. If you added a file a contributor must find, name it in the routing table
   above and in `ARCHITECTURE.md`.
3. If you closed a ranked gap, strike it through in the Group 2 or Group 3 gap
   list **with its evidence**, and update `docs/ai/MASTER_OUTSTANDING.md`.
4. If a document and a script disagree, the script is right — fix the document.

The commit message carries the reasoning; the documents carry the state. A
successor gets both or neither.

---

## What this is

HOPEFX is a Python/FastAPI + React/Vite AI trading platform for XAUUSD (gold):
ML inference, risk management, and multi-broker execution. Backend is a FastAPI
app; frontend is a React/TypeScript SPA. Status: paper trading active; live OANDA
is the next milestone.

This is a **money-moving system**. Prefer targeted, verified changes over broad
rewrites. Never weaken a risk gate, kill switch, or staleness/drift check without
explicit instruction.

---

## Canonical vs. legacy directories (common pitfall)

Add new code to the **canonical** dir, never the legacy shim:

| Domain | Use (canonical) | Do NOT add code to |
|--------|-----------------|--------------------|
| Backtesting | `backtesting/` | `backtest/` (re-export shim) |
| Strategies | `strategies/` | `strategy/` (live ML engine only) |
| Data pipeline | `data_layer/` for market-data *access* | *(nothing — see the note below)* |

WebSocket work goes in `api/ws_live.py`. The old standalone `websocket/`
server is **deleted** — never recreate a top-level `websocket/` package: it
shadows the `websocket-client` library for the whole project and silently
disables the REST fallback in `market_data/mt5_live_feed.py` (audit S13-02a).

Import market-data *access* via the public surface only:
`data_layer.orchestrator`, `data_layer.tick_store`, `data_layer.feeds.*`.

**`data/` is live runtime infrastructure.** These three docs used to describe it
as legacy data files, which was wrong and actionable: it told contributors to put
tick-feed and depth-of-market work in `data_layer/`, splitting one subsystem
across two packages (F216). The measured reality:

| Package | LOC | Production importers | What it is |
|---|---:|---:|---|
| `data_layer/` | 19,610 | 86 | Market-data **access**: orchestrator, tick store, feed adapters. The canonical public surface. |
| `data/` | 6,259 | 20 | Live **streaming and serving**: `real_time_price_engine.py`, `scheduler.py`, `depth_of_market.py`, `tick_feed.py`, `time_and_sales.py`, `streaming.py`, `feeds/macro.py`. Constructed in `core/startup_factories.py`, mounts three HTTP routers via `core/router_registry.py`, and `ml/training.py` reads its macro feed. |
| `market_data/` | 4,031 | 6 | Broker-side feeds, e.g. `mt5_live_feed.py`. |

**The boundary between them is not documented anywhere, and this file does not
invent one** (F217). Until it is agreed, extend the package a module already
lives in rather than moving code between them, and say which you chose in the PR.

---

## Key entry points

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app factory, startup/shutdown lifecycle |
| `hopefx_engine.py` | Standalone engine: NuclearStreamer → Brain → Risk → Broker |
| `run.py` | CLI runner (`--mode api \| engine \| backtest`) |
| `core/decision/HOPEFXDecisionEngine.py` | Central 5-phase decision pipeline |
| `ml/inference_engine.py` | Live inference with stale/drift gating |
| `risk/manager.py` | Pre-trade gate, VaR/CVaR, Kelly sizing, kill switch |
| `execution/oms.py` | Order Management System |
| `api/server.py` | FastAPI router aggregator |

---

## Commands

```bash
# Backend
python scripts/bootstrap_dev.py     # one-time: .env + dev users + install the git hooks
python run.py --mode api            # run FastAPI (port 8000)

# Tests (Python)
pytest -m "not slow and not e2e"    # fast suite (what CI runs)
pytest tests/unit/ -m "not slow"    # unit only
pytest --cov=. --cov-report=term-missing

# Lint / format (run before committing)
ruff check .                        # lint — must be clean
ruff format .                       # format
pre-commit run --all-files          # full gate (ruff, bandit, detect-secrets, merge-conflict)

# Frontend (frontend/)
npm ci && npm run dev               # Vite dev server (port 5173)
npm run typecheck && npm run build  # tsc --noEmit + vite build
npm test                            # vitest
```

Test markers: `unit`, `integration`, `e2e`, `slow`, `requires_redis`, `asyncio`.
`e2e` and `slow` are always skipped in CI.

---

## Before committing — non-negotiable

1. `ruff check .` is clean and the files you touched **compile**
   (`python -m py_compile <file>`).
2. **Run the hooks** — `pre-commit run --all-files`. They are configured
   (ruff, bandit, detect-secrets, and `check-merge-conflict`) but only protect
   you if you actually run them. Do **not** commit with `--no-verify`:
   that is exactly how merge-conflict markers and lint regressions slip in.
3. No leftover conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
4. Never commit secrets or real credentials. `prop_firm_mode.json` and
   `.env.example` carry **placeholders only**.

---

## Skills — use them, every time

**Standing instruction from the owner (2026-09-06): use the relevant skills on
every task, always.** Not "when it seems worth it" — every time. They exist
because this codebase has cost real money to get wrong, and each one encodes a
class of mistake already made here.

`.claude/skills/` holds **61** skills (`licenses/` is not one). All of them are
listed below. An earlier version of this file listed only thirteen "the ones
that earn their keep most often" — that was wrong in a way that mattered: a
skill nobody can see is a skill nobody loads, and the omitted 48 included every
Python-craft, observability, threat-modelling and incident skill in the set.

### Always, on every task

| Skill | When |
|---|---|
| `flow-by-flow` | **Start every development task here.** Picks mode, depth and risk floor, and names the affected flows. |
| `brainstorming` | Before any *creative* work — a new feature, component, or behaviour change. Explores intent before implementation. |
| `test-driven-development` | Before writing implementation code, for every feature and every bugfix. |
| `verification-before-completion` | Before claiming anything is done, fixed, or passing. Evidence before assertions. |
| `systematic-debugging` | The moment anything surprises you — a bug, a failing test, an unexpected result. |

### HOPEFX-specific — these encode defects already made here

| Skill | When |
|---|---|
| `hopefx-money-precision` | Prices, quantities, lot sizes, notional, P&L, balances, equity, fees, commissions; any Decimal↔float boundary; any reconciliation tolerance; any `==` on a monetary value. |
| `hopefx-invariants` | `verify_*` / `catastrophic_*` predicates, `enforce_*` call sites, `HOPEFX_INVARIANT_MODE`, fail-closed behaviour, or a refused pre-trade check. |
| `hopefx-dead-controls` | Any gate, guard, kill switch, health probe, alert, or "is it safe" check — **especially** when it looks correct but you have not traced that it runs. |
| `hopefx-fix-bridge` | `brokers/ibkr_fix_bridge.py`, `execution/fix_adapter.py`, FIX 4.4 sessions, sequence numbers, logon/heartbeat/reconnect, XAUUSD symbol mapping. |

### Planning and execution

| Skill | When |
|---|---|
| `writing-plans` | A spec or multi-step task, before touching code. |
| `executing-plans` | A written plan to execute with review checkpoints. |
| `planning-workflows` | Spec and no-spec planning workflows (requirements → design → tasks). |
| `using-git-worktrees` | Feature work needing isolation from the current workspace. |

### Review

| Skill | When |
|---|---|
| `requesting-code-review` | Completing a task or major feature, before merging. |
| `receiving-code-review` | Acting on review feedback — verification, not performative agreement. |
| `code-review-excellence` | Reviewing PRs, setting review standards. |
| `pr-review-fix` | Triaging CI failures and review comments across open PRs in batch. |
| `codebase-audit` | Full codebase review, severity triage, issues, worktree fixes. |
| `review-automation-orchestrator` | Scheduling periodic review cycles and routing findings. |
| `doc-freshness-review` | Documentation drift — `docs/`, `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `README.md`, `DEPLOYMENT.md`. |

### Python craft — reach for these by symptom

| Skill | When |
|---|---|
| `python-resilience` | Retries, exponential backoff, timeouts, fault tolerance, transient failures. |
| `python-error-handling` | Input validation, exception hierarchies, partial/batch failure. |
| `python-resource-management` | Context managers, cleanup, connections, file handles, streaming. |
| `python-background-jobs` | Task queues, workers, event-driven work, long-running operations. |
| `async-python-patterns` | asyncio, concurrency, async/await, I/O-bound systems. |
| `python-type-safety` | Type hints, generics, protocols, mypy/pyright configuration. |
| `python-testing-patterns` | pytest, fixtures, mocking, test suite structure. |
| `python-anti-patterns` | Checklist before finalising an implementation or when debugging a smell. |
| `python-performance-optimization` | Profiling with cProfile/memory profilers; slow code, bottlenecks. |
| `python-observability` | Structured logging, metrics, tracing, debugging production. |

### Trading, ML and data

| Skill | When |
|---|---|
| `backtesting-frameworks` | Look-ahead bias, survivorship bias, transaction costs, strategy validation. |
| `risk-metrics-calculation` | VaR, CVaR, Sharpe, Sortino, drawdown, risk limits. |
| `ml-pipeline-workflow` | End-to-end MLOps: data prep → training → validation → deployment. |
| `data-quality-frameworks` | Validation rules, data contracts, tick/feed quality and freshness. |
| `lightweight-charts` | TradingView lightweight-charts — series, scales, realtime data, plugins. |

### API, data storage and services

| Skill | When |
|---|---|
| `api-design-principles` | Designing or reviewing REST/GraphQL APIs and API standards. |
| `fastapi-templates` | New FastAPI apps, async patterns, dependency injection. |
| `postgresql-table-design` | PostgreSQL schema design or review — types, indexes, constraints. |

### Security and compliance

| Skill | When |
|---|---|
| `stride-analysis-patterns` | Threat modelling a system or feature. |
| `attack-tree-construction` | Mapping threat paths and defence gaps. |
| `threat-mitigation-mapping` | Mapping threats to controls; remediation plans. |
| `security-requirement-extraction` | Turning threats into requirements and security test cases. |
| `sast-configuration` | Static analysis / DevSecOps scanning setup. |
| `k8s-security-policies` | NetworkPolicy, PodSecurity, RBAC. |
| `pci-compliance` | Handling payment card data. |
| `stripe-integration` | Stripe checkout, subscriptions, webhooks, refunds. |

### Operations, observability and incidents

| Skill | When |
|---|---|
| `prometheus-configuration` | Metric collection, storage, alerting rules. |
| `grafana-dashboards` | Operational dashboards and metric visualisation. |
| `distributed-tracing` | Jaeger/Tempo, request flows across services. |
| `slo-implementation` | SLIs, SLOs, error budgets. |
| `incident-runbook-templates` | Step-by-step runbooks, escalation paths, recovery. |
| `on-call-handoff-patterns` | Shift handoffs, mid-incident transfer, on-call onboarding. |
| `postmortem-writing` | Blameless postmortems, root cause, action items. |

### UI, UX and frontend

| Skill | When |
|---|---|
| `ui-ux-pro-max` | **Any UI work** — styles, palettes, typography, charts, accessibility. Has a pre-delivery checklist; run it. |
| `flow-prototype` | Prototyping a complete interactive flow across screens and states **before** production UI. Owns the approval surface. |
| `frontend-design` | Visual direction — typography and aesthetics that do not read as templated defaults. |
| `e2e-testing-patterns` | Playwright/Cypress suites, flaky-test debugging. |
| `webapp-testing` | Driving a local web app with Playwright; screenshots, browser logs. |

### Skill maintenance

| Skill | When |
|---|---|
| `skill-authoring` | Creating, rewriting, auditing or evaluating skills. |
| `writing-skills` | Creating/editing skills and verifying them before deployment. |
| `manage-local-skills` | Standardising and syncing local skills into agent directories. |

---

Two rules that come from those skills and are worth repeating here, because
they are the ones most often skipped under time pressure:

1. **Every fix ships with a test that fails on the pre-fix tree.** Run it
   against the old code — `git stash`, run, `git stash pop` — and watch it
   fail. A test that has never failed proves nothing.
2. **Prove by execution, not by reading.** Reproduce the defect by running it
   before you fix it, and re-run the same reproduction after. Nine of the
   defects found in this repository read as correct.

## Gotchas

- **Python 3.12** is the production target — it is what `Dockerfile` runs
  (`python:3.12-slim`). CI tests **3.11 and 3.12**; the retrain workflows also
  run 3.12 so model artifacts are pickled on the same interpreter that loads
  them in production.
  This previously said 3.10 "matches the Docker image", which was false in both
  directions: the image was already 3.12, and 3.10 was tested by nothing.
  Because the stated reason for pinning is pickle compatibility on the
  committed `.pkl` artifacts, anyone following that advice produced artifacts
  under an interpreter neither CI nor production ever loaded. If you change the
  Dockerfile's Python, change the retrain workflows in the same commit.
- Model `.pkl`/`.zip` artifacts under `ml/saved_models/` and `ml/rl_models/`
  are **intentionally committed** (whitelisted in `.gitignore`, checksum-verified
  in CI). `dashboard/dist/` is **intentionally committed** so the server can
  serve the UI without a build step. Don't "clean these up."
- `WORDMAP.json` is gitignored; copy from `WORDMAP.json.example` locally.
  `prop_firm_mode.json` is **not** — `.gitignore` commits it deliberately with
  placeholder credentials so CI has a config to load. This file previously said
  it was gitignored, and the file's own `_comment` said so too, which invites
  putting real credentials in a tracked file. Keep credentials in environment
  variables. Note it also ships `enabled: true` with the FTMO ruleset, so a
  fresh deployment starts with those prop-firm limits active.
- `test-results.xml` is a CI-generated artifact — never commit it.
</content>
</invoke>
