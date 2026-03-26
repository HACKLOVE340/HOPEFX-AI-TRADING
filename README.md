# HOPEFX-AI-TRADING

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
# Swagger UI → http://localhost:8000/docs
```

---

<div align="center">

<img src="docs/assets/banner.svg" alt="HOPEFX — Institutional-Grade AI Gold Trading Platform" width="100%"/>

<br/>

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-FFD700.svg?style=for-the-badge&logo=python&logoColor=black)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-00c853.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/HACKLOVE340/HOPEFX-AI-TRADING/branch/main/graph/badge.svg)](https://codecov.io/gh/HACKLOVE340/HOPEFX-AI-TRADING)
[![Paper Trading](https://img.shields.io/badge/Paper_Trading-Active-orange.svg?style=for-the-badge)](docs/)
[![Event-Driven](https://img.shields.io/badge/Architecture-Event--Driven-00e5ff.svg?style=for-the-badge)](docs/)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen.svg?style=for-the-badge)](CONTRIBUTING.md)

<br/>

> **Institutional-grade AI gold/forex trading platform.**  
> Event-driven core · 68% OOS ML edge · Macro-aware inference · FIX low-latency · TCA/VaR analytics · One-command Helm deploy · 100% MIT

</div>

---

## ML Performance — Production Model

> **The headline number is the advanced model. The basic model is a baseline comparison only.**

| Model | OOS Accuracy | p-value | Features | Status |
|---|---|---|---|---|
| **advanced_oos.pkl** ← **production** | **68.0%** | **p=0.0000** | 122 stationary | ✅ Active |
| xgb_macro.pkl (fallback) | 50.3% | p=0.720 | 65 stationary | ⚠️ Fallback only |
| rf_macro.pkl (fallback) | 50.7% | p=0.612 | 65 stationary | ⚠️ Fallback only |

**OOS period**: 2023-03-22 → 2026-03-24 (756 bars, 3-year held-out, never seen during training)  
**Abstain rate**: 27.5% of bars filtered (model only signals on high-confidence bars)  
**Significance**: p=0.0000 — the null hypothesis (accuracy ≤ 50%) is rejected at any conventional threshold

The 68% result is the only number that matters for live deployment decisions. The basic model at 50.3% has no demonstrated edge and is kept only as a safe fallback if the advanced model fails to load.

---

## Backtest Results — XAUUSD (Real GC=F Data)

> **Data**: 5 years of real GC=F daily bars (Yahoo Finance, 2021-03-26 → 2026-03-24)  
> **Sizing**: 10% equity per trade, ATR-based stop (1.5×) and take-profit (2.5×), 35 bps commission + 5 bps slippage

![Equity Curve](examples/results/equity_curve.png)

| Metric | Value | Note |
|---|---|---|
| Backtest period | 2024-10-02 – 2026-03-24 | Real GC=F futures prices |
| Initial capital | $100,000 | |
| Final equity | $105,516 | |
| Total return | +5.52% | |
| Trades | 45 | ⚠️ Too few for Sharpe significance |
| Win rate | 57.8% | |
| Profit factor | 2.28 | |
| Max drawdown | −0.88% | |
| Sharpe ratio | 1.82 | SE ≈ ±0.54 at N=45 — not statistically robust |
| Calmar ratio | 6.26 | |
| ML accuracy (test set) | 53.9% | |

> ⚠️ **N=45 trades is insufficient for Sharpe significance** (SE ≈ ±0.54, need ~170 trades for SE ≤ ±0.3).  
> The credible performance number is the **OOS accuracy: 68.0%, p=0.0000** — not the Sharpe.  
> Do not commit live capital until 30+ days of OANDA paper trading is complete.

**Reproduce:**
```bash
python examples/generate_proof_artifacts.py
```

**Retrain production model:**
```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

---

## Current Status

