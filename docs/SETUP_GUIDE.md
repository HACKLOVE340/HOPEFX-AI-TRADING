# HOPEFX — Setup Guide

> Last updated: 2026-07-14

This guide covers setting up the full data layer and execution pipeline from scratch, including subscription activation, API keys, environment variables, Redis, and the startup sequence.

---

## Architecture Overview

```
MarketDataOrchestrator  ← SINGLE SOURCE OF TRUTH for all market data
    ├── GoldFeedManager          (5 gold price APIs → consensus tick)
    ├── DataQualityEngine        (validation, anomaly detection, failover)
    ├── MicrostructureEngine     (OFI, spread, delta, Kyle's lambda)
    ├── NewsSentimentEngine      (5 news feeds, VADER scoring, EMA signal)
    ├── MacroCalendarEngine      (Finnhub calendar, gold impact scoring)
    ├── MacroStoreBridge         (FRED → macro feature store)
    ├── DataLayerRedisStore      (per-instrument TTL caching)
    ├── DataLineageStore         (immutable audit trail, SQLite/PostgreSQL)
    ├── NormalizationPipeline    (tick + OHLCV cleaning)
    └── MarketReplayEngine       (Dukascopy historical replay)

Execution Pipeline (all data from orchestrator only)
    HopeFXEngine
        ├── orchestrator.get_latest_tick()    → price, spread, quality
        ├── orchestrator.get_ml_features()    → microstructure + sentiment + macro
        ├── Gatekeeper.evaluate()             → 11-check pre-trade gate
        ├── RiskManager.size_order()          → Kelly sizing with quality scaling
        ├── SmartRouter.route_and_execute()   → OFI-aligned broker selection
        └── orchestrator.notify_fill()        → replay + cache update on fill

Brokers (order execution ONLY — no market data)
    OANDABroker   → place_order, cancel_order, get_account_info
    IBKRBroker    → place_order, cancel_order, get_account_info
```

**Invariant**: No broker connector may return price data. `get_market_data()`, `stream_prices()`, and all equivalent methods raise `MarketDataForbidden` at runtime.

---

## Prerequisites

