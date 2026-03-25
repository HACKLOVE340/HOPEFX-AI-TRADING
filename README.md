# HOPEFX-AI-TRADING

## START HERE

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app:app --host 0.0.0.0 --port 8000

# API docs
open http://localhost:8000/docs
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
> Event-driven core · Agentic LLM · Transformer-Diffusion forecasting · Deep RL · FIX low-latency · TCA/VaR analytics · One-command Helm deploy · 100% MIT

</div>

---

## Backtest Results — XAUUSD Strategy

> **Data**: 5 years of real GC=F daily bars (Yahoo Finance, 2021-03-26 → 2026-03-24)
> **Models**: RandomForestClassifier + XGBoost, macro features (DXY, VIX, yields, SPX)
> **Sizing**: 10% equity per trade, ATR-based stop (1.5×) and take-profit (2.5×), 35 bps commission + 5 bps slippage

![Equity Curve](examples/results/equity_curve.png)

### Real-Data Backtest (GC=F, 5 years)

| Metric | Value |
|---|---|
| Data source | Yahoo Finance GC=F (real futures prices) |
| Backtest period | 2024-10-14 – 2026-03-24 |
| Initial capital | $100,000 |
| Final equity | $106,167 |
| Total return | +6.17% |
| Trades | 31 |
| Win rate | 67.7% |
| Profit factor | 3.553 |
| Max drawdown | −0.83% |
| ML accuracy (test) | 52.9% |
| ML up-precision | 60.2% |

> ⚠️ **31 trades is still too few for statistical significance.** The Sharpe and win rate are
> not reliable at this sample size. The pipeline now runs on real data end-to-end.
> Do not trade live capital until p<0.05 is demonstrated on a held-out OOS period.

### Model Metrics (50-year macro walk-forward, real GC=F daily)

| Model | WF Accuracy | WF p-value | OOS Accuracy (3yr) | OOS p-value | Training data |
|---|---|---|---|---|---|
| XGBoost | 50.3% ± 1.8% | 0.720 | 50.5% | 0.400 | 5,609 bars, GC=F + macro |
| RandomForest | 50.7% ± 2.6% | 0.612 | 48.4% | 0.818 | 5,609 bars, GC=F + macro |

> **Neither model shows p<0.05 edge above chance on the held-out OOS period.**
> Walk-forward CV accuracy is near chance (50%). The 3-year OOS period (2023–2026)
> is the only valid performance estimate — it was never seen during training.
> Research literature consistently shows 52–58% as a realistic ceiling on daily bars.
> Do not trade live capital on these results.

**Reproduce the real-data backtest:**
```bash
python examples/generate_proof_artifacts.py
```

**Retrain on 50 years of data with strict OOS validation:**
```bash
# Full 50-year daily history with macro features + 3-year held-out OOS
python ml/train_with_macro.py --years 50 --oos-years 3

# Quick smoke test (10 years, no macro)
python ml/train_with_macro.py --years 10 --no-macro
```

**Legacy retrain (H1 bars only):**
```bash
python -m data.scheduler          # fetch latest XAUUSD H1 bars
python ml/run_training.py --symbol GC=F --period 2y --models random_forest,xgboost
```

**Full walkthrough**: [`examples/end_to_end.ipynb`](examples/end_to_end.ipynb)

---

## What Changed (current)

| Fix | Detail |
|---|---|
| **Test suite green** | 2435 passed, 0 failed — bcrypt, auth, smoke, capsys, JWT secret isolation all fixed |
| **Deprecated entry points deleted** | `main.py`, `main_ultimate.py`, `main_mcc_wrapper.py`, `main_ultimate_integrated.py` removed |
| **startup_event() refactored** | 428 lines → 78 lines; all factories in `core/startup_factories.py` |
| **Email: SendGrid primary** | `core/email_service.py` uses SendGrid API first, SMTP fallback, dev log last |
| **Type hints complete** | `core/signal_engine.py` fully annotated; coverage restored to ≥86% |
| **bcrypt 4.x compatibility** | Downgraded to 4.0.1; SHA-256 pre-hash for passwords >72 bytes |
| **JWT secret isolation** | Test modules pin their own secret in fixtures; no cross-contamination |
| **Event bus /tmp fix** | `MemoryMappedEventStore` test uses 1 MB instead of 1 GB pre-allocation |
| **Data scheduler wired** | `DataScheduler` starts automatically at app startup |
| **Models retrained** | XGBoost + RandomForest trained on current GC=F data |
| **Prometheus metrics** | `/metrics` endpoint live with 15s sync loop, 41 registered metrics |
| **Grafana dashboards** | 4 dashboards, 27 panels — all metric names verified |

