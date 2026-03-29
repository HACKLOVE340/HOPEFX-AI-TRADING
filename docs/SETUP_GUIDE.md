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

# Subscription license key — obtain from hopefx.com/pricing or trial-request issue
# Without this, all trading endpoints return 403 Subscription Required
HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX

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

The `validate` command checks every required secret and reports exactly what is missing
or invalid. Fix all reported issues before proceeding to step 3.

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

# Multi-symbol backtest (7 symbols — XAU, BTC, ETH, EUR/USD, GBP/USD, Silver, Oil)
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

To verify the model is loaded correctly:

```bash
curl http://localhost:8000/api/ml/accuracy
# {"model_id":"advanced_oos","accuracy":0.664,"oos_n":1260,"gate_passed":true,...}

curl http://localhost:8000/api/ml/health
# {"status":"ok","feature_count":176,"model_loaded":true,...}
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

---

## Subscription Validation

HOPEFX requires a valid license key to access trading endpoints. Without one, the
application starts but all `/api/trading/`, `/api/signals/`, and `/api/ml/` endpoints
return `403 Subscription Required`. The `/health`, `/docs`, and `/metrics` endpoints
remain accessible without a key.

### Step 1 — Obtain a license key

Subscribe at [hopefx.com/pricing](https://hopefx.com/pricing) or request a 14-day
trial via GitHub Issues (label: `trial-request`). Your license key is emailed on
successful payment in the format:

```
HOPEFX-PRO-A7B9C2D4-X8Y2
```

### Step 2 — Add the key to `.env`

```bash
HOPEFX_LICENSE_KEY=HOPEFX-PRO-A7B9C2D4-X8Y2
```

### Step 3 — Validate before starting

```bash
python scripts/manage_secrets.py validate
```

Expected output:
```
✓ SECURITY_JWT_SECRET: set (48 chars)
✓ HOPEFX_LICENSE_KEY: valid (plan=professional, expires=2026-08-14)
✓ CONFIG_ENCRYPTION_KEY: set
✓ HOPEFX_KILL_SWITCH_TOKEN: set
All required secrets are valid.
```

If validation fails, the output shows exactly which key is missing or invalid.

### Step 4 — Confirm at runtime

After starting the app, confirm the license is active:

```bash
curl http://localhost:8000/api/monetization/subscription/me \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "plan": "professional",
  "status": "active",
  "expires_at": "2026-08-14T00:00:00Z",
  "features": ["signals", "ml_predict", "backtesting_10yr", "api_access", "social_trading"]
}
```

### License Key Renewal

Keys are valid for 30 days (monthly billing) or 365 days (annual billing). The app
checks key validity on startup and every 24 hours at runtime. When a key is within
7 days of expiry, a warning is logged:

```
WARNING: License key expires in 5 days. Renew at hopefx.com/billing
```

After expiry, trading endpoints return `403 Subscription Required` until a new key
is activated. Update `.env` with the new key and restart the app.

---

## Subscription-Gated Features

| Feature | Trial | Starter | Professional | Enterprise | Elite |
|---------|-------|---------|-------------|------------|-------|
| Paper trading | Limited (50 trades) | Yes | Yes | Yes | Yes |
| Live trading | No | 1 broker | 3 brokers | Unlimited | Unlimited |
| Signals (XAUUSD) | No | Yes | Yes | Yes | Yes |
| Multi-symbol signals | No | No | Yes | Yes | Yes |
| ML predictions | No | No | Yes | Yes | Yes |
| Backtesting (1 year) | No | Yes | Yes | Yes | Yes |
| Backtesting (10 years) | No | No | Yes | Yes | Yes |
| Backtesting (50 years) | No | No | No | Yes | Yes |
| Prop firm mode | No | No | Yes | Yes | Yes |
| Full API access (108 endpoints) | No | No | Yes | Yes | Yes |
| Social trading | No | No | Yes | Yes | Yes |
| Grafana dashboards | No | No | Yes | Yes | Yes |
| News RAG integration | No | No | No | Yes | Yes |
| Online learning | No | No | No | No | Yes |
| Model retraining | No | No | No | No | Yes |
| White-label | No | No | No | No | Yes |

Attempting to use a feature above your plan returns:
```json
{"error": "PLAN_LIMIT_EXCEEDED", "required_plan": "professional", "current_plan": "starter"}
```

See [MONETIZATION.md](MONETIZATION.md) for the full feature matrix and pricing.
