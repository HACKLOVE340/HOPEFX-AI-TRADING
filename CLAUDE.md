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
python scripts/bootstrap_dev.py     # one-time: generate .env + seed dev users
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

`.claude/skills/` holds 60 of them. The ones that earn their keep most often:

| When you are… | Load |
|---|---|
| starting **any** development task | `flow-by-flow` (then `flow-prototype` for a UI surface) |
| touching prices, balances, P&L, fees, lot sizes | `hopefx-money-precision` |
| touching a gate, limit, kill switch or invariant | `hopefx-invariants`, `hopefx-dead-controls` |
| writing any fix | `test-driven-development`, `verification-before-completion` |
| chasing a bug | `systematic-debugging` |
| touching Stripe, billing, webhooks, refunds | `stripe-integration` |
| touching any UI | `ui-ux-pro-max` (and its pre-delivery checklist) |
| touching retries, timeouts, circuit breakers | `python-resilience` |
| reasoning about an attack surface | `stride-analysis-patterns`, `attack-tree-construction` |
| planning work bigger than one file | `writing-plans`, then `executing-plans` |
| touching tick/feed quality or freshness | `data-quality-frameworks` |
| touching the ML pipeline | `ml-pipeline-workflow`, `backtesting-frameworks` |

Two rules that come from those skills and are worth repeating here, because
they are the ones most often skipped under time pressure:

1. **Every fix ships with a test that fails on the pre-fix tree.** Run it
   against the old code — `git stash`, run, `git stash pop` — and watch it
   fail. A test that has never failed proves nothing.
2. **Prove by execution, not by reading.** Reproduce the defect by running it
   before you fix it, and re-run the same reproduction after. Nine of the
   defects found in this repository read as correct.

---

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
