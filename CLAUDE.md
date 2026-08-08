# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

This file is intentionally short. The authoritative, detailed guides are:

- **[AGENTS.md](AGENTS.md)** — full agent guide: layout, conventions, testing, ML, workflows.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — canonical module map, key entry points, env flags.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — contribution workflow.

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
| Data pipeline | `data_layer/` | `data/` (CSV + old utilities) |

WebSocket work goes in `api/ws_live.py`. The old standalone `websocket/`
server is **deleted** — never recreate a top-level `websocket/` package: it
shadows the `websocket-client` library for the whole project and silently
disables the REST fallback in `market_data/mt5_live_feed.py` (audit S13-02a).

Import data via the public surface only: `data_layer.orchestrator`,
`data_layer.tick_store`, `data_layer.feeds.*`.

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
- `WORDMAP.json` and the live-credential `prop_firm_mode.json` overrides are
  gitignored; copy from the `*.example` templates locally.
- `test-results.xml` is a CI-generated artifact — never commit it.
</content>
</invoke>
