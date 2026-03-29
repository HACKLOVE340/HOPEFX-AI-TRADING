# HOPEFX — Deployment Infrastructure

> Last updated: 2026-07-14

This document covers the production deployment stack for HOPEFX AI Trading:
environment variables, broker wiring, monitoring, feature flags, and the
30-day paper trading run procedure.

---

## Quick Start

```bash
# 1. Copy and fill environment variables
cp .env.example .env
# Edit .env — minimum required fields marked REQUIRED below

# 2. Start with Docker Compose (includes Prometheus + Grafana)
docker-compose up -d

# 3. Verify health
curl http://localhost:8000/health
curl http://localhost:8000/api/status/paper-trading
```

---

## Environment Variables

All variables are documented in `.env.example`. The table below covers the
production-critical ones. The app starts without any `.env` (all defaults are
safe), but the following must be set for production use.

### Required for Live/Paper Trading

| Variable | Example | Notes |
|----------|---------|-------|
| `BROKER_TYPE` | `oanda` | `paper` (default) or `oanda` |
| `BROKER_OANDA_TOKEN` | `abc123...` | OANDA practice or live API key |
| `BROKER_OANDA_ACCOUNT` | `001-001-...` | OANDA account ID |
| `OANDA_ENVIRONMENT` | `practice` | `practice` or `live` |
| `OANDA_REGION` | `us` | `us`, `eu`, or `sg` |

### Required for Production Monitoring

| Variable | Example | Notes |
|----------|---------|-------|
| `SENTRY_DSN` | `https://abc@sentry.io/123` | Error tracking — app runs without it but errors are silent |
| `SENTRY_ENVIRONMENT` | `production` | Shown in Sentry issue grouping |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | 10% of transactions traced (reduce in high-traffic) |

### Required for Auth

| Variable | Example | Notes |
|----------|---------|-------|
| `SECRET_KEY` | 64-char random hex | JWT signing key — generate with `openssl rand -hex 32` |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Falls back to SQLite if unset |

### Optional but Recommended

| Variable | Default | Notes |
|----------|---------|-------|
| `INITIAL_BALANCE` | `100000` | Paper trading starting balance |
| `PAPER_TRADING_BALANCE` | `100000` | Alias for INITIAL_BALANCE |
| `LOG_LEVEL` | `INFO` | `DEBUG` for development |
| `APP_ENV` | `development` | `production` enables stricter validation |

---

## Broker Selection

`init_broker()` in `core/startup_factories.py` selects the broker by priority:

```
1. BROKER_TYPE=oanda  AND  BROKER_OANDA_TOKEN set
   → AsyncOANDAConnector (practice or live per OANDA_ENVIRONMENT)
   → 30-day paper trading clock starts on first successful connection

2. BROKER_TYPE=paper  (default)
   → PaperTradingBroker (in-memory simulation, no external calls)
```

If `BROKER_TYPE=oanda` but credentials are missing, the server logs a warning
and falls back to `PaperTradingBroker`. The app always starts.

---

## 30-Day OANDA Paper Trading Run

### Starting the Clock

```bash
# .env
BROKER_TYPE=oanda
BROKER_OANDA_TOKEN=your-practice-api-key
BROKER_OANDA_ACCOUNT=your-account-id
OANDA_ENVIRONMENT=practice
```

On first successful OANDA connection, `data/oanda_paper_start.json` is written:

```json
{
  "account_id": "12345678...",
  "environment": "practice",
  "started_utc": "2026-07-14T10:00:00+00:00",
  "target_days": 30,
  "note": "30-day paper trading run started."
}
```

The clock survives restarts — subsequent connections do NOT reset it.

### Checking Clock Status

```bash
curl http://localhost:8000/api/status/paper-trading
```

Response:
```json
{
  "started": true,
  "started_utc": "2026-07-14T10:00:00+00:00",
  "elapsed_days": 5.3,
  "remaining_days": 24.7,
  "target_days": 30,
  "complete": false,
  "environment": "practice",
  "account_id": "12345678...",
  "note": "5.3 days elapsed, 24.7 days remaining."
}
```

### After 30 Days

1. Review `examples/results/performance.json` — updated with real fill data
2. Enable Phase 2 anomaly weighting: `FEATURE_ANOMALY_WEIGHTING=true`
3. After 90 days + 500 fills: `FEATURE_ONLINE_LEARNING=true`

---

## Feature Flags

All 57 feature flags are documented in `.env.example`. The canonical registry
is `config/feature_flags.py`. Flags are read at startup — restart required
to apply changes.

### Research Pipeline Flags (Phases 1–4)

