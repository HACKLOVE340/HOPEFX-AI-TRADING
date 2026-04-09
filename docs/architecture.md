# HOPEFX AI Trading — System Architecture

> Last updated: 2026-07-14 (v1.17)

---

## Contents

1. [Overview](#overview)
2. [Entry Point & Startup](#entry-point--startup)
3. [Data Layer](#data-layer)
4. [Signal Engine](#signal-engine)
5. [ML Pipeline](#ml-pipeline)
6. [Risk Engine](#risk-engine)
7. [Execution Engine](#execution-engine)
8. [Broker Connectors](#broker-connectors)
9. [API Layer](#api-layer)
10. [Subscription & Access Control](#subscription--access-control)
11. [Notifications & Alerts](#notifications--alerts)
12. [Observability](#observability)
13. [Infrastructure](#infrastructure)
14. [Data Flow — End to End](#data-flow--end-to-end)
15. [Module Dependency Map](#module-dependency-map)

---

## Overview

HOPEFX is a self-hosted, institutional-grade automated trading platform for XAUUSD
and six additional forex/commodity symbols. It is built on FastAPI, SQLAlchemy,
Redis, and a 222-feature XGBoost stacking ensemble (59.92% OOS accuracy, p=0.0000).

**Key architectural decisions:**

| Decision | Rationale |
|----------|-----------|
| Single `MarketDataOrchestrator` for all price data | Prevents broker-specific price drift; all modules read from one consensus tick |
| `ComponentRegistry` for startup | Declarative dependency-aware startup replaces 40+ sequential try/except blocks |
| `plan_gate()` inline in endpoints | Subscription enforcement at the API boundary, not in business logic |
| `KillSwitch` persists to disk | Survives process restarts; nuclear halt cannot be undone by a crash/restart |
| `LIVE_MODE_CONFIRMED=false` default | Live order submission is opt-in; paper trading is the default state |
| Model registry with OOS gate | Models are only promoted to production when OOS accuracy >= 0.60 and p-value <= 0.05 |

---

## Entry Point & Startup

```
app.py  ->  uvicorn app:app --host 0.0.0.0 --port 8000
```

`app.py` defines the FastAPI application and its lifespan. On startup:

1. `core/startup_factories.py` builds a `ComponentRegistry` with all components
   declared in dependency order:

   ```
   config  ->  database  ->  cache  ->  risk_manager
                                     ->  broker
                                     ->  trade_executor  (deps: broker, risk_manager)
                                     ->  signal_engine   (deps: trade_executor)
   ```

2. `ComponentRegistry.start()` initialises each component in topological order.
   Required components abort startup on failure. Optional components log a warning
   and continue. A startup summary table is printed to the log.

3. `core/router_registry.py` registers all 50+ FastAPI routers. Each router is
   imported and mounted with its prefix. The registry is the single place where
   all API routes are wired — no routes are registered in `app.py` directly.

4. `data_layer/orchestrator.py` (`MarketDataOrchestrator`) starts all configured
   gold price feeds concurrently. The orchestrator is the only source of price
   data for the entire application.

5. `core/background_tasks.py` starts background loops: signal engine, SL/TP
   monitor, heartbeat, economic calendar poller, and online learner (if enabled).

---

## Data Layer

```
data_layer/
├── orchestrator.py        MarketDataOrchestrator — single source of truth
├── feeds/                 Feed adapters (Finnhub, Twelve Data, Polygon, etc.)
├── quality/               DataQualityEngine — anomaly detection, consensus scoring
├── lineage/               DataLineageStore — immutable audit trail (SQLite)
├── cache/                 Redis-backed tick cache with in-memory fallback
├── microstructure/        Order flow, bid/ask spread, volume profile
├── normalization/         Tick normalisation and unit conversion
├── sentiment/             News sentiment feed integration
├── calendar/              Economic calendar feed
├── replay/                Historical tick replay for backtesting
└── tick_store.py          Persistent tick storage
```

### MarketDataOrchestrator

`MarketDataOrchestrator` is the **only** permitted source of price data.
Direct broker price calls (`broker.get_market_data()`) raise `MarketDataForbidden`.

Flow:
```
NuclearStreamer (WebSocket)
  ├── Finnhub  (OANDA:XAU_USD)
  ├── Twelve Data  (XAU/USD)
  └── Polygon  (C.XAU/USD)
        |
        v
DataQualityEngine
  ├── Anomaly detection (z-score, IQR, Hampel filter)
  ├── Cross-source consensus scoring
  └── Confidence weighting
        |
        v
GoldTick  (price, bid, ask, spread, volume, quality, confidence, source_count)
        |
        ├──> Redis tick cache (1-min TTL)
        ├──> DataLineageStore (immutable audit trail)
        └──> orchestrator.get_latest_tick()  <- all consumers read here
```

`orchestrator.is_safe_to_trade()` returns `False` when:
- No tick received in the last 30 seconds
- Data quality below `ENGINE_MIN_DATA_QUALITY` (default: 0.40)
- All feeds are down

---

## Signal Engine

```
core/signal_engine.py      run_signal_engine() — main async loop
brain/                     HOPEFXBrain — regime detection + strategy orchestration
strategies/
├── base.py                BaseStrategy (ABC)
├── manager.py             StrategyManager — plan-gated strategy dispatch
├── regime_router.py       RegimeRouter — routes to strategy by market regime
├── strategy_brain.py      StrategyBrain — ML consensus (Elite only)
├── ma_crossover.py        MovingAverageCrossover (Starter)
├── ema_crossover.py       EMAcrossover (Starter)
├── rsi_strategy.py        RSIReversal (Starter)
├── its_8_os.py            Ichimoku (Starter)
├── macd_strategy.py       MACD (Professional)
├── bollinger_bands.py     BollingerBands (Professional)
├── breakout.py            Breakout (Professional)
├── mean_reversion.py      MeanReversion (Professional)
├── stochastic.py          Stochastic (Professional)
└── smc_ict.py             SMCICTStrategy (Enterprise)
```

Signal generation loop (runs every tick):

```
orchestrator.get_latest_tick()
        |
        v
HOPEFXBrain.detect_regime()
  ├── Trend / Range / Volatile / Crisis
  └── Macro overlay (DXY, VIX, US10Y, SPX, GLD)
        |
        v
RegimeRouter -> selects active strategy for current regime
        |
        v
BaseStrategy.generate_signals(tick, features)
        |
        v
Signal  (direction, confidence, entry, sl, tp, symbol, strategy, regime)
        |
        v
Gatekeeper.check(signal)   <- news blackout, sentiment, equity drawdown
        |
        v
RiskManager.pre_trade_gate(signal)   <- VaR, CVaR, leverage, spread, margin
        |
        v
TradeExecutor.execute_signal(signal)
```

---

## ML Pipeline

```
ml/
├── model.py               PPORLAgent, VectorRAGNewsSentiment, OnlineRetrainer
├── advanced_ai.py         AdvancedAIEnsemble — XGBoost stacking ensemble
├── model_registry.py      ModelRegistry — OOS gate, SHA-256 digest, promotion
├── sharpe_circuit_breaker.py  Blocks model promotion if Sharpe < threshold
├── advanced_features.py   176-feature engineering pipeline
├── features_extended.py   Extended feature set
├── macro_features.py      Macro features (DXY, VIX, US10Y, US2Y, SPX, GLD)
├── online_learner.py      SklearnOnlineLearner — SGD + EWC, hourly updates
└── train_advanced.py      Walk-forward training script (50-year dataset)
```

### Production Model

| Property | Value |
|----------|-------|
| File | `advanced_oos.pkl` |
| Algorithm | XGBoost stacking ensemble |
| Features | 176 (stationary, regime-aware, macro-augmented) |
| OOS accuracy | 59.92% (p=0.0000, N=2,016 bars) — see `ml/saved_models/advanced_oos_meta.json` |
| OOS promotion gate | accuracy >= 0.60 AND p-value <= 0.05 |
| Feature cache | Redis, 1-min TTL |
| Fallback | SignalEngine falls back to rule-based strategies if model unavailable |

### Model Registry

`ml/model_registry.py` tracks every model version: file path, SHA-256 digest,
OOS metrics, and promotion state. A model is only promoted to production when
both gates pass:

```python
REGISTRY_MIN_OOS_ACC  = 0.60   # env: REGISTRY_MIN_OOS_ACC
REGISTRY_MAX_OOS_PVAL = 0.05   # env: REGISTRY_MAX_OOS_PVAL
```

### Online Learning (Elite only)

`SklearnOnlineLearner` runs hourly via `FEATURE_ONLINE_LEARNING=true`.
Uses SGD with Elastic Weight Consolidation (EWC) to prevent catastrophic
forgetting. Updates are applied to a shadow model and promoted only if the
OOS gate passes.

### Retraining

Weekly automated retraining via `.github/workflows/retrain.yml`:
- Smoke run: `scripts/retrain_horizon5.py --smoke` (~5 min)
- Full run: `scripts/retrain_model.py --advanced --years 50 --oos-years 8` (~2 hours)

---

## Risk Engine

```
risk/
├── manager.py             RiskManager — pre-trade gate coordinator
├── pre_trade_gate.py      PreTradeGate — VaR, CVaR, leverage, spread, margin checks
├── gatekeeper.py          Gatekeeper — news blackout, sentiment, equity drawdown
├── circuit_breakers.py    CircuitBreaker — consecutive loss, daily drawdown halt
├── drawdown_tracker.py    DrawdownTracker — real-time equity curve tracking
├── intra_trade_monitor.py IntraTradeMonitor — SL/TP polling (200ms interval)
├── analytics.py           VaR, ES, EWMA VaR, GARCH VaR, Sharpe, slippage sim
├── advanced_analytics.py  AdvancedRiskAnalytics — Monte Carlo, stress tests
├── position_sizing.py     Kelly criterion, fixed fractional, volatility-scaled
├── fia_compliance.py      FIAComplianceManager — FIA Article 17 pre-trade checks
├── self_trade_prevention.py  Self-trade prevention
├── stress_test.py         Scenario stress testing
└── compliance/            Regulatory compliance sub-module
```

Pre-trade gate checks (in order, any failure blocks the order):

| Check | Source | Block condition |
|-------|--------|----------------|
| Kill switch | `kill_switch.py` | `KillSwitch.is_active()` |
| Live mode gate | `core/live_trading_gate.py` | `LIVE_MODE_CONFIRMED != true` |
| Spread spike | `risk/pre_trade_gate.py` | spread > `SPREAD_SPIKE_MULTIPLIER` x EMA baseline |
| Absolute spread | `risk/pre_trade_gate.py` | spread > `SPREAD_ABS_LIMIT_USD` |
| Leverage | `risk/pre_trade_gate.py` | leverage > `MAX_LEVERAGE_RATIO` |
| Margin buffer | `risk/pre_trade_gate.py` | free margin < `MIN_MARGIN_BUFFER` x required |
| CVaR | `risk/analytics.py` | CVaR exceeds daily risk budget |
| News blackout | `risk/gatekeeper.py` | High-impact event within `GATEKEEPER_PAUSE_S` seconds |
| Sentiment | `risk/gatekeeper.py` | Sentiment score < `GATEKEEPER_SENT_BLACKOUT` |
| Equity drawdown | `risk/gatekeeper.py` | Equity drawdown > `GATEKEEPER_IMPACT_BLACKOUT` |
| FIA compliance | `risk/fia_compliance.py` | FIA Article 17 pre-trade check fails |
| Circuit breaker | `risk/circuit_breakers.py` | Consecutive losses or daily drawdown limit hit |

### Kill Switch

`kill_switch.py` (`KillSwitch`) is a hardware-level halt. When triggered:
- All open positions are closed immediately
- All pending orders are cancelled
- The halt state is persisted to `kill_switch_state.json`
- The state survives process restarts — manual reset required

Trigger via API: `POST /api/trading/kill-switch`
Reset via API: `POST /api/trading/kill-switch/reset` (requires admin role)

---

## Execution Engine

```
execution/
├── trade_executor.py      TradeExecutor — signal -> order lifecycle
├── smart_router.py        SmartRouter — multi-broker routing and failover
├── order_management.py    OMS — order state machine
├── position_tracker.py    Real-time position reconciliation
├── fix_adapter.py         FIX 4.4 protocol adapter
└── slippage_model.py      Slippage estimation
```

Order lifecycle:

```
Signal (validated by RiskManager)
        |
        v
SmartRouter.route(signal)
  ├── Selects broker by: latency, spread, fill rate, account balance
  ├── Failover: if primary broker unhealthy -> secondary broker
  └── Returns RoutingDecision (broker_id, account_id, reason)
        |
        v
BrokerConnector.place_order(order)
        |
        v
ExecutionResult (order_id, fill_price, slippage, latency_ms, status)
        |
        v
PositionTracker.update(result)
IntraTradeMonitor.register(position)   <- polls SL/TP every 200ms
PostTradeAnalyzer.record(result)
```

---

## Broker Connectors

All connectors implement `BrokerConnector` (ABC) from `brokers/base.py`.
Price data methods raise `MarketDataForbidden` — use `orchestrator.get_latest_tick()`.

| Connector | File | Mode | Notes |
|-----------|------|------|-------|
| OANDA | `brokers/oanda_broker.py` | Live + Practice | Primary execution broker |
| IBKR | `brokers/ibkr_broker.py` | Live + Paper | TWS/IB Gateway via ib_insync |
| Alpaca | `brokers/alpaca_broker.py` | Live + Paper | REST + WebSocket |
| Binance | `brokers/binance_broker.py` | Live + Testnet | Spot + Futures |
| Bybit | `brokers/bybit_broker.py` | Live + Sandbox | XAUUSDT perpetuals |
| MT5 | `brokers/mt5_broker.py` | Live | MetaTrader 5 via MetaTrader5 |
| Paper | `brokers/paper_broker.py` | Simulation | Default when no broker configured |
| FIX | `execution/fix_adapter.py` | Live | FIX 4.4 for institutional connectivity |

`SmartRouter` manages multi-broker routing and failover. Broker health is checked
every 30 seconds. Unhealthy brokers are removed from the routing pool automatically.

---

## API Layer

```
app.py
└── core/router_registry.py   registers all 50+ routers

api/
├── auth.py              POST /api/auth/login, /refresh, /logout, /me
├── signals.py           GET /api/signals/latest, /history, /performance
├── trading.py           POST /api/trading/order, GET /positions, /account
├── ml.py                GET /api/ml/accuracy, POST /predict, /retrain
├── risk.py              GET /api/risk/status, /drawdown, /cvar
├── broker.py            GET /api/broker/status, POST /switch
├── backtesting.py       POST /api/backtest/run, GET /results
├── monetization.py      GET /api/monetization/pricing, POST /subscribe
├── billing.py           POST /api/billing/auth/activate-free-tier, /stripe/webhook
├── brain.py             POST /api/brain/generate-strategy, /deploy-strategy
├── chat.py              POST /api/chat/message, GET /history
├── explain.py           GET /api/explain/signal, /global-importance
├── social.py            GET /api/feed, POST /react
├── profiles.py          GET /api/profiles/{username}
├── mobile.py            POST /api/mobile/register-push, GET /push-status
├── admin.py             GET /api/admin/dashboard, /logs, /kyc
└── ...                  (50+ total routers)
```

All endpoints except `/health`, `/docs`, `/openapi.json`, `/redoc` require:
1. Valid JWT (`Authorization: Bearer <token>`)
2. Active subscription (enforced via `plan_gate()` per endpoint)

Interactive docs: `GET /docs` (Swagger UI), `GET /redoc` (ReDoc)

### WebSocket Endpoints

| Path | Data |
|------|------|
| `/ws/signals` | Live signal stream |
| `/ws/prices` | Live price ticks (from orchestrator) |
| `/ws/positions` | Position updates |
| `/ws/alerts` | Alert notifications |

---

## Subscription & Access Control

```
monetization/
├── subscription.py      SubscriptionManager, require_plan(), plan_gate()
├── pricing.py           SubscriptionTier, PricingTier, TierFeatures
├── license.py           License key validation
├── stripe_integration.py  Stripe webhook handling
├── stripe_live.py       Stripe live payment processing
└── access_codes.py      Activation code management
```

### Tier Hierarchy

```
FREE  ->  STARTER  ->  PROFESSIONAL  ->  ENTERPRISE  ->  ELITE
```

Plan enforcement uses `plan_gate(minimum_plan, user_plan)` from
`monetization/subscription.py`. It is called inline in each endpoint:

```python
sub = subscription_manager.get_subscription(user.user_id)
user_plan = sub.tier.value if (sub and sub.is_active()) else "free"
if not plan_gate("professional", user_plan):
    raise HTTPException(403, {"error_code": "PLAN_LIMIT_EXCEEDED", "required_plan": "professional"})
```

Strategy-level gating is also enforced in `strategies/manager.py` via
`STRATEGY_PLAN_REQUIREMENTS` before any strategy logic executes.

Free tier is activated automatically on signup:
`POST /api/billing/auth/activate-free-tier`

---

## Notifications & Alerts

```
notifications/
├── manager.py           NotificationManager — routes to all channels
├── telegram_bot.py      Telegram bot (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
├── discord_bot.py       Discord webhook (DISCORD_WEBHOOK_URL)
├── email_renderer.py    HTML email templates
├── email_triggers.py    Event-driven email dispatch
├── alert_engine.py      Alert rule engine (price, signal, drawdown triggers)
└── heartbeat.py         Periodic system health heartbeat
```

Notification channels are configured in `.env`. All channels are optional —
the system runs without any notification config. Channels are tried independently;
failure of one channel does not block others.

---

## Observability

```
monitoring/
├── metrics.py           Prometheus metrics (hopefx_* namespace)
├── health.py            /health endpoint — component-level status
└── logging.py           Structured JSON logging config

grafana/
├── dashboards/          4 dashboards, 27 panels
└── provisioning/        Auto-provisioning config
```

### Prometheus Metrics

Scraped at `GET /metrics`. Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `hopefx_signals_total` | Counter | Signals generated, by direction and strategy |
| `hopefx_orders_total` | Counter | Orders placed, by broker and status |
| `hopefx_request_duration_seconds` | Histogram | API request latency, by endpoint |
| `hopefx_active_positions` | Gauge | Open positions count |
| `hopefx_daily_pnl` | Gauge | Realised P&L for the current trading day |
| `hopefx_drawdown_pct` | Gauge | Current drawdown from equity peak |
| `hopefx_ml_prediction_confidence` | Gauge | Last ML prediction confidence score |
| `hopefx_data_quality_score` | Gauge | Current orchestrator data quality score |

### Health Check

`GET /health` returns per-component status:

```json
{
  "status": "healthy",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "broker": "healthy",
    "ml_model": "healthy",
    "orchestrator": "healthy",
    "kill_switch": "inactive"
  },
  "version": "1.17.0"
}
```

---

## Infrastructure

### Docker Compose (development / single-node production)

```
docker/
├── Dockerfile           Multi-stage build (builder -> runtime)
└── docker-compose.yml   app, postgres, redis, grafana, prometheus, nginx
```

Start the full stack:
```bash
docker compose up -d
```

### Kubernetes (production)

```
k8s/
├── namespace.yaml
├── k8s-deployment.yaml      app Deployment (2 replicas, rolling update)
├── k8s-service.yaml         ClusterIP service
├── ingress.yaml             NGINX ingress with TLS
├── k8s-configmap.yaml       Non-secret config
├── k8s-secrets.yaml         Secret references
├── redis-cluster.yaml       Redis StatefulSet
├── network-policy.yaml      Deny-all default, allow-list ingress/egress
├── pdb.yaml                 PodDisruptionBudget (minAvailable: 1)
├── kill-switch-configmap.yaml  Kill switch state persistence
└── kill-switch-rbac.yaml    RBAC for kill switch ConfigMap access
```

### Redis

```
redis/
├── redis-master.conf    Master config (AOF + RDB persistence)
├── redis-replica.conf   Replica config
└── sentinel.conf        Sentinel config (3-node HA)
```

---

## Data Flow — End to End

```
External Price Sources
  Finnhub WS  .  Twelve Data WS  .  Polygon WS
        |
        v
MarketDataOrchestrator  (data_layer/orchestrator.py)
  DataQualityEngine -> consensus GoldTick -> Redis cache
  DataLineageStore (immutable audit trail)
        |
        v
Signal Engine  (core/signal_engine.py)
  HOPEFXBrain -> RegimeRouter -> BaseStrategy.generate_signals()
  AdvancedAIEnsemble (176 features, XGBoost) -> ML signal
  StrategyBrain (Elite) -> consensus signal
        |
        v
Risk Engine  (risk/)
  Gatekeeper -> PreTradeGate -> CircuitBreaker -> FIACompliance
  KillSwitch check -> LiveTradingGate check
        |
        v
Execution Engine  (execution/)
  SmartRouter -> BrokerConnector.place_order()
  PositionTracker -> IntraTradeMonitor (SL/TP, 200ms poll)
  PostTradeAnalyzer -> TradeJournal
        |
        v
Observability
  Prometheus metrics -> Grafana dashboards
  Sentry error tracking
  Notifications (Telegram / Discord / Email)
  WebSocket push -> dashboard / mobile
```

---

## Module Dependency Map

```
app.py
├── core/router_registry.py      <- mounts all 50+ API routers
├── core/startup_factories.py    <- builds ComponentRegistry
│   ├── config/settings.py
│   ├── database/                <- SQLAlchemy + Alembic
│   ├── cache/                   <- Redis + in-memory fallback
│   ├── risk/manager.py
│   ├── brokers/                 <- BrokerConnector implementations
│   └── execution/trade_executor.py
│       └── execution/smart_router.py
├── data_layer/orchestrator.py   <- started independently in lifespan
│   ├── data_layer/feeds/        <- NuclearStreamer, Finnhub, Twelve Data, Polygon
│   ├── data_layer/quality/      <- DataQualityEngine
│   └── data_layer/lineage/      <- DataLineageStore
├── core/signal_engine.py        <- background loop
│   ├── brain/                   <- HOPEFXBrain, RegimeRouter
│   ├── strategies/              <- BaseStrategy implementations
│   └── ml/                      <- AdvancedAIEnsemble, ModelRegistry
├── kill_switch.py               <- checked at every order submission
├── monetization/subscription.py <- plan_gate() called in every gated endpoint
└── notifications/manager.py    <- called on signal, fill, alert, heartbeat
```

---

*Last updated: 2026-07-14*