| Area | Status | Detail |
|---|---|---|
| ML Signal | ✅ Edge proven | 68% OOS, p=0.0000, 122 features, macro wired to inference |
| Execution | ✅ Wired | FIX adapter + circuit breaker, paper broker connected |
| Risk Stack | ✅ Production | RiskManager, CVaR gate, kill switch, VaR/Sharpe analytics |
| Backtesting | ✅ Real data | GC=F 5Y, N=45 trades, full metric suite |
| Macro Inference | ✅ Fixed | MacroStore bootstraps at startup, macro_df passed to predictor |
| Paper Trading | ⏳ Not started | **Start now** — 30-day OANDA paper run required before live capital |
| Live Capital | ❌ Not ready | Requires 30-day paper run with real fill data |

---

## Architecture

```
app.py                      FastAPI server — 22 routers, lifespan startup
├── api/                    REST endpoints (trading, admin, backtesting, ML)
├── auth/                   JWT auth, RBAC, 2FA
├── brokers/                OANDA (region-routed), MT5, Alpaca, IB, Binance, CCXT, paper
├── strategies/             10 built-in strategies + StrategyBrain orchestrator
├── execution/              FIX adapter, OMS, trade executor, position tracker
├── risk/                   RiskManager, circuit breakers, VaR, CVaR, FIA compliance
│
├── core/
│   ├── component_registry.py   Dependency-ordered startup registry
│   ├── startup_factories.py    Component factories (MacroStore, signal engine, etc.)
│   ├── signal_engine.py        Strategy → ML → risk → order pipeline
│   └── position_reconciler.py
│
├── ml/
│   ├── advanced_features.py    122-feature pipeline (COT proxies, regime, macro)
│   ├── train_advanced.py       Advanced model training with OOS evaluation
│   ├── live_inference.py       AdvancedModelPredictor with Redis feature cache
│   ├── macro_store.py          Daily macro series → hourly alignment
│   ├── macro_bootstrap.py      yfinance fetch + daily refresh scheduler
│   └── saved_models/
│       ├── advanced_oos.pkl    ← PRODUCTION MODEL (68% OOS, 122 features)
│       └── xgb_macro.pkl       ← fallback (50% OOS, 65 features, no close_lag_N)
│
├── notifications/
│   ├── discord_bot.py          Community signal bot (rich embeds, rate-limited)
│   ├── telegram_bot.py         Telegram alerts
│   └── alert_engine.py         Multi-channel alert routing
│
├── monitoring/
│   ├── sentry_config.py        Sentry: error tracking + performance + ML fallback alerts
│   └── prometheus.yml          Scrape config
│
├── data/
│   ├── scheduler.py            Daily OANDA/yfinance fetch
│   ├── macro/                  DXY, VIX, US10Y, US2Y, SPX CSVs (bootstrapped at startup)
│   └── XAU_USD_H1.csv          11,457 H1 bars, 2024-03-24 to 2026-03-24
│
├── research/                   LSTM/Transformer/TCN, online learning, drift detection
│                               (research-only — see research/README.md for integration path)
│
├── grafana/                    4 dashboards, 27 panels
├── docker-compose.yml          app + postgres + redis + prometheus + grafana
├── helm/hopefx/                Kubernetes Helm chart (HPA, PDB, secrets)
├── k6/load_tests.js            k6: smoke/load/soak/spike/stress/breakpoint scenarios
└── locust/load_tests.py        Locust: PublicUser, MLResearcher, AuthenticatedTrader
```

---

## Quick Start

### Prerequisites
- Python 3.10+, pip, Git
- Redis (optional — app falls back gracefully)
- Docker + Docker Compose (for full stack with monitoring)

### Install and run

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Full stack (monitoring included)

```bash
docker-compose up -d
# App:        http://localhost:8000/docs
# Grafana:    http://localhost:3000
# Prometheus: http://localhost:9090
```

### Kubernetes

```bash
helm upgrade --install hopefx helm/hopefx/ \
  --set image.tag=latest \
  --set secrets.databaseUrl="postgresql://..." \
  --set secrets.redisUrl="redis://..."
```

### Start OANDA paper trading (do this now)

```bash
# 1. Get a free OANDA practice account at https://www.oanda.com/register/
# 2. Set credentials in .env:
#    BROKER_OANDA_TOKEN=your-practice-api-key
#    BROKER_OANDA_ACCOUNT=your-account-id
#    OANDA_ENVIRONMENT=practice
#    OANDA_REGION=us   # or eu / sg
# 3. Start the server — signal engine auto-starts
uvicorn app:app --host 0.0.0.0 --port 8000
# The 30-day clock starts now.
```