---

## Key Features

### Machine Learning & AI
- **XGBoost** and **RandomForest** classifiers with 66 engineered features
- **LSTM Neural Networks** for time-series price prediction (optional, requires TensorFlow)
- **Ensemble methods** for multi-model signal fusion
- **Walk-forward validation** — no look-ahead bias in train/test splits
- **SHAP explainability** — feature importance and counterfactual explanations via `/api/explainability`
- **Model drift detection** — `hopefx_model_drift_score` metric tracked in Prometheus
- **Automated retraining pipeline** — `ml/run_training.py` with hyperparameter tuning via Optuna

### Trading Execution
- **FIX 4.4 adapter** — `execution/fix_adapter.py`, quickfix backend with pyfixmsg fallback
- **Smart Order Router** — `brokers/smart_router.py`, latency-aware broker selection with failover
- **Paper Trading Broker** — full simulation with realistic fills, slippage, and commission
- **Live brokers** — OANDA, MT5, Alpaca, Interactive Brokers, Binance, CCXT (50+ exchanges)
- **Order Management System** — `execution/oms.py`, async order lifecycle tracking
- **Position Tracker** — `execution/position_tracker.py`, real-time P&L and exposure
- **Trade Executor** — `execution/trade_executor.py`, risk-gated order submission

### Risk Management
- **RiskManager** — position sizing, drawdown limits, daily loss limits, correlation penalties
- **Kill Switch** — instant halt via API, file flag, env var, or event bus; authenticated deactivation
- **Circuit Breakers** — `risk/circuit_breakers.py`, automatic trading suspension on anomalies
- **VaR / CVaR** — `analytics/risk.py`, 1-day Value-at-Risk
- **FIA Compliance** — `risk/fia_compliance.py`, position and reporting rules
- **Self-Trade Prevention** — `risk/self_trade_prevention.py`

### Monitoring & Observability
- **Prometheus** — `/metrics` endpoint with 41 registered metrics, 15s sync cadence
- **Grafana** — 4 dashboards (Trading Performance, ML Model Metrics, Broker Connectivity, System Health), 27 panels total, all expressions verified
- **Structured logging** — `infrastructure/logging.py`, JSON-formatted with correlation IDs
- **Health checks** — `infrastructure/health.py`, component-level status at `/health`

### Data Pipeline
- **DataScheduler** — `data/scheduler.py`, daily OANDA H1 fetch with yfinance fallback, wired to app startup
- **DataValidator** — `data/validator.py`, price sanity bounds, gap detection, stale data alerts
- **11,457 H1 bars** — `data/XAU_USD_H1.csv`, XAUUSD 2024-03-24 to 2026-03-24
- **Real-Time Price Engine** — `data/real_time_price_engine.py`, WebSocket + REST feed

### Additional Modules
- **No-Code Strategy Builder** — `nocode/builder.py`, plain-English strategy parsing, REST API at `/api/nocode`
- **Chart Replay Engine** — `replay/engine.py`, historical bar-by-bar replay with practice orders, REST API at `/api/replay`
- **AI Explainability** — `explainability/explainer.py`, SHAP-style feature attribution, REST API at `/api/explainability`
- **Execution Transparency** — `transparency/engine.py`, slippage tracking, fill quality reports, REST API at `/api/transparency`
- **Research Notebooks** — `research/`, in-app notebook engine at `/api/research`

### Built-in Strategies (10)

| Strategy | File | Type |
|---|---|---|
| Moving Average Crossover | `strategies/ma_crossover.py` | Trend |
| EMA Crossover | `strategies/ema_crossover.py` | Trend |
| Bollinger Bands | `strategies/bollinger_bands.py` | Mean Reversion |
| RSI | `strategies/rsi_strategy.py` | Momentum |
| MACD | `strategies/macd_strategy.py` | Trend/Momentum |
| Breakout | `strategies/breakout.py` | Breakout |
| Mean Reversion | `strategies/mean_reversion.py` | Mean Reversion |
| Stochastic | `strategies/stochastic.py` | Momentum |
| SMC/ICT Smart Money | `strategies/smc_ict.py` | Institutional |
| ITS-8-OS | `strategies/its_8_os.py` | Proprietary |

### Social & Copy Trading
- Proportional copy sizing with `RiskLimitExceeded` enforcement
- Strategy Marketplace — buy/sell strategy subscriptions
- Leaderboard — composite score ranking (return × Sharpe × log(followers))
- Teams module — multi-user trading groups

