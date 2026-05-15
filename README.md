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
| **56.5%** | **61.9%** | **−6.2%** | **1.52** | **2016+ trades** |
| p = 0.0000 · N=2,016 bars · 193 features | XAU/USD OOS | 2017–2026 OOS period | Trade-level | SE≤0.10 gate PASSED |

<br/>

> **Current status: Paper Trading active** — live OANDA run is the next milestone

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

- **Walk-forward validated** — 56.5% OOS accuracy on 2,016 held-out bars (p = 0.0000). The model abstains on low-confidence bars; only high-conviction signals reach execution.
- **Chaos-aware** — Lyapunov exponents, Higuchi fractal dimension, approximate entropy, and permutation entropy measure whether the market is in a predictable or chaotic state. The system reduces exposure when chaos is high.
- **Continually learning** — EWC (Elastic Weight Consolidation) prevents catastrophic forgetting during live adaptation. The model adapts to new regimes without losing knowledge of past ones.
- **Pre-execution probability filter** — every signal passes through Itô stochastic calculus price cones (±2σ GBM) before reaching the broker. Late entries are rejected before they cost money.
- **GARCH(1,1) position sizing** — position sizes are forward-looking on volatility. The system is smaller before volatility spikes, not after.
- **Geopolitical intelligence** — a dedicated module monitors conflict zones, sanctions, and central bank events specifically calibrated for gold's safe-haven mechanics.
- **Prop-firm safe** — daily drawdown gate, max position size enforcer, and a hardware kill switch. Rules encoded per firm: FTMO, The5ers, TopStep, MyForexFunds, Goat Funded.
- **Broker-agnostic** — routes through OANDA, IBKR, MT5, Binance, Bybit, Alpaca, or paper with automatic failover.
- **Observable** — every trade, signal, and error flows through Prometheus, Sentry, and structured logs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Client Layer                                  │
│     REST API (FastAPI)  ·  WebSocket  ·  GraphQL  ·  Mobile PWA    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                    HOPEFXBrain / Signal Engine                       │
│  ML Inference · Regime Filter · Nuclear Strategy · News Sentiment   │
│  Itô Cone Filter · Shadow Backtest · Confidence Aggregation         │
└──────┬──────────────────────────────────────────┬────────────────────┘
       │                                          │
┌──────▼──────────┐                    ┌──────────▼──────────────────┐
│   Risk Engine   │                    │      Execution Engine       │
│  CVaR Gate      │                    │  Smart Router               │
│  GARCH(1,1) VaR │                    │  OANDA · IBKR · MT5 · Paper │
│  Drawdown Limit │                    │  TWAP · VWAP · Iceberg      │
│  Kill Switch    │                    │  FIX Adapter · TCA          │
│  Kelly Sizing   │                    │  OMS · Position Tracker     │
└──────┬──────────┘                    └──────────┬──────────────────┘
       │                                          │
┌──────▼──────────────────────────────────────────▼──────────────────┐
│                      Data & Persistence                             │
│  PostgreSQL · Redis · Polygon L2 · Finnhub Tape · MacroStore       │
│  Microstructure Engine · Kyle's Lambda · Lee-Ready Classification  │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                      Observability                                   │
│         Prometheus · Grafana · Sentry · Structured Logs · Discord   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## ML Pipeline

### Production Model — `advanced_oos.pkl`

| Property | Value |
|---|---|
| Architecture | XGBoost + LightGBM + RandomForest + ExtraTrees stacking ensemble |
| Calibration | Isotonic (CalibratedClassifierCV) |
| Features | **193** engineered (stationary-tested, ADF + KPSS) |
| Training data | ~50 years XAUUSD (GC=F daily) |
| OOS period | 2017–2026 (2,016 bars) |
| OOS accuracy | **56.5%** (p = 0.0000, binomial one-sided) |
| OOS F1 | 0.689 |
| OOS AUC | 0.543 |
| Sharpe gate | PASSED — N=2,016 ≥ 600, SE=0.033 ≤ 0.10 |
| Multi-symbol backtest | N>2,016 trades (GC=F, 50-yr real data) |

### Feature Categories (176 features)

| Category | Examples |
|---|---|
| Fractal geometry | Lyapunov exponent, Higuchi fractal dimension, DFA, approximate entropy, permutation entropy, recurrence quantification |
| Order flow | OFI delta, VWAP deviation, bid/ask pressure ratio, cumulative delta |
| Regime | HMM state, bear/bull score, volatility regime, trend strength |
| Macro | DXY, real yields, VIX, COT proxy, intermarket correlations |
| Microstructure | Kyle's lambda, order book imbalance, spread z-score, absorption ratio |
| Technical | RSI, MACD, Bollinger, Ichimoku, Parkinson vol, realised vol |
| Calendar | Session, day-of-week, economic event proximity |

### Online Learning