- Python 3.10, 3.11, or 3.12
- Redis 7+ (local or remote)
- PostgreSQL 16+ (production) or SQLite (development)
- At least one gold price API key (Finnhub, Twelve Data, or Polygon for live streaming)
- OANDA practice account (for paper trading) or live broker credentials
- HOPEFX license key (from [hopefx.com/pricing](https://hopefx.com/pricing) — Free tier available at no cost)

---

## Step 0 — Subscription Activation

Every installation requires a license key. The Free tier is $0/month and activates automatically on first signup.

**New installation:**
```bash
# After starting the app for the first time, activate the Free tier:
curl -X POST http://localhost:8000/api/billing/auth/activate-free-tier \
  -H "Content-Type: application/json" \
  -d '{"user_id": "your-user-id"}'
```

**Paid plan:** After subscribing at [hopefx.com/pricing](https://hopefx.com/pricing), add your license key to `.env`:
```bash
HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX
```

Validate the key before proceeding:
```bash
python scripts/manage_secrets.py validate
# Expected: ✓ HOPEFX_LICENSE_KEY: valid (plan=professional, expires=2026-08-14)
```

Without a valid key, all `/api/trading/`, `/api/signals/`, and `/api/ml/` endpoints return `403 Subscription Required`. The `/health` and `/docs` endpoints remain accessible regardless.

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Optional: IBKR support
pip install ib_insync==0.9.86
```

---

## Step 2 — Environment Variables

```bash
cp .env.example .env
```

### Required: Redis

```env
REDIS_URL=redis://localhost:6379/0
```

Start Redis locally:
```bash
# macOS
brew install redis && brew services start redis

# Ubuntu/Debian
sudo apt install redis-server && sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### Required: Live Price Streaming

The `NuclearStreamer` in `market_data/nuclear_streamer.py` provides live XAUUSD WebSocket ticks.
Set at least one key. All configured sources run concurrently — anomalous ticks are discarded.

| API | Free Tier | Sign Up | Symbol |
|-----|-----------|---------|--------|
| Finnhub | 60 req/min | https://finnhub.io/ | `OANDA:XAU_USD` |
| Twelve Data | Free tier | https://twelvedata.com/ | `XAU/USD` |
| Polygon.io | Currencies plan | https://polygon.io/ | `C.XAU/USD` |

```env
FINNHUB_API_KEY=your_key_here
TWELVE_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here
```

Finnhub is also used by the news sentiment engine. Set it first.

### Optional: FRED Macro Data

Macro features (DXY, VIX, US10Y, US2Y, SPX, GLD) are fetched via `yfinance` — no API key required. FRED provides additional macro series:

```env
FRED_API_KEY=your_key_here   # https://fred.stlouisfed.org/docs/api/api_key.html
```

### Broker Credentials

**OANDA (paper trading — recommended for initial setup):**

1. Create a free practice account at https://www.oanda.com/
2. Go to Manage Funds → API Access → Generate token

```env
BROKER_TYPE=oanda
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001
OANDA_API_KEY=your_practice_token_here
OANDA_PRACTICE=true
OANDA_INSTRUMENTS=XAU_USD,EUR_USD
```

Note: OANDA is used for **order execution only**. Live price ticks come from `NuclearStreamer` (Finnhub/Twelve Data/Polygon), not from OANDA. See `SETUP_GUIDE.md` — Required: Live Price Streaming.

**IBKR (optional):**

1. Install TWS or IB Gateway
2. Enable API: File → Global Configuration → API → Settings → Enable ActiveX and Socket Clients

```env
IBKR_HOST=127.0.0.1
IBKR_PORT=7497          # 7497=paper TWS, 7496=live TWS, 4002=paper gateway, 4001=live gateway
IBKR_ENV=paper
IBKR_CLIENT_ID=1
```

**Bybit (XAUUSDT perpetuals — optional):**

```env
BYBIT_API_KEY=your_key_here
BYBIT_API_SECRET=your_secret_here
BYBIT_SANDBOX=true
BYBIT_DEFAULT_TYPE=linear
```

### Execution Tuning

```env
# Engine
ENGINE_MIN_CONFIDENCE=0.55
ENGINE_MIN_DATA_QUALITY=0.40
ENGINE_MAX_SPREAD_USD=2.00
ENGINE_TICK_LOOP_HZ=1.0
ENGINE_SIGNAL_COOLDOWN_S=30.0

# Risk
RISK_ACCOUNT_EQUITY=100000
RISK_MAX_POSITION_PCT=0.05
RISK_KELLY_FRACTION=0.25
RISK_MAX_DAILY_LOSS_PCT=0.05
RISK_MAX_DRAWDOWN_PCT=0.10
RISK_MAX_OPEN_POSITIONS=3

# Gatekeeper
GATEKEEPER_MIN_CONF=0.55
GATEKEEPER_MAX_DAILY_TRADES=20
GATEKEEPER_PAUSE_S=60
GATEKEEPER_SENT_BLACKOUT=0.85
GATEKEEPER_IMPACT_BLACKOUT=0.75

# Router
ROUTER_CB_ERRORS=3
ROUTER_CB_RESET_S=120
ROUTER_ORDER_TIMEOUT_S=5.0
ROUTER_MAX_SPREAD_BPS=50.0

# Lineage
LINEAGE_DB_PATH=data/lineage/lineage.db
```

---

### Live Trading Safety Gates

These must be set correctly before enabling live trading. They are enforced in code — not optional:

```env
# REQUIRED for live broker orders — must be explicitly set to "true"
# Without this, all non-paper broker connections block order execution
LIVE_MODE_CONFIRMED=false

# Leverage and margin protection
MAX_LEVERAGE_RATIO=10.0        # Block orders exceeding 10:1 leverage
MIN_MARGIN_BUFFER=2.0          # Require 200% free margin buffer

# Spread spike protection
SPREAD_SPIKE_MULTIPLIER=3.0    # Block when spread > 3× EMA baseline
SPREAD_ABS_LIMIT_USD=5.0       # Absolute spread limit (always blocks)

# SL/TP monitor
SLTP_POLL_INTERVAL_MS=200      # Check SL/TP every 200ms
```

Set `LIVE_MODE_CONFIRMED=true` only after completing the 30-day paper trading run. See [live_trading_gate.md](live_trading_gate.md).

---

## Step 3 — Database Setup

### Development (SQLite — zero config)

The lineage store defaults to `data/lineage/lineage.db`. No setup needed.

### Production (PostgreSQL)

```bash
docker run -d \
  -e POSTGRES_USER=hopefx \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=hopefx \
  -p 5432:5432 \
  postgres:14-alpine

# .env
DATABASE_URL=postgresql+asyncpg://hopefx:your_password@localhost:5432/hopefx

alembic upgrade head
```

---

## Step 4 — Verify Data Layer

```bash
python -c "
import asyncio
from data_layer.orchestrator import orchestrator

async def test():
    await orchestrator.start()
    await asyncio.sleep(5)
    tick = orchestrator.get_latest_tick()
    if tick:
        print(f'Tick OK: {tick.symbol} mid={tick.mid:.2f} quality={tick.quality.value} conf={tick.confidence:.3f}')
    else:
        print('No tick — check API keys')
    features = orchestrator.get_ml_features()
    print(f'Features: {len(features)} keys')
    print(f'Safe to trade: {orchestrator.is_safe_to_trade()}')
    health = orchestrator.health()
    print(f'Active feeds: {list(health[\"gold_feeds\"].keys())}')
    await orchestrator.stop()

asyncio.run(test())
"
```

Expected output:
```
Tick OK: XAU_USD mid=1923.45 quality=good conf=0.987
Features: 26 keys
Safe to trade: True
Active feeds: ['goldapi', 'metals_dev']
```

---

## Step 5 — Start the Full System

### Standalone process

```bash
python -m execution.execution
```

### Programmatic

```python
import asyncio
from execution.execution import ExecutionSystem

async def main():
    def my_inference(features: dict) -> tuple:
        # returns (direction, confidence, probability)
        return "neutral", 0.0, 0.5

    system = ExecutionSystem(ml_inference_fn=my_inference)
    await system.start()

    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await system.stop()

asyncio.run(main())
```

### FastAPI integration

```python
from fastapi import FastAPI
from execution.execution import ExecutionSystem

app = FastAPI()
system = ExecutionSystem()

@app.on_event("startup")
async def startup():
    await system.start()

@app.on_event("shutdown")
async def shutdown():
    await system.stop()

@app.get("/health")
def health():
    return system.health()
```

---

## Step 6 — Wiring Your ML Model

```python
from execution.execution import ExecutionSystem

def my_model(features: dict) -> tuple:
    """
    features keys (from orchestrator):
      Microstructure: order_flow_imbalance, trade_pressure, spread,
                      buy_pressure, sell_pressure, cumulative_delta, vwap
      Sentiment:      news_sentiment_score, news_sentiment_momentum,
                      news_article_count_1h, news_bullish_ratio
      Macro/Calendar: macro_impact_score, hours_to_next_event
      FRED:           dxy_level, us10y_yield, vix_level, cpi_yoy, ...
    """
    ofi  = features.get("order_flow_imbalance", 0.0)
    sent = features.get("news_sentiment_score", 0.0)
    # ... your model logic ...
    return "long", 0.72, 0.68   # direction, confidence, probability

system = ExecutionSystem(ml_inference_fn=my_model)
```

---

## Data Flow Reference

| Component | Data Access | Method |
|-----------|-------------|--------|
| HopeFXEngine | Tick price, spread, quality | `orchestrator.get_latest_tick()` |
| HopeFXEngine | ML features | `orchestrator.get_ml_features()` |
| HopeFXEngine | Safety gate | `orchestrator.is_safe_to_trade()` |
| RiskManager | Data quality | `orchestrator.get_latest_tick().confidence` |
| RiskManager | Sentiment, macro | `orchestrator.get_ml_features()` |
| Gatekeeper | Data quality | `orchestrator.get_latest_tick().confidence` |
| Gatekeeper | News blackout | `orchestrator.is_safe_to_trade()` |
| Gatekeeper | Impact score | `orchestrator.get_current_impact_score()` |
| Gatekeeper | Sentiment | `orchestrator.get_ml_features()` |
| SmartRouter | OFI, sentiment | From order_request (populated by engine from orchestrator) |
| OANDABroker | **NONE** — raises `MarketDataForbidden` | — |
| IBKRBroker | **NONE** — raises `MarketDataForbidden` | — |

---

## Lineage Audit Trail

Every event written to `DataLineageStore`:

| Event | Record Type | Written By |
|-------|-------------|------------|
| Validated tick | `TICK` | Orchestrator tick loop |
| News article | `NEWS` | NewsSentimentEngine |
| Macro event | `MACRO` | MacroCalendarEngine |
| ML signal generated | `SIGNAL` | HopeFXEngine |
| Gate rejection | `SIGNAL` (GATE_BLOCK) | Gatekeeper |
| Position sizing | `SIGNAL` (SIZE) | RiskManager |
| Routing decision | `SIGNAL` (ROUTE) | SmartRouter |
| Fill confirmed | `SIGNAL` (FILL) | HopeFXEngine |
| Fill rejected | `SIGNAL` (REJECT) | HopeFXEngine |

---

## Troubleshooting

**No tick from orchestrator:**
- Check at least one gold API key is set in `.env`
- Verify Redis: `redis-cli ping` → `PONG`
- Check logs: `grep "GoldFeedManager" hopefx.log`

**Data quality below threshold:**
- Multiple feeds improve consensus confidence
- Temporarily set `DQE_MIN_CONFIDENCE=0.20` to diagnose
- Check `orchestrator.health()["dqe"]` for per-source scores

**Gatekeeper blocking all trades:**
- Check `system.health()["gatekeeper"]` for block reasons
- Common: `news_blackout`, `data_quality_low`, `low_confidence`
- Verify `GATEKEEPER_MIN_CONF` matches your model's output range

**OANDA connection refused:**
- Verify `OANDA_ACCOUNT_ID` and `OANDA_API_TOKEN` are set
- Test: `curl -H "Authorization: Bearer $OANDA_API_TOKEN" https://api-fxpractice.oanda.com/v3/accounts`

**IBKR not connecting:**
- TWS/Gateway must be running before the system starts
- API connections must be enabled in TWS settings

**MarketDataForbidden raised:**
- A broker method that returns price data was called
- Replace the call with `orchestrator.get_latest_tick()` or `orchestrator.get_ml_features()`
- This is an architectural violation — fix it, do not suppress it
