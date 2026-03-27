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

| 📊 OOS Accuracy | 📈 Backtest Return | 🎯 Win Rate | 📉 Max Drawdown | ⚡ Sharpe |
|:-:|:-:|:-:|:-:|:-:|
| **68.0%** | **+5.52%** | **57.8%** | **−0.88%** | **1.52** |
| p = 0.0000 · 756 bars | 48 trades · real GC=F | Profit factor 2.28 | 3-year OOS period | Trade-level |

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

- **Walk-forward validated** — the 68% accuracy figure comes from a 3-year held-out OOS period (2023–2026), not in-sample fitting
- **Statistically tested** — p = 0.0000 on 756 OOS bars; the model abstains on 27.5% of bars where confidence is below threshold
- **Prop-firm safe** — daily drawdown gate, max position size enforcer, and a hardware kill switch that halts all orders instantly
- **Broker-agnostic** — routes through OANDA, IBKR, or paper with automatic failover; no single point of failure
- **Observable** — every trade, signal, and error flows through Prometheus, Sentry, and structured logs

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

The production model (`advanced_oos.pkl`) is a **stacking ensemble** trained on 50 years of GC=F futures data.

### Model Card

| Property | Value |
|----------|-------|
| Architecture | XGBoost + RF stacking ensemble |
| Features | 154 engineered (stationary-tested) |
| Training data | 50 years GC=F (6,365 bars) |
| OOS period | 2023-03-22 → 2026-03-24 (756 bars) |
| OOS accuracy | **68.0%** (p = 0.0000) |
| Abstain rate | 27.5% of bars filtered |
| Walk-forward folds | 5 |
| Target | ≥55% OOS with p < 0.05 — **exceeded** |

### Top Predictive Features

```
ri_bear_score        0.032   Regime bear pressure composite
frac_apen_10         0.018   Approximate entropy (fractal)
rvol_60              0.018   Realised volatility 60-bar
of_delta             0.016   Order flow delta
mom_roc              0.015   Rate of change momentum
frac_lyapunov_10     0.014   Lyapunov exponent (chaos measure)
parkinson_vol        0.014   Parkinson volatility estimator
dist_ma_50           0.014   Distance from 50-period MA
```

### Training a New Model

```bash
# Quick smoke test (~30 s)
python scripts/retrain_model.py --smoke --advanced

# Full retrain (50 years, 5 OOS years)
python scripts/retrain_model.py --advanced --years 50 --oos-years 5
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
pip install -r requirements-ci.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — minimum required for paper trading:
#   OANDA_API_KEY, OANDA_ACCOUNT_ID, SECURITY_JWT_SECRET
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
|----------|----------|-------------|
| `OANDA_API_KEY` | ✅ | OANDA v20 REST API key |
| `OANDA_ACCOUNT_ID` | ✅ | OANDA account ID |
| `SECURITY_JWT_SECRET` | ✅ | JWT signing secret (≥32 chars) |
| `REDIS_URL` | ✅ | Redis connection string |
| `DB_URL` | Paper only | PostgreSQL async URL |
| `SENTRY_DSN` | Recommended | Sentry error tracking DSN |
| `DISCORD_WEBHOOK_URL` | Optional | Discord alert webhook |
| `IBKR_HOST` | IBKR only | TWS/Gateway host (default: 127.0.0.1) |
| `IBKR_PORT` | IBKR only | 7497 (paper) or 7496 (live) |

Feature flags are controlled via `FEATURE_*` env vars — see [`FEATURES.md`](FEATURES.md).

---

## Broker Setup

<details>
<summary><strong>OANDA (recommended for paper trading)</strong></summary>

1. Create a free practice account at [oanda.com](https://www.oanda.com)
2. Generate an API key from *My Account → API Access*
3. Set `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` in `.env`
4. Set `OANDA_ENVIRONMENT=practice` for paper, `live` for real money

</details>

<details>
<summary><strong>Interactive Brokers</strong></summary>

1. Install TWS or IB Gateway
2. Enable API access: *File → Global Configuration → API → Settings*
3. Set `IBKR_PORT=7497` (paper) or `7496` (live)
4. The connector uses `ib_insync` — install with `pip install ib_insync`

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

**Test matrix:** Python 3.10, 3.11, 3.12 · 3 000+ tests · 70% coverage gate

---

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full production deployment instructions including:

- Docker Compose (single server)
- Kubernetes with Helm charts
- Systemd service (`hopefx-trading.service`)
- Prometheus + Grafana dashboards
- Sentry configuration

---

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the full milestone plan.

**Current:** Paper mode live on OANDA  
**Next:** Live OANDA run · 200+ trade sample · MT5 export  
**Later:** Multi-symbol (BTC, ETH) · Reinforcement learning · White-label API

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). All contributions must pass CI (ruff, bandit, pytest) before merge.

---

## License

**AGPL-3.0** — see [`LICENSE`](LICENSE).

Modifications must be shared under the same license.  
Commercial use requires explicit written permission from HOPEFX.

---

<div align="center">

*Copyright © 2025–2026 HOPEFX. Built with precision for gold traders.*

</div>