`SklearnOnlineLearner` (SGDClassifier-backed) updates incrementally every hour via `HourlyTrainer`. A daily EWC regime-adaptation loop runs at 00:05 UTC, adjusting model plasticity to the current market regime using Elastic Weight Consolidation — preventing catastrophic forgetting when regimes change. Enable with `ML_HOURLY_ENABLED=true`.

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

# Full stacking ensemble
python ml/train_advanced.py --years 50 --oos-years 3 --stacking

# Multi-symbol backtest (7 symbols)
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
| MetaTrader 5 (Python API + ZeroMQ bridge) | ✅ Stable |
| Binance / Bybit / Alpaca / CCXT (50+ exchanges) | ✅ Stable |
| FIX 4.4 protocol adapter | ✅ Stable |
| Smart order router (latency + OFI + sentiment scoring) | ✅ Stable |
| TWAP / VWAP / Iceberg order algorithms | ✅ Stable |
| Order Management System (OMS) | ✅ Stable |
| Almgren-Chriss Transaction Cost Analysis (TCA) | ✅ Stable |
| Copy trading | ✅ Stable |

</details>

<details>
<summary><strong>Risk Management</strong></summary>

| Feature | Status |
|---------|--------|
| CVaR order gate | ✅ Stable |
| GARCH(1,1) VaR (MLE, h-step variance recursion) | ✅ Stable |
| Multi-day VaR via overlapping returns | ✅ Stable |
| Daily drawdown limit | ✅ Stable |
| Kelly criterion + drawdown-adaptive sizing | ✅ Stable |
| Max position size enforcer | ✅ Stable |
| Kill switch (instant halt) | ✅ Stable |
| Pre-trade risk checks | ✅ Stable |
| Prop-firm compliance (FTMO, The5ers, TopStep, MFF, Goat) | ✅ Stable |
| Stress testing | ✅ Stable |
| Circuit breakers (execution + Sharpe) | ✅ Stable |
| Intra-trade monitor | ✅ Stable |

</details>

<details>
<summary><strong>Machine Learning</strong></summary>

| Feature | Status |
|---------|--------|
| XGBoost + LGB + RF + ET stacking ensemble | ✅ Stable |
| Walk-forward validation (5-fold anchored) | ✅ Stable |
| Stationarity testing (ADF + KPSS) | ✅ Stable |
| HMM regime detection (7 regimes) | ✅ Stable |
| Fractal geometry features (Lyapunov, HFD, DFA, ApEn) | ✅ Stable |
| EWC online learning (catastrophic forgetting prevention) | ✅ Stable |
| Feature importance (SHAP) | ✅ Stable |
| Macro feature integration | ✅ Stable |
| Model drift monitoring | ✅ Stable |
| Sharpe circuit breaker (live model gating) | ✅ Stable |
| Model explainability API | ✅ Stable |
| Reinforcement learning (PPO, walk-forward eval) | ✅ Stable |

</details>

<details>
<summary><strong>Nuclear Strategy System</strong></summary>

| Feature | Status |
|---------|--------|
| Itô stochastic calculus price cones (±2σ GBM) | ✅ Stable |
| Shadow backtest (last 30 ticks + 5 bars per TF) | ✅ Stable |
| Signal approval gate | ✅ Stable |
| Multi-TF regime classifier | ✅ Stable |
| Redis stream reader | ✅ Stable |
| Nuclear WORDMAP semantic scorer (severity 0–10) | ✅ Stable |

</details>

<details>
<summary><strong>Market Data & Microstructure</strong></summary>

