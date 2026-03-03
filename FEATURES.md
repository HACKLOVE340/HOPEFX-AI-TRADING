# HOPEFX AI Trading — Feature Registry

This document is the single source of truth for every feature in the platform.
Each feature maps to an env-var that can enable or disable it at runtime
(see `config/feature_flags.py`).

**Status levels**

| Badge | Meaning |
|-------|---------|
| `STABLE` | Production-ready, on by default |
| `BETA` | Functional but still evolving, on by default |
| `EXPERIMENTAL` | Exists in code but not yet reliable, **off by default** |
| `DISABLED` | Intentionally turned off / removed from product |

---

## Diff: current branch vs `main`

> **There are currently no code differences between this branch and `main`.**
> The branch was created to investigate CI failures for PR #38.  All fixes
> had already been merged to `main` via PR #39.

---

## Core Trading

| Feature | Env Var | Default | Status | Description |
|---------|---------|---------|--------|-------------|
| Strategy Manager | `FEATURE_STRATEGY_MANAGER` | ✅ on | STABLE | Multi-strategy orchestration |
| Paper Trading | `FEATURE_PAPER_TRADING` | ✅ on | STABLE | Risk-free paper-trading simulator |
| Live Trading | `FEATURE_LIVE_TRADING` | ❌ off | STABLE | Live order execution — explicit opt-in required |
| Risk Manager | `FEATURE_RISK_MANAGER` | ✅ on | STABLE | Drawdown limits, position sizing, exposure control |

## Strategies

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| MA Crossover | `FEATURE_STRATEGY_MA_CROSSOVER` | ✅ on | STABLE |
| EMA Crossover | `FEATURE_STRATEGY_EMA_CROSSOVER` | ✅ on | STABLE |
| Bollinger Bands | `FEATURE_STRATEGY_BOLLINGER` | ✅ on | STABLE |
| Breakout | `FEATURE_STRATEGY_BREAKOUT` | ✅ on | STABLE |
| MACD | `FEATURE_STRATEGY_MACD` | ✅ on | STABLE |
| RSI | `FEATURE_STRATEGY_RSI` | ✅ on | STABLE |
| SMC / ICT | `FEATURE_STRATEGY_SMC_ICT` | ✅ on | STABLE |
| Mean Reversion | `FEATURE_STRATEGY_MEAN_REVERSION` | ✅ on | STABLE |
| Stochastic | `FEATURE_STRATEGY_STOCHASTIC` | ✅ on | STABLE |
| Strategy Brain | `FEATURE_STRATEGY_BRAIN` | ✅ on | BETA |

## Analysis & Order Flow

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Order Flow Analysis | `FEATURE_ORDER_FLOW_ANALYSIS` | ✅ on | STABLE |
| Advanced Order Flow | `FEATURE_ORDER_FLOW_ADVANCED` | ✅ on | STABLE |
| Institutional Flow | `FEATURE_INSTITUTIONAL_FLOW` | ✅ on | STABLE |
| Order Flow Dashboard | `FEATURE_ORDER_FLOW_DASHBOARD` | ✅ on | STABLE |
| Market Analysis (regime / MTF / sessions) | `FEATURE_MARKET_ANALYSIS` | ✅ on | STABLE |
| Market Scanner | `FEATURE_MARKET_SCANNER` | ✅ on | STABLE |
| Candlestick Patterns | `FEATURE_CANDLESTICK_PATTERNS` | ✅ on | STABLE |
| Dark Pool Detection | `FEATURE_DARK_POOL_DETECTION` | ✅ on | BETA |

## Data Feeds

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Time & Sales | `FEATURE_TIME_AND_SALES` | ✅ on | STABLE |
| Depth of Market | `FEATURE_DEPTH_OF_MARKET` | ✅ on | STABLE |
| Market Data Streaming | `FEATURE_MARKET_DATA_STREAMING` | ✅ on | STABLE |

## News & Sentiment

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| News Sentiment | `FEATURE_NEWS_SENTIMENT` | ✅ on | STABLE |
| Economic Calendar | `FEATURE_ECONOMIC_CALENDAR` | ✅ on | STABLE |
| Geopolitical Risk | `FEATURE_GEOPOLITICAL_RISK` | ✅ on | BETA |

## Machine Learning

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| ML Predictions (LSTM / Transformer) | `FEATURE_ML_PREDICTIONS` | ❌ off | EXPERIMENTAL |
| ML Feature Engineering | `FEATURE_ML_FEATURE_ENGINEERING` | ✅ on | STABLE |

## Charting

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Chart Engine | `FEATURE_CHART_ENGINE` | ✅ on | STABLE |
| Drawing Tools | `FEATURE_DRAWING_TOOLS` | ✅ on | STABLE |

