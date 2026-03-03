# HOPEFX-AI-TRADING — WORDMAP
> **Single Source of Truth** for the entire project.  
> Every module, route, agent, strategy, price function, and hidden component catalogued here.  
> _Last generated: 2026-03-03_

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Directory Tree](#directory-tree)
3. [API Routes (108 endpoints)](#api-routes)
4. [Core Modules](#core-modules)
5. [Strategies (10 implementations)](#strategies)
6. [AI Bot & Signals](#ai-bot--signals)
7. [Market Data & Price Functions](#market-data--price-functions)
8. [Dashboard Components](#dashboard-components)
9. [Broker Integrations](#broker-integrations)
10. [ML / AI Models](#ml--ai-models)
11. [Risk Management](#risk-management)
12. [Backtesting Engine](#backtesting-engine)
13. [Monetization & Payments](#monetization--payments)
14. [Analytics & Research](#analytics--research)
15. [Notifications & Alerts](#notifications--alerts)
16. [Social & Copy Trading](#social--copy-trading)
17. [Mobile API](#mobile-api)
18. [Database Models](#database-models)
19. [Configuration](#configuration)
20. [Security](#security)
21. [Testing Infrastructure](#testing-infrastructure)
22. [Known Random/Simulated Data Locations](#randomsimulated-data)

---

## Project Overview

| Field | Value |
|---|---|
| **Name** | HOPEFX AI Trading |
| **Focus** | XAU/USD (Gold) + Multi-asset AI trading framework |
| **Language** | Python 3.8+ |
| **Framework** | FastAPI (REST API) + Jinja2 (dashboard templates) |
| **ML** | TensorFlow 2.15, PyTorch 2.1, scikit-learn 1.3 |
| **Data Source** | Yahoo Finance (yfinance) — live, no random prices |
| **Broker Support** | Paper, Alpaca, Binance, OANDA, IBKR, MT5 |
| **Market Data** | yfinance (GC=F for XAUUSD, BTC-USD, EURUSD=X, etc.) |
| **Real-time** | WebSocket server + Server-Sent Events |
| **Auth** | Config-based with encryption (Fernet) |

---

## Directory Tree

```
HOPEFX-AI-TRADING/
├── app.py                          ← FastAPI application entry point
├── main.py                         ← CLI entry point
├── cli.py                          ← Command-line interface
├── setup.py                        ← Package setup
├── requirements.txt                ← Production dependencies
├── WORDMAP.md                      ← THIS FILE — project documentation map
├── WORDMAP.json                    ← Machine-readable version of this map
│
├── api/                            ← REST API routers
│   ├── admin.py                    ← Admin dashboard endpoints + HTML pages
│   ├── trading.py                  ← Trading strategies, market data, regime
│   ├── signals.py                  ← Real-Time Signal Service (REST + alerts)
│   ├── monetization.py             ← Subscriptions, pricing, affiliates
│   └── websocket_server.py         ← WebSocket manager + channels
│
├── strategies/                     ← 10 trading strategy implementations
│   ├── base.py                     ← BaseStrategy, Signal, SignalType
│   ├── manager.py                  ← StrategyManager (register/start/stop)
│   ├── strategy_brain.py           ← StrategyBrain (multi-strategy consensus)
│   ├── ma_crossover.py             ← Moving Average Crossover
│   ├── ema_crossover.py            ← EMA Crossover
│   ├── mean_reversion.py           ← Mean Reversion (Bollinger Bands)
│   ├── rsi_strategy.py             ← RSI Oscillator
│   ├── bollinger_bands.py          ← Bollinger Bands
│   ├── macd_strategy.py            ← MACD Momentum
│   ├── breakout.py                 ← Breakout Strategy
│   ├── stochastic.py               ← Stochastic Oscillator
│   ├── smc_ict.py                  ← Smart Money Concepts (ICT)
│   └── its_8_os.py                 ← ICT 8 Optimal Setups
│
├── analysis/                       ← Advanced market analysis
│   ├── market_analysis.py          ← MarketRegimeDetector, SessionAnalyzer, MTF
│   ├── order_flow.py               ← OrderFlowAnalyzer, VolumeProfile, Footprint
│   ├── advanced_order_flow.py      ← AggressionMetrics, DeltaDivergence, Oscillator
│   ├── institutional_flow.py       ← InstitutionalFlowDetector (large orders)
│   ├── market_scanner.py           ← MarketScanner (opportunity detection)
│   ├── order_flow_dashboard.py     ← OrderFlowDashboard (REST API)
│   └── patterns/                   ← Chart + candlestick + S/R pattern detection
│
├── ml/                             ← Machine learning models
│   ├── models/
│   │   ├── base.py                 ← BaseMLModel
│   │   ├── lstm.py                 ← LSTMPricePredictor
│   │   ├── random_forest.py        ← RandomForestTradingClassifier
│   │   └── ensemble.py             ← EnsembleModel
│   ├── features/
│   │   └── technical.py            ← TechnicalFeatureEngineer
│   ├── training/                   ← Training pipeline
│   └── evaluation/                 ← Model evaluation metrics
│
├── brokers/                        ← Multi-broker integration
│   ├── base.py                     ← BaseBroker interface
│   ├── paper_trading.py            ← PaperTradingBroker (uses real prices via API)
│   ├── alpaca.py                   ← AlpacaBroker
│   ├── binance.py                  ← BinanceBroker
│   ├── oanda.py                    ← OandaBroker (Forex)
│   ├── interactive_brokers.py      ← IBKR integration
│   ├── mt5.py                      ← MetaTrader 5
│   ├── advanced_orders.py          ← OCO, Trailing Stop, Bracket orders
│   ├── factory.py                  ← BrokerFactory
│   └── prop_firms/                 ← FTMO, MyForexFunds, The5ers, TopStep
│
├── risk/                           ← Risk management engine
│   ├── manager.py                  ← RiskManager (position sizing, drawdown)
│   └── advanced_analytics.py       ← VaR, CVaR, Monte Carlo (seeded)
│
├── notifications/                  ← Alert & notification system
│   ├── alert_engine.py             ← AlertEngine (price/signal alerts)
│   └── manager.py                  ← NotificationManager (email, push, webhook)
│
├── backtesting/                    ← Backtesting engine
│   ├── engine.py                   ← BacktestEngine
│   ├── data_handler.py             ← Historical data loader
│   ├── data_sources.py             ← Data source connectors
│   ├── metrics.py                  ← Sharpe, Sortino, Calmar ratios
│   ├── optimizer.py                ← Walk-forward optimization
│   ├── walk_forward.py             ← Walk-forward analysis
│   ├── portfolio.py                ← Portfolio tracker
│   ├── reports.py                  ← Report generation
│   └── plots.py                    ← Performance charts
│
├── analytics/                      ← Performance analytics
│   ├── performance.py              ← Trade performance metrics
│   ├── portfolio.py                ← Portfolio analytics
│   ├── risk.py                     ← Risk metrics
│   ├── options.py                  ← Options analytics
│   └── simulations.py              ← Monte Carlo simulations (legitimate use)
│
├── data/                           ← Live data streaming
│   ├── streaming.py                ← DataStreamingService
│   ├── depth_of_market.py          ← DOM (Level 2) data
│   └── time_and_sales.py           ← Time & Sales tape
│
├── cache/
│   └── market_data_cache.py        ← MarketDataCache (TTL, multi-timeframe)
│
├── database/
│   └── models.py                   ← SQLAlchemy models (Trade, Position, etc.)
│
├── config/
│   └── config_manager.py           ← ConfigManager + EncryptionManager (Fernet)
│
├── charting/                       ← Chart engine & indicators
│   ├── chart_engine.py             ← ChartEngine
│   ├── indicators.py               ← 50+ technical indicators
│   ├── drawing_tools.py            ← Trendlines, Fibonacci, Patterns
│   ├── templates.py                ← Chart layout templates
│   └── timeframes.py               ← Timeframe conversion utilities
│
├── monetization/                   ← Subscription & payment system
│   ├── subscription.py             ← SubscriptionManager
│   ├── pricing.py                  ← PricingTierManager
│   ├── access_codes.py             ← AccessCodeManager
│   ├── affiliate.py                ← AffiliateProgram
│   ├── commission.py               ← CommissionTracker
│   ├── enterprise.py               ← EnterpriseManager
│   ├── marketplace.py              ← StrategyMarketplace
│   ├── analytics.py                ← MonetizationAnalytics
│   ├── payment_processor.py        ← PaymentProcessor
│   ├── stripe_integration.py       ← Stripe webhooks
│   ├── license.py                  ← LicenseManager
│   └── invoices.py                 ← InvoiceGenerator
│
├── payments/                       ← Multi-payment gateway
│   ├── payment_gateway.py          ← PaymentGateway router
│   ├── transaction_manager.py      ← TransactionManager
│   ├── wallet.py                   ← WalletManager
│   ├── security.py                 ← Payment security
│   ├── crypto/                     ← Bitcoin, Ethereum, USDT
│   └── fintech/                    ← Flutterwave, Paystack, Bank Transfer
│
├── social/                         ← Social trading
│   ├── copy_trading.py             ← CopyTradingEngine
│   ├── leaderboards.py             ← PerformanceLeaderboard
│   ├── profiles.py                 ← TraderProfiles
│   ├── marketplace.py              ← StrategyMarketplace (social layer)
│   └── performance.py              ← Social performance metrics
│
├── mobile/                         ← Mobile app API
│   ├── api.py                      ← MobileAPIRouter
│   ├── auth.py                     ← JWT auth for mobile
│   ├── trading.py                  ← Mobile trading endpoints
│   ├── push_notifications.py       ← Push notification service
│   └── analytics.py                ← Mobile analytics
│
├── research/
│   └── __init__.py                 ← Jupyter-style research notebook templates
│
├── replay/
│   └── __init__.py                 ← Trade replay engine
│
├── explainability/
│   └── __init__.py                 ← AI decision explainability (SHAP-style)
│
├── nocode/                         ← No-code strategy builder
├── teams/                          ← Multi-user teams
├── transparency/                   ← Audit trail & transparency reports
│
├── utils/
│   ├── component_status.py         ← ComponentStatusChecker
│   └── security.py                 ← SecurityUtils (XSS, CSRF, rate limiting)
│
├── templates/                      ← Jinja2 HTML templates
│   ├── base.html                   ← Shared layout + navigation sidebar
│   ├── paper_trading.html          ← Paper trading dashboard (real prices via API)
│   ├── pricing.html                ← Subscription pricing page
│   └── admin/
│       ├── dashboard.html          ← Main admin dashboard (AI Bot, Regime panels)
│       ├── strategies.html         ← Strategy management (all 10 types)
│       ├── monitoring.html         ← System monitoring
│       └── settings.html           ← Risk & system settings
│
└── tests/
    ├── conftest.py                 ← Pytest fixtures
    ├── unit/                       ← 30+ unit test modules (701 tests)
    └── integration/                ← Integration tests
```

---

## API Routes

### Admin (prefix: `/admin`)
| Method | Path | Description |
|---|---|---|
| GET | `/admin/` | Admin dashboard HTML |
| GET | `/admin/strategies` | Strategies management HTML |
| GET | `/admin/monitoring` | System monitoring HTML |
| GET | `/admin/settings` | Settings HTML |
| GET | `/admin/api/system-info` | System health info |
| GET | `/admin/api/dashboard-data` | Full dashboard data |
| GET | `/admin/api/settings` | Current settings |
| POST | `/admin/api/settings` | Save settings |
| GET | `/admin/api/system-metrics` | CPU, memory, uptime |
| GET | `/admin/api/widgets` | Dashboard widget data |
| GET | `/admin/api/activity` | Recent activity log |
| GET | `/admin/api/component-map` | All component status |

### Trading (prefix: `/api/trading`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/trading/strategies` | Create strategy (all 10 types) |
| GET | `/api/trading/strategies` | List all strategies |
| GET | `/api/trading/strategies/{name}` | Get single strategy |
| POST | `/api/trading/strategies/{name}/start` | Start strategy |
| POST | `/api/trading/strategies/{name}/stop` | Stop strategy |
| DELETE | `/api/trading/strategies/{name}` | Delete strategy |
| POST | `/api/trading/strategies/start-all` | Start all |
| POST | `/api/trading/strategies/stop-all` | Stop all |
| POST | `/api/trading/position-size` | Calculate position size |
| GET | `/api/trading/risk-metrics` | Risk metrics |
| GET | `/api/trading/performance/summary` | Performance summary |
| GET | `/api/trading/performance/{name}` | Per-strategy performance |
| GET | `/api/trading/market-price/{symbol}` | **LIVE price** (yfinance) |
| GET | `/api/trading/market-ohlcv/{symbol}` | **LIVE OHLCV** (yfinance) |
| GET | `/api/trading/market-regime/{symbol}` | **LIVE market regime** |
| GET | `/api/trading/strategy-types` | All available strategy types |
| GET | `/api/trading/strategy-brain/stats` | StrategyBrain statistics |
| POST | `/api/trading/strategy-brain/analyze` | Joint multi-strategy analysis |
| GET | `/api/trading/component-map` | Full component map |

### Signals (prefix: `/api/signals`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/signals/summary` | AI Bot signal summary |
| GET | `/api/signals/active` | Currently active signals |
| GET | `/api/signals/history` | Signal history (last N hours) |
| POST | `/api/signals/generate` | Generate signal from price |
| GET | `/api/signals/analytics` | Signal analytics |
| POST | `/api/signals/alerts` | Create signal alert |
| GET | `/api/signals/alerts` | List alerts |
| DELETE | `/api/signals/alerts/{id}` | Delete alert |
| GET | `/api/signals/channels` | WebSocket channel list |

### Monetization (prefix: `/api/monetization`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/monetization/pricing` | Pricing tiers |
| POST | `/api/monetization/subscribe` | Subscribe |
| POST | `/api/monetization/activate-code` | Activate access code |
| GET | `/api/monetization/analytics/dashboard` | Revenue analytics |
| POST | `/api/monetization/affiliate/signup` | Join affiliate |
| GET | `/api/monetization/marketplace/strategies` | Strategy marketplace |

### System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Full system status |
| GET | `/docs` | Swagger/OpenAPI UI |
| GET | `/redoc` | ReDoc UI |

---

## Core Modules

### `app.py` — Application Entry Point
- `FastAPI` application factory
- Startup: registers ALL optional routers with graceful degradation
- Routers registered: Trading, Admin, Monetization, WebSocket, Alerts, Order Flow, Market Scanner, DOM, **Signals** (new)
- CORS configured for development
- DB session management

### `config/config_manager.py`
- `ConfigManager` — YAML config loader with environment variable overrides
- `EncryptionManager` — Fernet-based encryption for API keys

---

## Strategies

| Type Key | Class | Description |
|---|---|---|
| `ma_crossover` | `MovingAverageCrossover` | SMA fast/slow crossover |
| `ema_crossover` | `EMAcrossoverStrategy` | EMA fast/slow crossover |
| `mean_reversion` | `MeanReversionStrategy` | Bollinger Band mean reversion |
| `rsi` | `RSIStrategy` | RSI overbought/oversold |
| `bollinger_bands` | `BollingerBandsStrategy` | Bollinger Band squeeze/expansion |
| `macd` | `MACDStrategy` | MACD histogram divergence |
| `breakout` | `BreakoutStrategy` | Support/Resistance breakout |
| `stochastic` | `StochasticStrategy` | Stochastic K/D crossover |
| `smc_ict` | `SMCICTStrategy` | Smart Money Concepts (ICT): OB, FVG, BOS, CHoCh |
| `its_8_os` | `ITS8OSStrategy` | ICT 8 Setups: AMD, Power of 3, Kill Zones, Silver Bullet |

### `StrategyBrain` — Multi-Strategy Intelligence
- Weighted consensus across all registered strategies
- Performance-based weight adjustment
- Endpoints: `GET /api/trading/strategy-brain/stats`, `POST /api/trading/strategy-brain/analyze`

---

## AI Bot & Signals

### `api/signals.py` — `RealTimeSignalService`
Previously hidden (implemented but not exposed). Now fully wired with REST API.

**Key classes:**
- `TradingSignal` — signal with direction, strength (0-1), confidence, entry/SL/TP
- `SignalStrength` — `VERY_STRONG / STRONG / MODERATE / WEAK / VERY_WEAK`
- `SignalDirection` — `BUY / SELL / HOLD`
- `SignalAlert` — configurable price/direction alert
- `SignalAnalytics` — running win rate, direction distribution
- `RealTimeSignalService` — main service class

**Functions:**
- `generate_signal(symbol, strategies, price, timeframe, regime, session)`
- `get_active_signals(symbol?)` — currently live signals
- `get_signal_history(symbol?, hours)` — past signals
- `create_alert(symbol, direction, min_confidence)` — create alert
- `get_analytics()` — win rates & stats
- `format_for_websocket(signal)` — WebSocket-ready JSON

---

## Market Data & Price Functions

### ⚠️ Zero Random Price Mandate — Compliance Status

| Location | Status | Notes |
|---|---|---|
| `api/trading.py` → `get_market_price` | ✅ LIVE | yfinance fetch, 5-min TTL cache |
| `api/trading.py` → `get_market_ohlcv` | ✅ LIVE | yfinance historical data |
| `api/trading.py` → `get_market_regime` | ✅ LIVE | MarketRegimeDetector + yfinance |
| `templates/paper_trading.html` → `updatePrices()` | ✅ LIVE | Polls `/api/trading/market-price/` |
| `templates/paper_trading.html` → `updateChart()` | ✅ LIVE | Polls `/api/trading/market-ohlcv/` |
| `templates/paper_trading.html` → `_renderFallbackChart()` | ✅ FIXED | Now shows "data unavailable" annotation |
| `analytics/simulations.py` | ✅ LEGITIMATE | Monte Carlo simulation (by design) |
| `risk/advanced_analytics.py` | ✅ LEGITIMATE | Monte Carlo VaR/CVaR (seeded, reproducible) |
| `research/__init__.py` | ✅ FIXED | Uses `np.random.default_rng(seed=42)` with clear "preview only" comment |
| `backtesting/` | ✅ LEGITIMATE | Uses historical real data via `data_handler.py` |
| `replay/__init__.py` | ✅ LEGITIMATE | Trade replay uses stored historical data |

### Symbol Map (UI → yfinance ticker)
| UI Symbol | yfinance Ticker |
|---|---|
| XAUUSD | GC=F (Gold Futures) |
| EURUSD | EURUSD=X |
| BTCUSD | BTC-USD |
| SPY | SPY |
| USDJPY | USDJPY=X |
| GBPUSD | GBPUSD=X |
| USDCHF | USDCHF=X |
| AUDUSD | AUDUSD=X |

---

## Dashboard Components

### Admin Dashboard (`/admin/`)
- **System Health** — version, uptime, status badge
- **Trading KPIs** — total/active strategies, P&L, win rate, positions, signals
- **Risk Gauges** — drawdown bar, risk utilization, daily loss limit
- **Market Prices** — LIVE XAU/USD and BTC/USD (DOM construction, XSS-safe)
- **🤖 AI Bot & Signals** — active signals, 24h count, buy/sell split, avg confidence (NEW)
- **📊 Market Regime** — XAU/USD regime, direction, volatility %ile (NEW)
- **Module Status Grid** — all 16 modules with green/amber/red status
- **Quick Actions** — Start All, Stop All, Paper Trading, Strategies, Monitoring, etc.
- **Activity Feed** — recent system events

### Paper Trading Dashboard (`/paper-trading`)
- Symbol selector (XAUUSD, BTCUSD, EURUSD, GBPUSD)
- Real-time price display (polls every 10s from live API)
- Order entry (market/limit, buy/sell)
- Open positions table with live P&L
- Account equity / margin tracking
- Live Plotly candlestick chart (real OHLCV data from API)
- Fallback: shows "data unavailable" annotation (no fake candles)

---

## Broker Integrations

| Broker | Class | Sandbox | Live |
|---|---|---|---|
| Paper Trading | `PaperTradingBroker` | ✅ | N/A |
| Alpaca | `AlpacaBroker` | ✅ | ✅ |
| Binance | `BinanceBroker` | ✅ | ✅ |
| OANDA | `OandaBroker` | ✅ | ✅ |
| Interactive Brokers | `InteractiveBrokersBroker` | ✅ | ✅ |
| MetaTrader 5 | `MT5Broker` | ✅ | ✅ |
| FTMO (Prop) | `FTMOBroker` | ✅ | ✅ |
| MyForexFunds | `MyForexFundsBroker` | ✅ | ✅ |
| The5ers | `The5ersBroker` | ✅ | ✅ |
| TopStep | `TopStepBroker` | ✅ | ✅ |

---

## ML / AI Models

| Model | Class | Purpose |
|---|---|---|
| LSTM | `LSTMPricePredictor` | Price direction prediction (TensorFlow) |
| Random Forest | `RandomForestTradingClassifier` | Signal classification (scikit-learn) |
| Ensemble | `EnsembleModel` | Combined model voting |
| Features | `TechnicalFeatureEngineer` | 50+ technical indicator features |

---

## Risk Management

### `risk/manager.py` — `RiskManager`
- Position sizing (Kelly Criterion, fixed fractional)
- Max drawdown enforcement
- Daily loss limit tracking
- Correlation-aware portfolio risk
- Per-trade risk calculation

### `risk/advanced_analytics.py`
- Value at Risk (VaR) — Historical & Parametric
- Conditional VaR (CVaR / Expected Shortfall)
- Monte Carlo portfolio simulation (seeded for reproducibility)
- Stress testing
- Correlation analysis

---

## Backtesting Engine

### `backtesting/engine.py` — `BacktestEngine`
- Event-driven architecture
- Walk-forward optimization
- Multi-strategy backtesting
- Transaction cost modeling
- Slippage simulation

### Metrics: Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Profit Factor

---

## Monetization & Payments

### Subscription Tiers
- Free / Basic / Pro / Elite / Institutional

### Payment Methods
- Stripe (credit card, webhook)
- Crypto: Bitcoin, Ethereum, USDT
- Fintech: Flutterwave, Paystack, Bank Transfer

---

## Notifications & Alerts

### `notifications/alert_engine.py` — `AlertEngine`
- Price alerts (above/below threshold)
- Signal alerts (direction + confidence threshold)
- Strategy event alerts
- WebSocket + REST delivery

### `notifications/manager.py` — `NotificationManager`
- Email, SMS, Push, Webhook channels
- Rate limiting and delivery tracking

---

## Random/Simulated Data

> **All locations below are LEGITIMATE uses of random numbers.**  
> Zero random prices in any production data flow or UI.

| File | Type | Legitimacy |
|---|---|---|
| `analytics/simulations.py` | Monte Carlo | ✅ Statistical simulation |
| `risk/advanced_analytics.py` | Monte Carlo VaR | ✅ Seeded (seed=42), reproducible |
| `research/__init__.py` | Notebook template preview | ✅ Seeded (seed=42), clearly documented |
| `replay/__init__.py` | Replay simulation | ✅ Uses stored historical data |
| `backtesting/` | Backtest simulation | ✅ Uses real historical data |
| Tests (`tests/`) | Mock data | ✅ Unit test fixtures |

---

## Configuration

### `.env` variables (set via `.env.example`)
- `CONFIG_ENCRYPTION_KEY` — Fernet key for credential encryption
- `ALPHA_VANTAGE_KEY` — Optional enhanced market data
- `REDIS_URL` — Cache backend (falls back to in-memory)
- `DATABASE_URL` — SQLAlchemy database URL

---

## Testing Infrastructure

- **Framework:** pytest + pytest-asyncio
- **Test count:** 701 tests across 30+ test modules
- **Coverage areas:** All strategies, brokers, analytics, ML, risk, notifications, charting, database, config, security, social, mobile
- **Run:** `pytest tests/unit/` (all 701 pass)

---

## Agent Orchestration

All agents operate as Python classes/services coordinated through the FastAPI application:

| Agent | Implementation | Status |
|---|---|---|
| **StrategyBrain** | `strategies/strategy_brain.py` | ✅ Active + REST API |
| **RealTimeSignalService** | `api/signals.py` | ✅ Active + REST API |
| **MarketRegimeDetector** | `analysis/market_analysis.py` | ✅ Active + REST API |
| **OrderFlowAnalyzer** | `analysis/order_flow.py` | ✅ Active + REST API |
| **MarketScanner** | `analysis/market_scanner.py` | ✅ Active + REST API |
| **InstitutionalFlowDetector** | `analysis/institutional_flow.py` | ✅ Active + REST API |
| **AdvancedOrderFlowAnalyzer** | `analysis/advanced_order_flow.py` | ✅ Active + REST API |
| **AlertEngine** | `notifications/alert_engine.py` | ✅ Active + REST API |
| **RiskManager** | `risk/manager.py` | ✅ Active |
| **LSTMPricePredictor** | `ml/models/lstm.py` | ✅ Implemented |
| **RandomForestClassifier** | `ml/models/random_forest.py` | ✅ Implemented |

---

_This WordMap is auto-generated from code analysis. Update by re-running the generation script or editing this file directly._