---

## Architecture

```
HOPEFX-AI-TRADING/
├── app.py                    # FastAPI server — 22 routers, lifespan startup
├── kill_switch.py            # System-wide halt (API + file + env + event bus)
├── prometheus_monitoring.py  # /metrics endpoint + MetricsRegistry sync
│
├── api/                      # REST endpoints (trading, admin, backtesting, monetization)
├── auth/                     # JWT auth, RBAC, 2FA
├── brokers/                  # OANDA, MT5, Alpaca, IB, Binance, CCXT, paper, smart router
├── strategies/               # 10 built-in strategies + StrategyBrain orchestrator
├── execution/                # FIX adapter, OMS, trade executor, position tracker
├── risk/                     # RiskManager, circuit breakers, VaR, FIA compliance
│
├── core/
│   ├── component_registry.py # Dependency-ordered startup registry
│   ├── startup_factories.py  # Component factory functions (extracted from startup_event)
│   ├── signal_engine.py      # Strategy → risk → order pipeline (background task)
│   ├── email_service.py      # SendGrid primary, SMTP fallback, dev log
│   └── position_reconciler.py
│
├── ml/                       # ML pipeline
│   ├── training.py           # RF + XGBoost + LSTM training with walk-forward split
│   ├── run_training.py       # CLI training runner
│   ├── train_with_macro.py   # 50-year macro retrain (DXY, VIX, yields, SPX)
│   ├── features/             # 66-feature technical engineering
│   └── saved_models/GCF/     # Trained weights + manifest.json
│
├── data/                     # Data pipeline
│   ├── scheduler.py          # Daily OANDA/yfinance fetch (wired to app startup)
│   ├── validator.py          # Price sanity, gap detection, stale data
│   ├── real_time_price_engine.py
│   └── XAU_USD_H1.csv        # 11,457 H1 bars, 2024-03-24 to 2026-03-24
│
├── notifications/
│   ├── manager.py            # SendGrid primary, SMTP fallback, Telegram, Discord
│   └── alert_engine.py       # Rule-based alert routing
│
├── infrastructure/           # Metrics registry (41 collectors), health, logging
├── nocode/                   # No-code strategy builder
├── replay/                   # Chart replay engine
├── explainability/           # AI explainability / SHAP
├── transparency/             # Execution transparency / TCA
│
├── grafana/                  # 4 dashboards, 27 panels — all metric names verified
├── prometheus.yml            # Scrape config
├── docker-compose.yml        # app + postgres + redis + prometheus + grafana
├── helm/hopefx/              # Kubernetes Helm chart (HPA, PDB, secrets)
├── k8s/                      # Raw Kubernetes manifests
│
└── tests/                    # 2435 passing tests
    ├── test_auth_gates.py    # 56 tests — RBAC enforcement
    ├── test_auth_pentest.py  # 18 tests — JWT security
    ├── test_smoke_critical.py # 30 tests — module import smoke
    ├── test_copy_trading.py  # 20 tests — CopyTradingEngine
    ├── integration/          # API, broker, Redis integration
    ├── unit/                 # Per-module unit tests
    └── e2e/                  # End-to-end trading flow
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- pip
- Git
- Redis (optional — app falls back gracefully)
- Docker + Docker Compose (for full stack with monitoring)

### Installation

```bash
# 1. Clone
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# 2. Virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, and any broker credentials
```

### Run (API server only)

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
# Swagger UI:  http://localhost:8000/docs
# Metrics:     http://localhost:8000/metrics
# Health:      http://localhost:8000/health
```

### Run (full stack with monitoring)

```bash
docker-compose up -d
# App:        http://localhost:8000
# Grafana:    http://localhost:3000  (set GF_SECURITY_ADMIN_PASSWORD in .env)
# Prometheus: http://localhost:9090
```

### Run (Kubernetes)

```bash
helm upgrade --install hopefx helm/hopefx/ \
  --set image.tag=latest \
  --set secrets.databaseUrl="postgresql://..." \
  --set secrets.redisUrl="redis://..."
```

### Fetch data and retrain models

```bash
# Pull latest XAUUSD H1 bars (also runs automatically on app startup)
python -m data.scheduler

# Retrain RandomForest + XGBoost on current data
python ml/run_training.py --symbol GC=F --period 2y --models random_forest,xgboost

# Full 50-year macro retrain (recommended before live use)
python ml/train_with_macro.py --years 50
```

### Run tests