### Retrain models

```bash
# Production model (122 features, 50-year data, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Basic model (65 features, macro walk-forward)
python ml/train_with_macro.py --years 50 --oos-years 3

# Fetch latest XAUUSD H1 bars
python -m data.scheduler
```

---

## Key Features

### ML & Signal Generation
- **Production model**: `advanced_oos.pkl` — 122 stationary features, 68.0% OOS accuracy (p=0.0000)
- **Feature set**: technical indicators + COT/central-bank buying proxies + regime features (Hurst, ADX) + macro cross-asset (DXY, VIX, yields, SPX)
- **Macro inference**: `MacroStore` bootstraps DXY/VIX/yield/SPX at startup; `macro_df` passed to every `predict_proba()` call
- **Abstain filter**: model abstains on 27.5% of bars (low-confidence signals filtered out)
- **Fallback safety**: if `advanced_oos.pkl` fails to load, CRITICAL log + Sentry fatal alert + Discord alert fire immediately; fallback model has no `close_lag_N` features
- **Feature cache**: Redis-backed (1-min TTL) prevents recomputing 122 features on every concurrent tick

### Execution
- **FIX 4.4 adapter** with circuit breaker and heartbeat monitoring
- **Smart Order Router** — latency-aware broker selection with failover
- **OANDA region routing** — `us` / `eu` / `sg` via `OANDA_REGION` env var
- **Paper Trading Broker** — realistic fills, slippage, commission
- **Live brokers** — OANDA, MT5, Alpaca, Interactive Brokers, Binance, CCXT (50+ exchanges)

### Risk Management
- **RiskManager** — Kelly criterion sizing, drawdown limits, daily loss limits
- **CVaR pre-trade gate** — blocks orders when CVaR limit is breached
- **Kill Switch** — instant halt via API, file flag, env var, or event bus; persists across restarts
- **Circuit Breakers** — automatic trading suspension on anomalies
- **VaR / CVaR** — historical, parametric, Monte Carlo, EWMA methods

### Observability
- **Prometheus** — `/metrics` endpoint, 41 registered metrics, 15s sync
- **Grafana** — 4 dashboards, 27 panels (Trading Performance, ML Metrics, Broker Connectivity, System Health)
- **Sentry** — error tracking + performance monitoring + ML fallback fatal alerts; FastAPI/SQLAlchemy/Redis/aiohttp integrations
- **Discord bot** — community signal channel with rich embeds (colour-coded direction, confidence bar, R/R ratio, fallback warning)

### Load Testing
- **k6**: smoke / load / soak / spike / stress / breakpoint scenarios; custom metrics for order, signal, and ML latency
- **Locust**: PublicUser, MLResearcher, AuthenticatedTrader user classes; CSV/HTML report output

---

## API Endpoints

| Group | Prefix | Auth |
|---|---|---|
| Auth | `/auth` | Public |
| Trading | `/api/trading` | JWT (trader role) |
| ML | `/api/ml` | JWT |
| Signals | `/api/signals` | JWT |
| Risk | `/api/risk` | JWT |
| Backtesting | `/api/backtest` | JWT |
| Kill Switch | `/api/kill-switch` | JWT (admin) |
| Admin | `/admin` | JWT (admin) |
| WebSocket | `/ws` | JWT |
| Alerts | `/api/alerts` | JWT |
| Explainability | `/api/explainability` | JWT |
| Transparency | `/api/transparency` | JWT |
| No-Code Builder | `/api/nocode` | JWT |
| Replay | `/api/replay` | JWT |
| Metrics | `/metrics` | Internal |
| Health | `/health` | Public |
| Docs | `/docs` | Public |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | SQLite | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `SECURITY_JWT_SECRET` | dev default | JWT signing secret — **change in production** |
| `BROKER_OANDA_TOKEN` | — | OANDA API key |
| `BROKER_OANDA_ACCOUNT` | — | OANDA account ID |
| `OANDA_ENVIRONMENT` | `practice` | `practice` or `live` |
| `OANDA_REGION` | `us` | `us` / `eu` / `sg` |
| `SIGNAL_ENGINE_SYMBOLS` | `XAUUSD` | Comma-separated symbols |
| `SIGNAL_ENGINE_AUTO_TRADE` | `false` | Enable auto-execution |
| `MACRO_DATA_DIR` | `data/macro` | Directory for macro CSV files |
| `SENTRY_DSN` | — | Sentry project DSN |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Performance monitoring sample rate |
| `DISCORD_WEBHOOK_URL` | — | Discord signals channel webhook |
| `DISCORD_SIGNAL_COOLDOWN_SECONDS` | `300` | Min seconds between Discord posts per symbol |
| `PAPER_TRADING_BALANCE` | `10000` | Starting balance for paper broker |
| `RISK_MAX_POSITION_SIZE_PCT` | `0.02` | Max position as % of equity |
| `RISK_MAX_DRAWDOWN_PCT` | `0.10` | Max drawdown before halt |