## Backtesting

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Backtesting Engine | `FEATURE_BACKTESTING` | ✅ on | STABLE |
| Walk-Forward Optimisation | `FEATURE_WALK_FORWARD` | ✅ on | STABLE |

## Broker Connectors

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| OANDA | `FEATURE_BROKER_OANDA` | ✅ on | STABLE |
| Alpaca | `FEATURE_BROKER_ALPACA` | ✅ on | STABLE |
| Binance | `FEATURE_BROKER_BINANCE` | ✅ on | STABLE |
| MetaTrader 5 | `FEATURE_BROKER_MT5` | ✅ on | STABLE |
| Interactive Brokers | `FEATURE_BROKER_INTERACTIVE_BROKERS` | ✅ on | STABLE |

## Social & Copy Trading

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Social Trading | `FEATURE_SOCIAL_TRADING` | ✅ on | BETA |
| Copy Trading | `FEATURE_COPY_TRADING` | ✅ on | BETA |

## Monetisation

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Subscriptions | `FEATURE_SUBSCRIPTIONS` | ✅ on | STABLE |
| White-Label / Reseller | `FEATURE_WHITE_LABEL` | ✅ on | BETA |
| Enterprise | `FEATURE_ENTERPRISE` | ✅ on | BETA |
| Payments | `FEATURE_PAYMENTS` | ✅ on | STABLE |

## Mobile

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Mobile API | `FEATURE_MOBILE_API` | ✅ on | BETA |
| Push Notifications | `FEATURE_PUSH_NOTIFICATIONS` | ✅ on | BETA |

## Admin & Monitoring

| Feature | Env Var | Default | Status |
|---------|---------|---------|--------|
| Admin Dashboard | `FEATURE_ADMIN_DASHBOARD` | ✅ on | STABLE |
| Analytics Module | `FEATURE_ANALYTICS` | ✅ on | STABLE |

## Experimental / Unreleased

These features exist in the codebase and are **wired into the app** but **off by default**.
Set the corresponding env-var to `true` to enable them.  Each module registers its own
FastAPI router at startup — no code changes required.

| Feature | Env Var | Status | Routes registered when enabled |
|---------|---------|--------|-------------------------------|
| Research Module | `FEATURE_RESEARCH` | EXPERIMENTAL | `GET/POST /api/research/notebooks`, `/api/research/templates` |
| Explainability | `FEATURE_EXPLAINABILITY` | EXPERIMENTAL | `POST /api/explainability/explain`, `GET /api/explainability/history` |
| Transparency Reports | `FEATURE_TRANSPARENCY` | EXPERIMENTAL | `POST /api/transparency/executions`, `GET /api/transparency/report` |
| Teams Module | `FEATURE_TEAMS` | EXPERIMENTAL | `POST /api/teams`, `GET /api/teams/{id}`, `/api/teams/{id}/invite` |
| No-Code Builder | `FEATURE_NOCODE` | EXPERIMENTAL | `GET/POST /api/nocode/strategies`, `GET /api/nocode/indicators` |
| Replay Engine | `FEATURE_REPLAY` | EXPERIMENTAL | `POST /api/replay/sessions`, `/api/replay/sessions/{id}/play` |
| ML Predictions | `FEATURE_ML_PREDICTIONS` | EXPERIMENTAL | `GET /api/ml/status`, `POST /api/ml/features/compute` |

---

## How to enable/disable a feature

```bash
# In your .env file or shell environment:

# Disable live trading (keeps paper trading safe)
FEATURE_LIVE_TRADING=false

# Enable an experimental feature for local development
FEATURE_RESEARCH=true
FEATURE_ML_PREDICTIONS=true

# Disable a feature entirely for a lightweight deployment
FEATURE_SOCIAL_TRADING=false
FEATURE_WHITE_LABEL=false
```

```python
# In application code, gate behaviour behind a flag:
from config.feature_flags import flags

if flags.ORDER_FLOW_DASHBOARD:
    result = dashboard.get_complete_analysis("XAUUSD")

if flags.ML_PREDICTIONS:
    prediction = ml_model.predict(features)

# Log all flags at startup:
flags.log_summary()

# Inspect the full registry programmatically:
for name, info in flags.registry().items():
    print(f"{name}: {info['enabled']} ({info['status']})")
```

---

## Adding a new feature

1. Add a `_FeatureDef` entry in `config/feature_flags.py` under the
   appropriate section.
2. Add the corresponding `FEATURE_<NAME>=<default>` line to `.env.example`.
3. Add a row to the relevant table in this file.
4. Gate the feature in application code with `if flags.YOUR_FLAG:`.
5. Start with `status=FeatureStatus.EXPERIMENTAL` and `default=False` until
   the feature is tested and ready.