```bash
pip install pytest pytest-asyncio pytest-cov

# Full suite (excludes Redis integration — requires running Redis)
pytest tests/ --ignore=tests/integration/test_redis.py -q
# Expected: 2435 passed, 18 skipped

# With Redis
pytest tests/ -q
```

---

## API Endpoints

| Group | Prefix | Description |
|---|---|---|
| Auth | `/auth` | Login, register, JWT refresh, 2FA |
| Trading | `/api/trading` | Orders, positions, OHLCV, market data |
| Admin | `/admin` | System config, risk settings, activity log |
| Backtesting | `/api/backtest` | Run backtests, hyperopt, walk-forward |
| Monetization | `/api/monetization` | Subscriptions, licensing |
| Kill Switch | `/api/kill-switch` | Activate / deactivate / status |
| WebSocket | `/ws` | Real-time price and order streaming |
| Alerts | `/api/alerts` | Alert rules and notification history |
| Order Flow | `/api/order-flow` | Institutional flow analysis |
| Market Scanner | `/api/scanner` | Multi-symbol opportunity scanner |
| Depth of Market | `/api/dom` | Level 2 order book |
| Signals | `/api/signals` | Strategy signal feed |
| News | `/api/news` | News sentiment and geopolitical risk |
| Research | `/api/research` | In-app research notebooks |
| Explainability | `/api/explainability` | SHAP feature attribution, counterfactuals |
| Transparency | `/api/transparency` | Slippage reports, execution audit trail |
| Teams | `/api/teams` | Multi-user trading groups |
| No-Code Builder | `/api/nocode` | Plain-English strategy creation |
| Replay | `/api/replay` | Historical chart replay with practice orders |
| ML | `/api/ml` | Model predictions, feature importance |
| Hyperopt | `/api/hyperopt` | Strategy parameter optimisation |
| Status (JSON) | `/api/status/json` | Machine-readable system status |
| Status (HTML) | `/status` | Public status page |
| Metrics | `/metrics` | Prometheus scrape endpoint |
| Health | `/health` | Component health check |
| Docs | `/docs` | Swagger UI |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | SQLite | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `SECURITY_JWT_SECRET` | dev default | JWT signing secret — **set in production** |
| `PAPER_TRADING_BALANCE` | `10000` | Starting balance for paper broker |
| `OANDA_ACCOUNT_ID` | — | OANDA practice account ID |
| `OANDA_API_KEY` | — | OANDA API key |
| `HOPEFX_KILL_SWITCH_TOKEN` | — | Token required to deactivate kill switch via API |
| `SENDGRID_API_KEY` | — | SendGrid API key for transactional email |
| `FROM_EMAIL` | `noreply@hopefx.io` | Sender address for transactional email |
| `SMTP_HOST` | — | SMTP host (fallback if SendGrid not configured) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |
| `PROMETHEUS_SCRAPE_INTERVAL_SECONDS` | `15` | Metrics sync cadence |
| `RISK_MAX_POSITION_SIZE_PCT` | `0.02` | Max position size as % of equity |
| `RISK_MAX_DRAWDOWN_PCT` | `0.10` | Max drawdown before halt |
| `RISK_MAX_DAILY_LOSS_PCT` | `0.05` | Daily loss limit |
| `SIGNAL_ENGINE_SYMBOLS` | `XAUUSD,EURUSD,GBPUSD` | Symbols for signal engine |
| `SIGNAL_ENGINE_AUTO_TRADE` | `false` | Enable auto-execution of signals |
| `FEATURE_EXPLAINABILITY` | `false` | Enable explainability module |
| `FEATURE_NOCODE` | `false` | Enable no-code builder |
| `FEATURE_REPLAY` | `false` | Enable chart replay |
| `FEATURE_TRANSPARENCY` | `false` | Enable transparency reports |
| `GF_SECURITY_ADMIN_PASSWORD` | required | Grafana admin password |

The app starts without any `.env` file — all variables have safe defaults for local development.

---

## Monitoring

Four Grafana dashboards are provisioned automatically on `docker-compose up`:

| Dashboard | Panels | Key Metrics |
|---|---|---|
| Trading Performance | 7 | Equity curve, open positions, daily P&L, win rate, drawdown, order rate, fill latency |
| ML Model Metrics | 7 | Signal confidence, signals/hr, model accuracy, market regime, drift score, inference latency, last retrain |
| Broker Connectivity | 6 | Broker status, round-trip latency, rejection rate, active broker, failover events, FIX heartbeat |
| System Health | 7 | API request rate, error rate, p95 latency, CPU, memory, Redis clients, DB pool |