The app starts without any `.env` — all variables have safe defaults for local development.

---

## Testing

```bash
pip install pytest pytest-asyncio pytest-cov

# Full suite
pytest tests/ --ignore=tests/integration/test_redis.py -q

# Critical suites
pytest tests/test_auth_gates.py -q        # RBAC enforcement
pytest tests/test_smoke_critical.py -q    # Module import smoke
pytest tests/unit/ -q                     # Per-module unit tests
pytest tests/integration/ -q             # API + broker integration
```

---

## Monitoring

Four Grafana dashboards provisioned automatically on `docker-compose up`:

| Dashboard | Key Metrics |
|---|---|
| Trading Performance | Equity curve, open positions, daily P&L, win rate, drawdown |
| ML Model Metrics | Signal confidence, model accuracy, market regime, drift score |
| Broker Connectivity | Broker status, round-trip latency, rejection rate, FIX heartbeat |
| System Health | API request rate, error rate, p95 latency, CPU, memory, Redis |

---

## Security

- Never commit credentials — use `.env` (gitignored)
- `SECURITY_JWT_SECRET` must be a strong random value in production
- All API keys encrypted at rest via Fernet (`config/config_manager.py`)
- JWT tokens with configurable expiry; 2FA supported
- AML gate and compliance checks on all order flow
- Passwords hashed with bcrypt (SHA-256 pre-hash for inputs >72 bytes)

See [SECURITY.md](./SECURITY.md) for full guidelines.

---

## Documentation

| Document | Description |
|---|---|
| [CRITICAL_FLAWS.md](./CRITICAL_FLAWS.md) | Audit findings, fix history, open items |
| [ANALYSIS_AND_ROADMAP.md](./ANALYSIS_AND_ROADMAP.md) | Architecture analysis and next steps |
| [INSTALLATION.md](./INSTALLATION.md) | Full installation guide |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Production deployment guide |
| [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) | Pre-launch checklist |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](./SECURITY.md) | Security best practices |
| [CHANGELOG.md](./CHANGELOG.md) | Version history |
| [research/README.md](./research/README.md) | Research pipeline integration path |

---

## Contributing

1. Fork → feature branch → changes + tests → `pytest tests/ -q` (all pass) → PR
2. See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines.

---

## Community

<div align="center">

[![Discord](https://img.shields.io/badge/Discord-Join%20Community-7289da?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/hopefx)
[![Telegram](https://img.shields.io/badge/Telegram-Join%20Channel-26a5e4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/hopefx)
[![Twitter](https://img.shields.io/badge/Twitter-Follow%20Us-1da1f2?style=for-the-badge&logo=twitter&logoColor=white)](https://twitter.com/HOPEFX_Trading)

</div>

---

## License

MIT — see [LICENSE](./LICENSE). Free for personal and commercial use.

---

<div align="center">

**[Get Started](./INSTALLATION.md) · [API Docs](http://localhost:8000/docs) · [Discord](https://discord.gg/hopefx) · [Star on GitHub](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING)**

</div>
