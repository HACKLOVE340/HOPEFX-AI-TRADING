# HOPEFX Documentation

**AI-powered gold and forex trading platform.**
Automated strategies, real-time signals, and institutional-grade risk management.

---

## What is HOPEFX?

HOPEFX is a self-hosted algorithmic trading framework that combines:

- **Machine learning** — XGBoost stacking ensemble (176 features, 66.4% OOS accuracy, p=0.0000) with incremental online learning (SGD + EWC, hourly updates)
- **Strategy engine** — 10 built-in strategies (MA crossover, EMA crossover, RSI, MACD, Bollinger Bands, SMC/ICT, mean reversion, breakout, stochastic, Strategy Brain)
- **Risk management** — per-trade position sizing, CVaR gate, daily loss limits, max drawdown circuit breakers, kill switch, prop-firm compliance mode
- **Broker integration** — OANDA (practice + live), Interactive Brokers, Alpaca, Binance, MT5, paper trading simulator, FIX 4.4 adapter
- **Multi-symbol backtesting** — walk-forward validation across 7 symbols (XAU/USD, BTC/USD, ETH/USD, EUR/USD, GBP/USD, Silver, Oil); N>919 trades, SE≤0.10 gate satisfied
- **REST API** — 108 endpoints covering signals, broker, ML, backtest, social, payments, mobile
- **Multi-channel alerts** — Discord, Telegram, email, Sentry

---

## Quick Navigation

### Getting Started
| I want to… | Go to |
|---|---|
| Install HOPEFX | [Installation](INSTALLATION.md) |
| Run my first backtest | [Quick Start](QUICKSTART.md) |
| Connect OANDA | [OANDA Paper Trading Setup](oanda_paper_trading_setup.md) |
| Set up a broker | [Setup Guide](SETUP_GUIDE.md) |
| Understand the architecture | [Architecture](architecture.md) |

### Trading & Strategies
| I want to… | Go to |
|---|---|
| Browse built-in strategies | [Sample Strategies](SAMPLE_STRATEGIES.md) |
| Understand order flow | [Order Flow Guide](ORDER_FLOW_GUIDE.md) |
| Run a backtest | [Backtesting Guide](BACKTESTING_GUIDE.md) |
| Diversify across assets | [Asset Diversification](ASSET_DIVERSIFICATION.md) |
| Trade with a prop firm | [Prop Firm Guide](PROP_FIRM_GUIDE.md) |

### ML & AI
| I want to… | Go to |
|---|---|
| Understand the ML model | [Model Performance](model_performance.md) |
| Train or retrain the model | [ML Guide](ML_GUIDE.md) |
| Read the ML pipeline | [Architecture — ML section](architecture.md) |

### Risk & Live Trading
| I want to… | Go to |
|---|---|
| Configure risk limits | [Risk Management](RISK_MANAGEMENT.md) |
| Enable live trading | [Live Trading Gate](live_trading_gate.md) |
| Understand security | [Security](SECURITY.md) |

### API & Integration
| I want to… | Go to |
|---|---|
| Read the full API reference | [API Reference](API_REFERENCE.md) |
| Integrate mobile | [Mobile Guide](MOBILE_GUIDE.md) |
| Set up webhooks/alerts | [API Guide](API_GUIDE.md) |
| World Monitor geopolitical data | [World Monitor Integration](WORLD_MONITOR_INTEGRATION.md) |

### Operations
| I want to… | Go to |
|---|---|
| Deploy to production | [Deployment](DEPLOYMENT.md) |
| Set up monitoring | [Grafana Setup](GRAFANA_SETUP.md) |
| Debug issues | [Debugging](DEBUGGING.md) |
| Fix common problems | [Troubleshooting](TROUBLESHOOTING.md) |
| Get answers | [FAQ](FAQ.md) |

### Monetization & Community
| I want to… | Go to |
|---|---|
| Set up subscriptions/payments | [Monetization](MONETIZATION.md) |
| Join the community | [Community](COMMUNITY.md) |
| Contribute code | [Contributing](CONTRIBUTING.md) |
| Read the roadmap | [Roadmap](roadmap.md) |
| Watch video tutorials | [Video Tutorials](VIDEO_TUTORIALS.md) |

---

## Architecture Overview

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

See [Architecture](architecture.md) for the full module map and startup sequence.

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 4 GB | 8 GB |
| CPU | 2 cores | 4+ cores |
| Storage | 10 GB | 20 GB |
| Redis 7+ | Optional | Recommended |
| PostgreSQL 16+ | Optional | Recommended |

---

## Current Status

| Component | Status |
|---|---|
| ML model (`advanced_oos.pkl`) | ✅ 66.4% OOS accuracy, p=0.0000, 176 features |
| Multi-symbol backtest | ✅ N>919 trades, SE≤0.10 gate satisfied |
| Risk engine | ✅ CVaR gate, kill switch, drawdown circuit breaker |
| OANDA paper broker | ✅ Stable — 30-day paper run completed |
| REST + WebSocket API | ✅ 108 endpoints, stable |
| Test suite | ✅ 2,560+ tests, CI green |
| Online learning | ✅ SGD + EWC, enable with `ML_HOURLY_ENABLED=true` |

---

## License

AGPL-3.0. See [LICENSE](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE).
Commercial use requires a separate license — see [LICENSE-COMMERCIAL.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE-COMMERCIAL.md).