| Feature | Status |
|---------|--------|
| Multi-source WebSocket streamer (Polygon + Finnhub + Twelve Data) | ✅ Stable |
| L2 order book (Polygon quotes + Finnhub trade tape collated) | ✅ Stable |
| Microstructure engine (Kyle's lambda, Lee-Ready, OBI) | ✅ Stable |
| Depth of Market (DOM) service — up to 50 levels | ✅ Stable |
| Order flow analysis (cumulative delta, stacked imbalances) | ✅ Stable |
| Institutional flow detection (iceberg, absorption, smart money) | ✅ Stable |
| Geopolitical risk intelligence (conflict zones, sanctions, instability) | ✅ Stable |
| Economic calendar integration | ✅ Stable |
| News sentiment analysis | ✅ Stable |
| Gold-specific feed manager (GoldAPI, Metals.dev, MetalsAPI) | ✅ Stable |

</details>

<details>
<summary><strong>Strategies</strong></summary>

MA Crossover · EMA Crossover · Bollinger Bands · Breakout · MACD · RSI · **SMC/ICT** (Order Blocks, FVG, Liquidity Sweeps, BOS/CHoCh, OTE Fibonacci) · Mean Reversion · Stochastic · Pullback · **Strategy Brain** (multi-strategy consensus voting) · **Regime Router** · **Nuclear Strategy Engine**

</details>

<details>
<summary><strong>Security</strong></summary>

| Feature | Status |
|---------|--------|
| Global fortress (24/7 autonomous security engine) | ✅ Stable |
| RL-based security response (monitor / rate-limit / block) | ✅ Stable |
| HSM vault (PBKDF2 key derivation, Fernet encryption) | ✅ Stable |
| Self-healer (LLM code review → fix approval queue) | ✅ Stable |
| AML gate (velocity checks, KYC thresholds) | ✅ Stable |
| KYC provider integration | ✅ Stable |
| Regulatory reporter | ✅ Stable |
| JWT auth + RBAC + 2FA | ✅ Stable |
| Rate limiting (per-IP, per-tenant) | ✅ Stable |

</details>

<details>
<summary><strong>Monetization</strong></summary>

| Feature | Status |
|---------|--------|
| Stripe subscription platform (FREE / STARTER / PROFESSIONAL / ENTERPRISE / ELITE) | ✅ Stable |
| Dunning (3x retry at 24h / 72h / 168h) | ✅ Stable |
| Plan gating on all trading and ML endpoints | ✅ Stable |
| Strategy marketplace (submission, purchase, revenue split) | ✅ Stable |
| License key generation / validation / revocation | ✅ Stable |
| Affiliate system | ✅ Stable |
| Crypto checkout | ✅ Stable |
| Invoicing | ✅ Stable |
| White-label API (per-tenant auth, branding, rate limits) | ✅ Stable |

</details>

<details>
<summary><strong>Infrastructure</strong></summary>

| Component | Status |
|-----------|--------|
| FastAPI REST + WebSocket + GraphQL | ✅ Stable |
| JWT auth + RBAC | ✅ Stable |
| Rate limiting (slowapi) | ✅ Stable |
| PostgreSQL + async ORM + Alembic | ✅ Stable |
| Redis cache + pub/sub | ✅ Stable |
| Prometheus + Grafana | ✅ Stable |
| Sentry error tracking | ✅ Stable |
| Docker + docker-compose | ✅ Stable |
| Kubernetes + Helm + ArgoCD | ✅ Stable |
| Systemd service | ✅ Stable |
| Chaos engineering (7 fault injection scenarios) | ✅ Stable |
| Load testing (k6 + Locust) | ✅ Stable |
| 15 CI/CD workflows (ruff, bandit, mypy, pytest, CodeQL, Fortify) | ✅ Stable |

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
#   POLYGON_API_KEY  (for L2 order book)
#   FINNHUB_API_KEY  (for trade tape / cumulative delta)
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
| `POLYGON_API_KEY` | Recommended | Polygon.io — L2 order book + price stream |
| `FINNHUB_API_KEY` | Recommended | Finnhub — trade tape for cumulative delta |
| `TWELVE_API_KEY` | Optional | Twelve Data — price stream (third source) |
| `DATABASE_URL` | Production | PostgreSQL connection string |
| `REDIS_URL` | Recommended | Redis connection string |
| `SENTRY_DSN` | Recommended | Sentry error tracking DSN |
| `DISCORD_WEBHOOK_URL` | Optional | Discord alert webhook |
| `ML_HOURLY_ENABLED` | Optional | `true` to enable hourly online learning |
| `BROKER_TYPE` | Optional | `oanda`, `ibkr`, `mt5`, or `paper` (default: `paper`) |
| `STRIPE_SECRET_KEY` | Monetization | `sk_test_...` (test) or `sk_live_...` (production) |

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
4. The 30-day paper trading clock starts automatically on first successful connection.

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
<summary><strong>MetaTrader 5 (ZeroMQ bridge)</strong></summary>

1. Install the `HopeFX_ZMQ_EA.mq5` EA from `brokers/mql5/` into MT5
2. Enable AutoTrading and ZeroMQ DLL in MT5
3. Set in `.env`:
   ```
   BROKER_TYPE=mt5
   MT5_ZMQ_PUSH_PORT=5555
   MT5_ZMQ_PULL_PORT=5556
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

# Full suite including ML training (~10 min)
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

| Milestone | Status | Description |
|---|---|---|
| Statistical robustness | ✅ Done | 56.5% OOS, N=2,016 bars, SE≤0.10 |
| Monetization platform | ✅ Done | Stripe, dunning, marketplace, white-label |
| MT5 ZeroMQ export | ✅ Done | Custom MQL5 EA + ZeroMQ bridge |
| Multi-symbol expansion | ✅ Done | 7 symbols, portfolio risk wired |
| Strategy marketplace | ✅ Done | Submission, purchase, revenue split |
| Reinforcement learning | ✅ Done | PPO agent, walk-forward eval |
| Web frontend | ✅ Done | 38 pages, real-time charts, order book depth |
| Mobile app | ✅ Done | 19 screens, biometric auth, push notifications |
| White-label API | ✅ Done | Per-tenant auth, rate limiting, branding |
| Live OANDA trading | ⏳ Next | After 30-day paper run completes |

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
