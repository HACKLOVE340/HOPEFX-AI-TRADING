# Setup Guide

## Requirements

- Python 3.10, 3.11, or 3.12
- Git
- PostgreSQL 16 (production) or SQLite (development — zero config)
- Redis 7 (optional — rate limiting and caching fall back to in-memory without it)

---

## 1. Clone and install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

For CI or lightweight environments (no C extensions, no GPU deps):

```bash
pip install -r requirements-ci.txt
```

---

## 2. Environment configuration

```bash
cp .env.example .env
```

Minimum required variables (app will not start without these):

```env
# JWT signing key — generate with:
# python -c "import secrets; print(secrets.token_urlsafe(48))"
SECURITY_JWT_SECRET=<48-char random string>

# Application mode: development | production | test
APP_ENV=development
```

Additional variables for full functionality:

```env
# Broker (default: paper trading — no credentials needed)
BROKER_TYPE=paper                  # paper | oanda | ibkr | ccxt | fix

# OANDA paper trading (free practice account at oanda.com)
OANDA_API_KEY=your_practice_token
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001
OANDA_ENVIRONMENT=practice

# Database (SQLite used automatically in development if unset)
DATABASE_URL=postgresql://user:pass@localhost:5432/hopefx

# Redis (in-memory fallback used if unset)
REDIS_URL=redis://localhost:6379/0

# Monitoring (optional but recommended in production)
SENTRY_DSN=https://...@sentry.io/...
```

Generate and validate all production secrets at once:

```bash
python scripts/manage_secrets.py generate
python scripts/manage_secrets.py validate
```

---

## 3. Database setup

**Development (SQLite — zero config):**

The app creates `hopefx.db` automatically on first start. No setup needed.

**Production (PostgreSQL):**

```bash
# Run Alembic migrations
alembic upgrade head
```

This applies all 6 migrations (initial schema through watchlists table).

---

## 4. Start the application

```bash
# Development (auto-reload on file changes)
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Or via the CLI
python cli.py serve
```

Verify it started:

```bash
curl http://localhost:8000/health
# {"status":"healthy","version":"2.0.0","environment":"development",...}
```

- **Dashboard**: http://localhost:8000/
- **API explorer**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Metrics**: http://localhost:8000/metrics (Prometheus format)

---

## 5. Run the test suite

```bash
# Smoke tests (fast, no external deps)
python -m pytest tests/test_smoke_critical.py -q

# Unit tests
python -m pytest tests/unit/ -q

# Integration tests (needs app importable)
python -m pytest tests/integration/ -q

# Full suite
python -m pytest tests/ -q
```

---

## 6. Docker Compose (full stack)

Starts app + PostgreSQL 16 + Redis 7 + Prometheus + Grafana:

```bash
# Copy and fill in required secrets first
cp .env.example .env
# Edit .env — set SECURITY_JWT_SECRET, DB_PASSWORD, etc.

docker compose up -d
```

Services:
| Service | URL |
|---------|-----|
| API + Dashboard | http://localhost:8000 |
| Grafana | http://localhost:3000 (admin / see GRAFANA_ADMIN_PASSWORD) |
| Prometheus | http://localhost:9090 |

---

## 7. Kubernetes (Helm)

```bash
helm install hopefx helm/hopefx/ \
  --set secrets.jwtSecret="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --set secrets.dbPassword="your-db-password"
```

See `helm/hopefx/values.yaml` for all configurable parameters.

---

## 8. ML model

The production model (`ml/saved_models/advanced_oos.pkl`) is included in the repository — 176 features, 66.4% OOS accuracy (p=0.0000, N=1,260 bars), validated 2026-03-28.

To retrain from scratch:

```bash
# Smoke test (~30 s)
python ml/train_advanced.py --smoke

# Full production retrain (50 years, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Multi-symbol backtest (XAU + BTC + ETH)
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

To verify the model is loaded correctly:

```bash
curl http://localhost:8000/api/ml/accuracy
# {"model_id":"advanced_oos","accuracy":0.664,"oos_n":1260,"gate_passed":true,...}
```

## 9. Online learning (optional)

Enable incremental model updates that keep the model current without a full retrain:

```env
# In .env
ML_HOURLY_ENABLED=true
ML_SYMBOLS=XAU_USD
ONLINE_LEARNER_PERSIST=true
ONLINE_LEARNER_DIR=ml/saved_models
```

When enabled:
- **Every hour:** `SklearnOnlineLearner` receives the last 24 bars and calls `partial_fit()`.
- **Daily at 00:05 UTC:** EWC regime-adaptation loop adjusts model plasticity based on detected market regime (volatile / ranging / trending).
- Learner state is persisted to `ml/saved_models/online_learner_{symbol}.pkl` and reloaded at startup.

---

## Troubleshooting

**App exits immediately with validation errors:**

The startup validator prints exactly what is missing. Common causes:
- `SECURITY_JWT_SECRET` not set or shorter than 32 characters
- `SECURITY_JWT_SECRET` still contains `CHANGE_ME`

**`ModuleNotFoundError` on startup:**

```bash
pip install -r requirements.txt
```

If using CI requirements: `pip install -r requirements-ci.txt` — this excludes heavy deps (ta-lib, TensorFlow, MetaTrader5).

**Database migration errors:**

```bash
alembic current    # show current revision
alembic upgrade head  # apply all pending migrations
```

**Redis connection refused:**

Redis is optional. The app falls back to in-memory rate limiting and caching automatically. Set `REDIS_URL` only if you have Redis running.

**OANDA connection errors:**

```bash
python scripts/validate_oanda.py
```

This tests API key validity, account reachability, and XAU_USD pricing availability.
