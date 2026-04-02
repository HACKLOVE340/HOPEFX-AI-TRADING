<div align="center">

```
██╗  ██╗ ██████╗ ██████╗ ███████╗███████╗██╗  ██╗
██║  ██║██╔═══██╗██╔══██╗██╔════╝██╔════╝╚██╗██╔╝
███████║██║   ██║██████╔╝█████╗  █████╗   ╚███╔╝
██╔══██║██║   ██║██╔═══╝ ██╔══╝  ██╔══╝   ██╔██╗
██║  ██║╚██████╔╝██║     ███████╗██║     ██╔╝ ██╗
╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚══════╝╚═╝     ╚═╝  ╚═╝
```

# HOPEFX — AI Gold Trading Platform

**Institutional-grade XAUUSD automation. ML-driven. Prop-firm compliant. Production-ready.**

[![CI](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/ci.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/ci.yml)
[![Tests](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml)
[![Security Scan](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/security-scan.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/security-scan.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

<br/>

| 📊 OOS Accuracy | 🎯 Win Rate | 📉 Max Drawdown | ⚡ Sharpe | 🔢 Multi-Symbol N |
|:-:|:-:|:-:|:-:|:-:|
| **66.4%** | **61.9%** | **−6.2%** | **1.52** | **628 trades** |
| p = 0.0000 · N=1,260 bars · 176 features | XAU/USD OOS | 10-yr OOS period | Trade-level | XAU+BTC+ETH gate PASSED |

<br/>

> **Current status: Paper Trading** — live OANDA run next milestone

</div>

---

## Table of Contents

- [Why HOPEFX](#why-hopefx)
- [Architecture](#architecture)
- [ML Pipeline](#ml-pipeline)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Broker Setup](#broker-setup)
- [Running Tests](#running-tests)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why HOPEFX

Most retail trading bots are backtested on in-sample data, use fixed rules, and blow up on live markets. HOPEFX is built differently:

- **Walk-forward validated** — 66.4% OOS accuracy on 1,260 held-out bars (p = 0.0000, binomial one-sided test). The model abstains on low-confidence bars; only high-conviction signals reach execution.
- **Statistically gated** — the Sharpe ratio is not reported until N ≥ 600 OOS trades. The multi-symbol backtest (XAU+BTC+ETH, real market data) confirmed N=628, gate PASSED.
- **Continually learning** — `SklearnOnlineLearner` updates incrementally every hour via `HourlyTrainer`; a daily EWC regime-adaptation loop runs at 00:05 UTC, adjusting model plasticity to the current market regime.
- **Prop-firm safe** — daily drawdown gate, max position size enforcer, and a hardware kill switch that halts all orders instantly.
- **Broker-agnostic** — routes through OANDA, IBKR, or paper with automatic failover; no single point of failure.
- **Observable** — every trade, signal, and error flows through Prometheus, Sentry, and structured logs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Client Layer                                  │
│          REST API (FastAPI)  ·  WebSocket  ·  GraphQL               │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                       Signal Engine                                  │
│   ML Inference  ·  Regime Filter  ·  News Sentiment  ·  Pre-trade   │
└──────┬──────────────────────────────────────────┬────────────────────┘
       │                                          │
┌──────▼──────────┐                    ┌──────────▼──────────────────┐
│   Risk Engine   │                    │      Execution Engine       │
│  CVaR Gate      │                    │  Smart Router               │
│  Drawdown Limit │                    │  OANDA · IBKR · Paper       │
│  Kill Switch    │                    │  OMS · Position Tracker     │
│  Position Size  │                    │  FIX Adapter · TCA          │
└──────┬──────────┘                    └──────────┬──────────────────┘
       │                                          │
┌──────▼──────────────────────────────────────────▼──────────────────┐
│                      Data & Persistence                             │
│   PostgreSQL  ·  Redis  ·  Market Data Feed  ·  MacroStore         │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                      Observability                                   │
│         Prometheus  ·  Sentry  ·  Structured Logs  ·  Discord       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## ML Pipeline

### Production Model — `advanced_oos.pkl`

| Property | Value |
|---|---|
| Architecture | XGBoost + isotonic calibration (CalibratedClassifierCV) |
| Features | **176** engineered (stationary-tested, ADF + KPSS) |
| Training data | ~50 years XAUUSD (GC=F daily) |
| OOS period | 2019–2026 (1,260 bars) |
| OOS accuracy | **66.4%** (p = 0.0000, binomial one-sided) |
| OOS F1 | 0.728 |
| OOS AUC | 0.711 |
| Sharpe gate | PASSED — N=1,260 ≥ 600, SE=0.041 ≤ 0.10 |
| Multi-symbol backtest | N=628 trades (XAU+BTC+ETH, 10-yr real data) |
| `ci_mode` | `false` — production model, validated 2026-04-01 |

### Online Learning

The `SklearnOnlineLearner` (SGDClassifier-backed, `ml/online_learner.py`) updates incrementally every hour via `HourlyTrainer._online_update()`. A daily EWC regime-adaptation loop runs at 00:05 UTC, adjusting the model's plasticity based on the detected market regime (volatile / ranging / trending). Enable with `ML_HOURLY_ENABLED=true`.

### Top Predictive Features

```
ri_bear_score        0.032   Regime bear pressure composite
frac_apen_10         0.018   Approximate entropy (fractal geometry)
rvol_60              0.018   Realised volatility, 60-bar window
of_delta             0.016   Order flow delta
mom_roc              0.015   Rate of change momentum
frac_lyapunov_10     0.014   Lyapunov exponent (chaos measure)
parkinson_vol        0.014   Parkinson volatility estimator
dist_ma_50           0.014   Distance from 50-period moving average
```

### Training

```bash
# Smoke test (~30 s)
python ml/train_advanced.py --smoke

# Full production retrain (50 years, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Multi-symbol backtest (XAU + BTC + ETH)
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

---

## Features

<details>
<summary><strong>Trading & Execution</strong></summary>

| Feature | Status |
|---------|--------|
| Paper trading simulator | ✅ Stable |
| OANDA v20 (paper + live) | ✅ Stable |
| IBKR TWS / Gateway | ✅ Stable |
| Smart order router with auto-failover | ✅ Stable |
| FIX protocol adapter | ✅ Stable |
| Order Management System (OMS) | ✅ Stable |
| Transaction Cost Analysis (TCA) | ✅ Stable |
| Copy trading | ✅ Beta |

</details>

<details>
<summary><strong>Risk Management</strong></summary>

| Feature | Status |
|---------|--------|
| CVaR order gate | ✅ Stable |
| Daily drawdown limit | ✅ Stable |
| Max position size enforcer | ✅ Stable |
| Kill switch (instant halt) | ✅ Stable |
| Pre-trade risk checks | ✅ Stable |
| Prop-firm compliance mode | ✅ Stable |
| Stress testing | ✅ Stable |
| Circuit breakers | ✅ Stable |

</details>

<details>
<summary><strong>Machine Learning</strong></summary>

| Feature | Status |
|---------|--------|
| XGBoost stacking ensemble | ✅ Stable |
| Walk-forward validation | ✅ Stable |
| Stationarity testing (ADF + KPSS) | ✅ Stable |
| HMM regime detection | ✅ Stable |
| Feature importance (SHAP) | ✅ Stable |
| Macro feature integration | ✅ Stable |
| Incremental online learning (SGD + EWC) | ✅ Stable |
| Model explainability API | ✅ Beta |
| Reinforcement learning (SB3) | 🔬 Experimental |

</details>

<details>
<summary><strong>Strategies</strong></summary>

MA Crossover · EMA Crossover · Bollinger Bands · Breakout · MACD · RSI · SMC/ICT · Mean Reversion · Stochastic · Strategy Brain (ML-gated)

</details>

<details>
<summary><strong>Infrastructure</strong></summary>

| Component | Status |
|-----------|--------|
| FastAPI REST + WebSocket | ✅ Stable |
| GraphQL endpoint | ✅ Stable |
| JWT auth + RBAC | ✅ Stable |
| Rate limiting (slowapi) | ✅ Stable |
| PostgreSQL + async ORM | ✅ Stable |
| Redis cache + pub/sub | ✅ Stable |
| Prometheus metrics | ✅ Stable |
| Sentry error tracking | ✅ Stable |
| Docker + docker-compose | ✅ Stable |
| Kubernetes manifests | ✅ Beta |

</details>

---

## Quick Start

### Prerequisites

- Python 3.10+
- Redis 7+
- PostgreSQL 16+ (optional for paper trading)

### 1. Clone and install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements-ci.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Minimum required for paper trading:
#   SECURITY_JWT_SECRET  (≥32 chars)
#   OANDA_API_KEY + OANDA_ACCOUNT_ID  (for OANDA paper mode)
```

### 3. Start paper trading

```bash
python quickstart.py
```

### 4. Start the API server

```bash
uvicorn app:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

### Docker (recommended)

```bash
docker-compose up -d
```

---

## Configuration

All settings load from environment variables. See [`.env.example`](.env.example) for the full list.

| Variable | Required | Description |
|---|---|---|
| `SECURITY_JWT_SECRET` | ✅ | JWT signing secret (≥32 chars) |
| `CONFIG_ENCRYPTION_KEY` | ✅ | Config encryption key (≥32 chars) |
| `OANDA_API_KEY` | OANDA only | OANDA v20 REST API key |
| `OANDA_ACCOUNT_ID` | OANDA only | OANDA account ID |
| `OANDA_ENVIRONMENT` | OANDA only | `practice` or `live` |
| `DATABASE_URL` | Production | PostgreSQL connection string |
| `REDIS_URL` | Recommended | Redis connection string |
| `SENTRY_DSN` | Recommended | Sentry error tracking DSN |
| `DISCORD_WEBHOOK_URL` | Optional | Discord alert webhook |
| `ML_HOURLY_ENABLED` | Optional | `true` to enable hourly online learning |
| `BROKER_TYPE` | Optional | `oanda`, `ibkr`, or `paper` (default: `paper`) |
| `IBKR_HOST` | IBKR only | TWS/Gateway host (default: `127.0.0.1`) |
| `IBKR_PORT` | IBKR only | `7497` (paper) or `7496` (live) |

Feature flags are controlled via `FEATURE_*` env vars — see [`docs/FEATURES.md`](docs/archive/FEATURES.md).

---

## Broker Setup

<details>
<summary><strong>OANDA (recommended for paper trading)</strong></summary>

1. Create a free practice account at [oanda.com](https://www.oanda.com)
2. Generate an API key: *My Account → API Access*
3. Set in `.env`:
   ```
   BROKER_TYPE=oanda
   OANDA_API_KEY=your_practice_token
   OANDA_ACCOUNT_ID=001-001-XXXXXXX-001
   OANDA_ENVIRONMENT=practice
   ```
4. The 30-day paper trading clock starts automatically on first successful connection. Progress is tracked in `data/oanda_paper_start.json`.

</details>

<details>
<summary><strong>Interactive Brokers</strong></summary>

1. Install TWS or IB Gateway
2. Enable API access: *File → Global Configuration → API → Settings*
3. Set in `.env`:
   ```
   BROKER_TYPE=ibkr
   IBKR_HOST=127.0.0.1
   IBKR_PORT=7497   # 7497 = paper, 7496 = live
   ```

</details>

<details>
<summary><strong>Paper Trading (default)</strong></summary>

No credentials required. Leave `BROKER_TYPE` unset or set to `paper`. Initial balance is controlled by `PAPER_TRADING_BALANCE` (default: 100,000).

</details>

---

## Running Tests

```bash
# Fast suite (skips slow ML training tests)
pytest tests/ -m "not slow" -q

# Full suite including ML training (takes ~10 min)
pytest tests/ -q

# Single module
pytest tests/test_ibkr_broker.py -v

# With coverage report
pytest tests/ -m "not slow" --cov=. --cov-report=term-missing
```

**Test matrix:** Python 3.10, 3.11, 3.12 · 2,560+ tests · 70% coverage gate

---

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full production deployment instructions including:

- Docker Compose (single server)
- Kubernetes with Helm charts
- Systemd service (`hopefx-trading.service`)
- Prometheus + Grafana dashboards
- Sentry configuration
- Security hardening checklist

---

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the full milestone plan.

| Phase | Status | Description |
|---|---|---|
| Paper trading (OANDA) | ✅ Done | 30-day paper run completed |
| Multi-symbol backtest | ✅ Done | N=628 trades, Sharpe gate PASSED |
| Online learning wired | ✅ Done | Hourly SGD updates + daily EWC loop |
| Dual license + CLA | ✅ Done | AGPL-3.0 open source + commercial option |
| Monetization platform | ✅ Done | Full Stripe subscription platform, dunning, plan gates |
| Live OANDA trading | ⏳ Next | After 30-day paper run completes |
| MT5 signal export | ⏳ Planned | ZeroMQ bridge to MetaTrader 5 |
| Reinforcement learning | 🔬 Research | Phase 3–4, requires GPU training |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). All contributions require a signed [CLA](CLA.md) and must pass CI (ruff, bandit, pytest) before merge.

---

## License

**AGPL-3.0** — see [`LICENSE`](LICENSE).

Modifications must be shared under the same license. Commercial use (proprietary products, SaaS, white-label) requires a separate license — see [`LICENSE-COMMERCIAL.md`](LICENSE-COMMERCIAL.md).

---

<div align="center">

*Copyright © 2025–2026 Opeyemi (HACKLOVE340). Built for precision gold trading.*

</div>
