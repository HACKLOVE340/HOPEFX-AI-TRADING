# HOPEFX Documentation

**AI-powered gold and forex trading platform.**
Automated strategies, real-time signals, and institutional-grade risk management.

---

## What is HOPEFX?

HOPEFX is a self-hosted algorithmic trading framework that combines:

- **Machine learning** — XGBoost stacking ensemble (176 features, 66.4% OOS accuracy, p=0.0000) with incremental online learning (SGD + EWC, hourly updates)
- **Strategy engine** — 10 built-in strategies (MA crossover, EMA crossover, RSI, MACD, Bollinger Bands, SMC/ICT, mean reversion, breakout, stochastic, Strategy Brain)
- **Risk management** — per-trade position sizing, CVaR gate, daily loss limits, max drawdown circuit breakers, kill switch, prop-firm compliance mode
- **Broker integration** — OANDA (practice + live), Interactive Brokers, paper trading simulator, FIX 4.4 adapter
- **Multi-symbol backtesting** — walk-forward validation across XAU/USD, BTC/USD, ETH/USD; N=628 trades confirmed (Sharpe gate PASSED)
- **Multi-channel alerts** — Discord, Telegram, email, Sentry

---

## Quick navigation

| I want to… | Go to |
|---|---|
| Install HOPEFX | [Installation](INSTALLATION.md) |
| Run my first backtest | [Quick Start](QUICKSTART.md) |
| Connect OANDA | [OANDA Paper Trading Setup](oanda_paper_trading_setup.md) |
| Browse strategies | [Sample Strategies](SAMPLE_STRATEGIES.md) |
| Read the API docs | [API Reference](API_REFERENCE.md) |
| Get answers | [FAQ](FAQ.md) |

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI Server                        │
│   REST API · WebSocket · GraphQL · /docs · /api/signals      │
└────────────────────────┬─────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐   ┌──────────────┐  ┌──────────────┐
   │  ML/AI   │   │  HOPEFXBrain │  │  Risk Engine │
   │ advanced │   │  Signal +    │  │  CVaR gate   │
   │ _oos.pkl │   │  Regime      │  │  Kill switch │
   │ 176 feat │   │  Decision    │  │  Drawdown    │
   └────┬─────┘   └──────┬───────┘  └──────┬───────┘
        │                │                  │
   ┌────▼─────┐          └──────────────────┘
   │ Online   │                  │
   │ Learner  │                  ▼
   │ SGD+EWC  │         ┌──────────────────┐
   │ hourly   │         │  Execution Engine│
   └──────────┘         │  Smart Router    │
                        │  OANDA · IBKR    │
                        │  Paper · FIX 4.4 │
                        └────────┬─────────┘
                                 │
                  ┌──────────────▼──────────────┐
                  │      Data & Persistence      │
                  │  PostgreSQL · Redis · Macro  │
                  └──────────────────────────────┘
```

---

## System requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 4 GB | 8 GB |
| CPU | 2 cores | 4+ cores |
| Storage | 10 GB | 20 GB |
| Redis 7+ | Optional | Recommended |
| PostgreSQL 16+ | Optional | Recommended |

---

## License

AGPL-3.0. See [LICENSE](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE). Commercial use requires a separate license — see [LICENSE-COMMERCIAL.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE-COMMERCIAL.md).