| Flag | Default | Enable When |
|------|---------|-------------|
| `FEATURE_MTF_FUSION` | `true` | Always on — H4/D1 regime features |
| `FEATURE_ANOMALY_WEIGHTING` | `false` | After 30-day paper run |
| `FEATURE_ONLINE_LEARNING` | `false` | After 90-day paper run + 500 fills |
| `FEATURE_DEEP_ENSEMBLE` | `false` | After GPU training + OOS >= 70% |

### Trading Mode Flags

| Flag | Default | Notes |
|------|---------|-------|
| `FEATURE_PAPER_TRADING` | `true` | Always keep true until live validated |
| `FEATURE_LIVE_TRADING` | `false` | Set true only after 30-day paper run |
| `FEATURE_BACKTESTING` | `true` | Required for /api/backtest endpoints |

---

## Monitoring Stack

### Prometheus + Grafana (Docker Compose)

```bash
docker-compose up -d prometheus grafana
```

- Prometheus scrapes `GET /metrics` every 15s
- Grafana at `http://localhost:3000` (admin / see `GF_SECURITY_ADMIN_PASSWORD`)
- 4 dashboards pre-provisioned: trading performance, ML metrics, system health, order flow

All 21 Grafana panel metric names are registered in `infrastructure/metrics.py`.
Zero "No data" panels on a running instance.

### Sentry

Set `SENTRY_DSN` in `.env`. The SDK initialises automatically at startup via
`api/platform.py::init_sentry()` → `monitoring/sentry_config.py::init_sentry()`.

Features enabled:
- FastAPI, SQLAlchemy, Redis, aiohttp integrations
- `before_send` hook scrubs 15 sensitive field names (password, api_key, token, etc.)
- `capture_ml_fallback_event()` fires a fatal-level Sentry issue when the ML
  model falls back to the baseline — actionable alert for model degradation

Without `SENTRY_DSN`, `init_sentry()` returns `False` silently. The app runs.

---

## Backtest Cost Model

The backtest engine (`backtest/engine.py`) uses production-realistic costs:

| Parameter | Value | Notes |
|-----------|-------|-------|
| Commission | $7 round-trip | Realistic XAUUSD CFD |
| Slippage (gold) | 3 pips × $0.10 = $0.30 | OANDA XAU_USD practice spread |
| Slippage (forex/crypto) | 3 pips × $0.01 = $0.03 | Tight exchange spread |
| Position sizing | Quarter-Kelly | 1% risk/trade, capped by available cash |
| R:R filter | min 1.5:1 | Signals below threshold rejected |

### Sharpe Reporting

Sharpe is reported at **trade level** (corrected):
```
Sharpe = mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days)
SE     = 1 / sqrt(2 * (N - 1))
```

| N trades | SE | Interpretation |
|----------|----|----------------|
| 48 | ±0.21 | Not robust — cite OOS accuracy instead |
| 250 | ±0.045 | Minimum acceptable |
| 600 | ±0.029 | Target — statistically robust |

> **Deprecated:** Bar-level Sharpe (equity.pct_change()) was previously
> reported as 4.68. This figure is inflated by flat no-trade days and must
> not be used. The corrected trade-level Sharpe is **1.52** at N=48.

---

## Docker Compose Services

| Service | Port | Description |
|---------|------|-------------|
| `app` | 8000 | FastAPI application |
| `postgres` | 5432 | PostgreSQL database |
| `redis` | 6379 | Cache + WebSocket pub/sub |
| `prometheus` | 9090 | Metrics scraper |
| `grafana` | 3000 | Dashboards |
| `celery` | — | Background task worker |

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Run database migrations
docker-compose exec app alembic upgrade head

# Run tests inside container
docker-compose exec app pytest tests/ -q
```

---

## Health Checks

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /health` | None | Liveness check — returns 200 if app is up |
| `GET /api/status/json` | None | Full system status (DB, Redis, broker, ML) |
| `GET /api/status/paper-trading` | None | 30-day paper trading clock status |
| `GET /metrics` | None | Prometheus metrics (text/plain) |

---

## Production Checklist

Before switching `FEATURE_LIVE_TRADING=true`:

- [ ] 30-day OANDA paper trading run complete (`complete: true` in `/api/status/paper-trading`)
- [ ] `SENTRY_DSN` set and verified (check Sentry project for test event)
- [ ] `SECRET_KEY` is a 64-char random value (not the default)
- [ ] `DATABASE_URL` points to a persistent PostgreSQL instance (not SQLite)
- [ ] `APP_ENV=production` set
- [ ] `FEATURE_LIVE_TRADING=false` until paper run complete
- [ ] Kill switch tested: `POST /api/kill-switch/activate` returns 200
- [ ] Grafana dashboards show live data (no "No data" panels)
- [ ] Prometheus scrape interval confirmed at 15s
- [ ] `data/oanda_paper_start.json` backed up