All 27 Grafana panel expressions are verified against registered `MetricsRegistry` collectors.

---

## Security

1. Never commit credentials — use environment variables or `.env` (gitignored)
2. `SECURITY_JWT_SECRET` must be set to a strong random value in production
3. `HOPEFX_KILL_SWITCH_TOKEN` must be set to enable authenticated kill switch deactivation
4. `GF_SECURITY_ADMIN_PASSWORD` is required — Docker Compose refuses to start without it
5. All API keys encrypted at rest via Fernet (`config/config_manager.py`)
6. JWT tokens with configurable expiry; 2FA supported
7. AML gate and compliance checks on all order flow
8. Passwords hashed with bcrypt (SHA-256 pre-hash handles inputs >72 bytes)

See [SECURITY.md](./SECURITY.md) for full guidelines.

---

## Known Limitations

| Area | Status |
|---|---|
| ML accuracy | 49% on H1 data — near chance. 50-year macro retrain not yet run. |
| Backtest depth | 17 trades over 9 months — insufficient for Sharpe significance. |
| FIX adapter | 3 `pass` blocks in `execution/fix_adapter.py` — not production-ready. |
| PPO reward | 1 bp holding cost — far below real transaction costs. |
| VaR scaling | `sqrt(t)` approximation — documented, not calibrated. |
| Email deliverability | SendGrid configured but not warmed up — set `SENDGRID_API_KEY` before production use. |

See [CRITICAL_FLAWS.md](./CRITICAL_FLAWS.md) for the full audit trail.

---

## Testing

```bash
pip install pytest pytest-asyncio pytest-cov

# Full suite (excludes Redis — requires running Redis instance)
pytest tests/ --ignore=tests/integration/test_redis.py -q
# Expected: 2435 passed, 18 skipped

# Specific suites
pytest tests/test_auth_gates.py -q        # 56 tests — RBAC
pytest tests/test_auth_pentest.py -q      # 18 tests — JWT security
pytest tests/test_smoke_critical.py -q    # 30 tests — module imports
pytest tests/test_copy_trading.py -q      # 20 tests — copy trading
pytest tests/integration/ -q             # API + broker integration
pytest tests/unit/ -q                    # Per-module unit tests
```

---

## Documentation

| Document | Description |
|---|---|
| [CRITICAL_FLAWS.md](./CRITICAL_FLAWS.md) | Audit findings, fix history, open items |
| [INSTALLATION.md](./INSTALLATION.md) | Full installation guide |
| [DIAGNOSTIC_REPORT.md](./DIAGNOSTIC_REPORT.md) | Static + dynamic audit with commit hashes |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Production deployment guide |
| [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) | Pre-launch checklist |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](./SECURITY.md) | Security best practices |
| [DEBUGGING.md](./DEBUGGING.md) | Troubleshooting guide |
| [CHANGELOG.md](./CHANGELOG.md) | Version history |
| [docs/API_GUIDE.md](./docs/API_GUIDE.md) | API developer guide |
| [docs/SAMPLE_STRATEGIES.md](./docs/SAMPLE_STRATEGIES.md) | Ready-to-use strategies |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make changes and add tests
4. Run `pytest tests/ --ignore=tests/integration/test_redis.py -q` — all must pass
5. Submit a pull request

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines.

---

## Community

<div align="center">

[![Discord](https://img.shields.io/badge/Discord-Join%20Community-7289da?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/hopefx)
[![Telegram](https://img.shields.io/badge/Telegram-Join%20Channel-26a5e4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/hopefx)
[![Twitter](https://img.shields.io/badge/Twitter-Follow%20Us-1da1f2?style=for-the-badge&logo=twitter&logoColor=white)](https://twitter.com/HOPEFX_Trading)
[![YouTube](https://img.shields.io/badge/YouTube-Subscribe-ff0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/@hopefx)

</div>

---

## Support

| Type | Contact |
|---|---|
| General questions | [Discord](https://discord.gg/hopefx) or [GitHub Discussions](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/discussions) |
| Bug reports | [GitHub Issues](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues) |
| Security issues | See [SECURITY.md](./SECURITY.md) |
| Partnerships | partners@hopefx.com |

---

## License

MIT License — see [LICENSE](./LICENSE). Free for personal and commercial use.

---

<div align="center">

**Built with ❤️ by the HOPEFX Community**

[Get Started](./INSTALLATION.md) • [API Docs](http://localhost:8000/docs) • [Discord](https://discord.gg/hopefx) • [Star Us](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING)

</div>
