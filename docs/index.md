# HOPEFX Documentation

**AI-powered gold and forex trading platform.**  
Automated strategies, real-time signals, and institutional-grade risk management.

---

## What is HOPEFX?

HOPEFX is a self-hosted algorithmic trading framework that combines:

- **Machine learning** — LSTM, XGBoost, and Random Forest models trained on OHLCV + macro data (DXY, US 10Y yield, CPI)
- **Strategy engine** — 9 built-in strategies (MA crossover, RSI, MACD, Bollinger Bands, SMC/ICT, EMA, mean reversion, breakout, stochastic)
- **Risk management** — per-trade position sizing, daily loss limits, max drawdown circuit breakers, kill switch
- **Broker integration** — OANDA live and practice accounts via REST API
- **Strategy marketplace** — publish and subscribe to community strategies
- **Multi-channel alerts** — Discord, Slack, Telegram, email

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
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Server                       │
│  /api/backtest  /api/macro  /api/payments  /status  /   │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐   ┌──────────┐   ┌──────────────┐
   │  ML/AI   │   │  Brain   │   │  Risk Mgr    │
   │ Training │   │ (HOPEFXBrain)│ (position    │
   │ Pipeline │   │ Decision │   │  sizing,     │
   │          │   │ Engine   │   │  drawdown)   │
   └──────────┘   └──────────┘   └──────────────┘
         │               │               │
         └───────────────┼───────────────┘
                         ▼
                  ┌──────────────┐
                  │    Broker    │
                  │ OANDA / Paper│
                  └──────────────┘
```

---

## System requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 2 GB | 8 GB |
| CPU | 2 cores | 4+ cores |
| Storage | 5 GB | 20 GB |
| Redis | Optional | Recommended |
| PostgreSQL | Optional | Recommended |

---

## License

MIT License. See [LICENSE](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE).
