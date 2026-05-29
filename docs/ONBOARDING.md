# HOPEFX Developer Onboarding Guide

> Last updated: 2026-05-29  
> This guide takes a new contributor from zero to running tests in one sitting.  
> Complements [`docs/QUICKSTART.md`](QUICKSTART.md) (end-user) and [`CONTRIBUTING.md`](../CONTRIBUTING.md) (PR process).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and Bootstrap](#2-clone-and-bootstrap)
3. [Environment Variables](#3-environment-variables)
4. [Run the Stack](#4-run-the-stack)
5. [Run Tests](#5-run-tests)
6. [Codebase Map](#6-codebase-map)
7. [Key Concepts](#7-key-concepts)
8. [Development Workflow](#8-development-workflow)
9. [Linting and Code Style](#9-linting-and-code-style)
10. [Database Migrations](#10-database-migrations)
11. [Frontend Development](#11-frontend-development)
12. [ML Pipeline](#12-ml-pipeline)
13. [Secrets and Security](#13-secrets-and-security)
14. [CI Gates](#14-ci-gates)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Prerequisites

| Tool | Minimum version | Purpose |
|------|-----------------|---------|
| Python | 3.12 | Backend runtime |
| Node.js | 20 LTS | Frontend build |
| Docker + Compose | 24+ | Full local stack |
| Git | 2.40+ | Version control |
| PostgreSQL (or Docker) | 15+ | Primary database |
| Redis (or Docker) | 7+ | Cache, pub/sub, tick buffer |

> **Tip — use Docker.**  Running `docker compose up` is the fastest path.  
> Pure local setup is described in §2 below for contributors who need breakpoint debugging.

---

## 2. Clone and Bootstrap

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# Python virtualenv
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Python dependencies
pip install -r requirements.txt

# Frontend dependencies
cd frontend && npm install --legacy-peer-deps && cd ..
```

The first `pip install` takes 2–5 minutes; it installs PyTorch CPU, XGBoost, LightGBM, and FastAPI along with ~140 other packages.

### Verify install

```bash
python -c "import fastapi, sqlalchemy, torch, xgboost; print('OK')"
cd frontend && npx tsc --noEmit && echo "TS OK"
```

---

## 3. Environment Variables

```bash
cp .env.example .env
```

Edit `.env` — the fields marked `CHANGE_ME` **must** be set before the app starts:

| Variable | Description |
|----------|-------------|
| `SECURITY_JWT_SECRET` | 64-char hex string for JWT signing — generate with `openssl rand -hex 32` |
| `DB_ENCRYPTION_KEY` | 32-byte URL-safe base64 key for AES-256-GCM column encryption — generate with `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `DATABASE_URL` | PostgreSQL DSN, e.g. `******localhost:5432/hopefx` |
| `REDIS_URL` | Redis DSN, e.g. `redis://localhost:6379/0` |
| `STRIPE_SECRET_KEY` | Stripe secret key (use test key `sk_test_...` in development) |
| `OANDA_API_KEY` | OANDA API token — not required for unit tests, required for paper trading |

> Variables **without** `CHANGE_ME` in their default value are optional and have sensible defaults for local development.

---

## 4. Run the Stack

### Docker (recommended)

```bash
docker compose up --build
```

Services started:
- **app** — FastAPI on `http://localhost:8000`
- **frontend** — Vite dev server on `http://localhost:5173` (with HMR)
- **postgres** — PostgreSQL on `localhost:5432`
- **redis** — Redis on `localhost:6379`
- **celery** — Background task worker

The Vite dev server proxies `/api` and `/ws` to the FastAPI backend; open `http://localhost:5173` for the full app.

### Manual (for breakpoint debugging)

```bash
# Terminal 1 — FastAPI
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend && npm run dev

# Terminal 3 — Celery worker (optional)
celery -A celery_app worker --loglevel=info
```

---

## 5. Run Tests

```bash
# Fast unit tests (no I/O, no broker connections)
pytest tests/unit/ -x -q

# Integration tests (requires running Postgres + Redis)
pytest tests/integration/ -x -q

# Full suite (skip e2e and slow ML tests in CI)
pytest tests/ -m "not e2e and not slow" -q

# Single test file
pytest tests/unit/test_risk_analytics.py -v

# With coverage
pytest tests/unit/ --cov=. --cov-report=term-missing -q
```

Test directory layout:

| Directory | Contents |
|-----------|---------|
| `tests/unit/` | Pure unit tests — no database, no broker |
| `tests/integration/` | Tests that use Postgres + Redis via testcontainers |
| `tests/e2e/` | Full pipeline tests — requires live or paper broker |
| `tests/system/` | Deployment and smoke tests run in CI against a real Docker stack |
| `tests/fixtures/` | Shared pytest fixtures (db session, fake user, etc.) |

> `tests/conftest.py` sets `CI_FAST=1` which reduces XGBoost `n_estimators` from 300 → 50 for faster test runs.

---

## 6. Codebase Map

```
HOPEFX-AI-TRADING/
├── app.py                  FastAPI application factory + ASGI entry point
├── core/
│   ├── app_state.py        Global singletons (price_engine, nuclear_streamer, …)
│   ├── startup_factories.py Component factories wired in FastAPI lifespan
│   ├── startup_helpers.py  Startup helper functions (data layer, ML prewarm, …)
│   ├── compat_router.py    Convenience alias endpoints (307 redirects)
│   └── router_registry.py  Central router mount table
├── api/                    FastAPI route handlers (one file per domain)
├── database/
│   ├── models.py           SQLAlchemy ORM models (trades, orders, portfolio, …)
│   ├── user_models.py      User / session / token models
│   └── encryption.py       AES-256-GCM TypeDecorator for sensitive columns
├── alembic/                Database schema migration scripts
├── ml/
│   ├── inference_engine.py Live prediction: features → stale check → drift → predict
│   ├── train_advanced.py   Offline training: XGBoost + LightGBM + RF + stacking
│   ├── drift_detector.py   Z-score drift detection on live feature buffer
│   └── drift_monitor.py    PSI + KS-test drift monitor; GET /api/ml/drift-report
├── risk/
│   ├── manager.py          Pre-trade gate, GARCH VaR, CVaR, Kelly, prop firm limits
│   └── circuit_breaker.py  Sharpe-based automatic circuit breaker
├── execution/
│   ├── oms.py              Order Management System (9 states, GTC/IOC/FOK/OCO)
│   └── smart_router.py     Microstructure-aware multi-broker order router
├── data_layer/
│   ├── orchestrator.py     MarketDataOrchestrator — canonical price data source
│   └── aggregator/         OHLCV bar builder, microstructure, order flow imbalance
├── brokers/                Live broker connectors (OANDA, IBKR, Bybit, MT5)
├── strategies/             Backtestable strategy classes
├── strategy/               Live ML signal engine (strategy_brain.py)
├── portfolio/              Portfolio optimizer and PMS
├── auth/                   JWT auth, OAuth2, 2FA, KYC
├── frontend/               React + TypeScript SPA (Vite, TanStack Query, Zustand)
│   ├── src/
│   │   ├── App.tsx         Root router; all lazy-loaded routes; ErrorBoundary
│   │   ├── pages/          Page-level components (one per route)
│   │   ├── components/     Shared UI components and panels
│   │   ├── features/       Feature modules (chart-bot, etc.)
│   │   ├── hooks/          Custom React hooks
│   │   ├── store/          Zustand global state
│   │   └── lib/            Utilities, API client, formatters
│   └── public/             Static assets (icons, manifest)
├── tests/                  Test suite (see §5)
└── docs/                   Documentation
```

---

## 7. Key Concepts

### Request lifecycle

```
Browser → Vite (dev proxy) / Nginx (prod)
  → FastAPI app.py
    → auth/router.py (JWT verification)
    → api/<domain>.py (route handler)
      → data_layer or broker or ml
    → database (async SQLAlchemy)
```

### Data flow

```
Market feed (OANDA/IBKR/MT5)
  → data_layer/orchestrator.py (MarketDataOrchestrator)
    → data_layer/aggregator/ (OHLCV bars)
    → ml/inference_engine.py (feature extraction → predict)
    → risk/manager.py (pre-trade gate)
    → execution/oms.py (order lifecycle)
    → brokers/<connector>.py (send to exchange)
```

### Async everywhere

All database access, broker I/O, and ML inference are `async`.  Use `await` and `async with` consistently.  `asyncio.run()` is reserved for standalone scripts.

### State management

Global singletons live in `core/app_state.py`.  Access them via `app_state.price_engine`, `app_state.nuclear_streamer`, etc.  Never instantiate these directly in route handlers — use the factories in `core/startup_factories.py`.

### Feature flags

Subscription gates use `features_json` on `WhitelabelTenant` and the `SubscriptionGate` React component.  Backend enforcement is in `auth/dependencies.py::require_feature`.

---

## 8. Development Workflow

```bash
# 1. Create a feature branch
git checkout -b feat/my-feature

# 2. Make changes, commit early and often
git add -p          # stage hunks, not whole files
git commit -m "feat(domain): short summary"

# 3. Before pushing: lint + test
ruff check --fix .
pytest tests/unit/ -x -q

# 4. Push and open a PR
git push origin feat/my-feature
```

Commit message format: `type(scope): summary` where type is one of `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `security`.

---

## 9. Linting and Code Style

```bash
# Python — Ruff (replaces flake8/isort/pyupgrade)
ruff check .          # check
ruff check --fix .    # auto-fix safe rules

# TypeScript — tsc
cd frontend && npx tsc --noEmit

# Frontend linting
cd frontend && npm run lint
```

CI runs `ruff check` on every changed Python file (excluding tests, alembic, examples, and frontend).  PRs will fail if new lint errors are introduced.

Style rules in `pyproject.toml` / `ruff.toml`.  Key conventions:
- Double-quoted strings in Python
- `from __future__ import annotations` at the top of every Python file
- `UTC = timezone.utc`; use `datetime.now(UTC)` not `datetime.utcnow()`
- No bare `except:` — always catch specific exceptions

---

## 10. Database Migrations

Migrations live in `alembic/versions/`.  Revision IDs follow the pattern `[a-z0-9]{12}_<short_description>.py`.

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration (auto-detect model changes)
alembic revision --autogenerate -m "add_my_table"

# Show current migration state
alembic current

# Roll back one revision
alembic downgrade -1
```

**Migration guidelines:**
- Always use `op.batch_alter_table` for column changes in SQLite-compatible code (test environments).
- Drop foreign key constraints **before** dropping columns; use inspector lookups to confirm existence.
- Guard column additions with `inspector.get_columns()` checks to be re-entrant.
- Add `# nosec B110` on intentional `except SomeError: pass` lines to pass the CI security scan.

---

## 11. Frontend Development

```bash
cd frontend

npm run dev        # start Vite dev server with HMR
npm run build      # production build → ../static/
npx tsc --noEmit   # TypeScript check
npm run lint       # ESLint
npm run test       # Vitest unit tests
npm run test:e2e   # Playwright E2E (requires running backend)
```

### Key frontend patterns

- **Charts**: All charting uses `lightweight-charts` v5 only (recharts/chart.js removed).  Use the imperative `createChart()` API; wrap in `useEffect` + `useRef`.  Always sort + deduplicate data by time before calling `series.setData()`.
- **State**: Zustand stores in `src/store/`.  Server state via TanStack Query.  No Redux.
- **Code splitting**: All page components are lazy-loaded via `React.lazy()`.  Every route is wrapped in `ErrorBoundary` via the `wrap()` helper in `App.tsx`.
- **API calls**: Use hooks from `src/hooks/` which wrap `useQuery`/`useMutation`.  The Vite dev proxy forwards `/api/*` to `localhost:8000`.
- **PWA**: Service worker is generated by `vite-plugin-pwa`.  API routes are `NetworkOnly` (never serve stale financial data from cache).

---

## 12. ML Pipeline

### Offline training

```bash
# Train with 50-year history, 4-year OOS hold-out, stacking
python ml/train_advanced.py --years 50 --oos-years 4 --stacking

# Train fast (CI/dev mode — 2 years, no OOS)
python ml/train_advanced.py --years 2
```

Trained models are saved to `ml/saved_models/`.  The inference engine loads the latest version on startup and hot-reloads when a new version is registered via `ml/model_registry.py`.

### Drift monitoring

The endpoint `GET /api/ml/drift-report` returns real-time PSI + KS-test statistics.  Thresholds:
- PSI < 0.10 → no drift (green)
- PSI 0.10–0.25 → investigate (yellow)
- PSI > 0.25 → retrain recommended (red)
- KS p-value < 0.05 → distributions significantly different

Drift monitoring requires ≥ 50 live inference ticks to build the comparison window.

---

## 13. Secrets and Security

**Never commit secrets.**  The pre-commit hook and CI Gate A will reject any commit that contains a hardcoded credential.

### Environment secrets checklist

| Secret | Where used | How to generate |
|--------|-----------|-----------------|
| `SECURITY_JWT_SECRET` | JWT signing | `openssl rand -hex 32` |
| `DB_ENCRYPTION_KEY` | AES-256-GCM TOTP column encryption | `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `CONFIG_ENCRYPTION_KEY` | Config store encryption | `openssl rand -base64 36` |
| `STRIPE_SECRET_KEY` | Stripe billing | Stripe dashboard |
| `OANDA_API_KEY` | Live/paper trading | OANDA portal |

### Rotating secrets

1. Generate a new value.
2. Update the secret in your deployment platform (GitHub Secrets / AWS Secrets Manager / Vault).
3. For `DB_ENCRYPTION_KEY`: existing encrypted rows use the old key.  Run `python scripts/rotate_db_encryption_key.py --old-key OLD --new-key NEW` to re-encrypt in place (script reads → decrypts with old key → encrypts with new key → writes back).

---

## 14. CI Gates

All PRs run through six sequential gates defined in `.github/workflows/`:

| Gate | Check |
|------|-------|
| **A** — Auth coverage | Every non-public endpoint is protected by JWT/role middleware |
| **B** — Schema consistency | ORM models match Alembic migration state |
| **C** — No mock data in production | No `Mock(`, `MagicMock`, synthetic `CHANGE_ME` data in `api/` or `database/` |
| **D** — Ruff lint | No lint errors in changed Python files |
| **E** — Dead file detection | No imported modules are unreachable |
| **F** — Docker smoke | `docker compose up` starts clean and `/api/health` returns 200 |

Fixing a gate failure:
- **Gate A**: add `Depends(get_current_user)` or `Depends(require_role(...))` to the unprotected route.
- **Gate D**: run `ruff check --fix .` locally.
- **Gate F**: check the smoke test logs — common causes are DB migration failures or missing env vars.

---

## 15. Troubleshooting

### `RuntimeError: CRITICAL DEPENDENCY MISSING: SQLAlchemy`

```bash
pip install 'sqlalchemy>=2.0'
# or
pip install -r requirements.txt
```

### `alembic.exc.ProgrammingError: column does not exist`

The migration chain has a gap.  Run `alembic current` to see where you are, then `alembic upgrade head`.

### `TS2322: Type 'X' is not assignable to type 'DeepPartial<LineWidth>'`

LWC v5 requires integer line widths (1–5).  Change `lineWidth: 1.5` → `lineWidth: 2`.

### Vite HMR not connecting in Gitpod / GitHub Codespaces

The `vite.config.ts` `allowedHosts` list includes `.gitpod.io`, `.gitpod.dev`, and `.preview.app.github.dev`.  If your environment URL doesn't match, add it to that array.

### `CORS error` on API calls from frontend

Ensure the Vite proxy is configured for your custom endpoint prefix.  The `/api`, `/ws`, `/kyc`, `/graphql` prefixes are proxied by default.

### Redis connection refused

```bash
# Local
redis-server --daemonize yes

# Docker
docker compose up redis
```

### ML drift report returns `unknown` status

Start live inference to populate the 50-tick drift buffer:
```bash
python hopefx_engine.py --mode paper --symbol XAUUSD
```

---

*For architecture deep-dives, see [`docs/architecture.md`](architecture.md).*  
*For the API reference, see [`docs/API_REFERENCE.md`](API_REFERENCE.md).*  
*For deployment, see [`DEPLOYMENT.md`](../DEPLOYMENT.md).*
