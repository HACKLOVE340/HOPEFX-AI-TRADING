# HOPEFX — AI Gold Trading Platform

> **Status: Paper Trading** | XAUUSD | Multi-broker | Real-time ML

[![CI](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/ci.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/ci.yml)
[![Tests](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml/badge.svg)](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions/workflows/tests.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](pyproject.toml)

---

## Key Stats

| Metric | Value |
|--------|-------|
| Out-of-sample accuracy | **68%** |
| Backtest return | **+5.52%** |
| Walk-forward folds | 5 |
| Supported symbols | XAUUSD (XAU/USD) |
| Broker integrations | OANDA · IBKR · Paper |

---

## Features

- **Prop-firm compliance** — daily drawdown gate, max position size, kill switch
- **Multi-broker routing** — OANDA paper/live, IBKR TWS/Gateway, paper fallback with auto-failover
- **Real-time ML signals** — XGBoost stacking ensemble, 100+ engineered features, walk-forward validation
- **Regime detection** — HMM-based market regime classifier gates entries
- **Risk engine** — CVaR order gate, pre-trade checks, position sizing, Sharpe/SE guard
- **Sentiment layer** — news feed parser + TextBlob/VADER scoring
- **Observability** — Prometheus metrics, Sentry error tracking, structured logging
- **REST + WebSocket API** — FastAPI, JWT auth, rate limiting, GraphQL endpoint
- **Full test suite** — 3 000+ tests, pytest-asyncio, hypothesis property tests, 70% coverage gate

---

## Quick Start

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
pip install -r requirements-ci.txt
cp .env.example .env          # fill in OANDA_API_KEY etc.
python quickstart.py          # paper trading mode
```

Run tests:

```bash
pytest tests/ -m "not slow" -q
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI / WebSocket               │
├──────────────┬──────────────┬───────────────────────┤
│  ML Pipeline │  Risk Engine │  Broker Router        │
│  (XGBoost)   │  (CVaR/DD)   │  OANDA · IBKR · Paper │
├──────────────┴──────────────┴───────────────────────┤
│         Market Data Feed  ·  News Sentiment         │
├─────────────────────────────────────────────────────┤
│   PostgreSQL · Redis · Prometheus · Sentry          │
└─────────────────────────────────────────────────────┘
```

---

## Configuration

All settings are loaded from environment variables (see `.env.example`).
Critical secrets (API keys, JWT secret) must be set before starting.

| Variable | Purpose |
|----------|---------|
| `OANDA_API_KEY` | OANDA v20 REST API key |
| `OANDA_ACCOUNT_ID` | OANDA account ID |
| `SECURITY_JWT_SECRET` | JWT signing secret (≥32 chars) |
| `REDIS_URL` | Redis connection string |
| `DB_URL` | PostgreSQL async URL |

---

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for current milestones.

---

## License

AGPL-3.0 — see [LICENSE](LICENSE). Modifications must be shared under the same license.
Commercial use requires explicit permission from HOPEFX.
