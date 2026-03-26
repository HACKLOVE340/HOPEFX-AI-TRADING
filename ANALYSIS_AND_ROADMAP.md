# HOPEFX — Architecture Analysis & Roadmap

> Last updated: 2026-03-25 — reflects current codebase state after v12 fixes.

---

## Current State

### Test Coverage

| Metric | Value |
|--------|-------|
| Tests written | 2,544 |
| Tests passing | 2,390 |
| Tests skipped | 29 |
| Gap (import issues / silent skips) | 154 |
| Failures | 0 |

The 154-function gap between written and passing is tracked. Most are import-conditional
tests that skip silently when optional dependencies (TensorFlow, quickfix) are absent.
The CI badge reflects actual pytest output, not a hardcoded number.

### ML Model Status

| Model | OOS Accuracy | p-value | Features | Status |
|-------|-------------|---------|----------|--------|
| **advanced_oos.pkl** | **68.0%** | **p=0.0000** | 122 stationary | ✅ **Production** |
| xgb_macro.pkl | 50.3% ± 1.8% | p=0.720 | 65 stationary | ⚠️ Fallback only |
| rf_macro.pkl | 50.7% ± 2.6% | p=0.612 | 65 stationary | ⚠️ Fallback only |

**OOS period**: 2023-03-22 → 2026-03-24 (756 bars, 3-year held-out)  
**Abstain rate**: 27.5% of bars filtered (model signals only on high-confidence bars)  
**Target was**: ≥ 55% OOS with p < 0.05 — **exceeded** (68.0%, p=0.0000)

Both fallback models have had all `close_lag_N` non-stationary features removed.
The fallback path now logs CRITICAL + fires Sentry fatal alert + Discord alert
when `advanced_oos.pkl` fails to load.

### Backtest Results (Real GC=F Data)

| Metric | Value | Note |
|--------|-------|------|
| Period | 2024-10-02 – 2026-03-24 | Real GC=F futures |
| Trades | 45 | ⚠️ Too few for Sharpe significance |
| Win rate | 57.8% | |
| Profit factor | 2.28 | |
| Max drawdown | −0.88% | |
| Sharpe | 1.82 | SE ≈ ±0.54 at N=45 — not statistically robust |
| Calmar | 6.26 | |

Need ~170 trades for Sharpe SE ≤ ±0.3. At ~1 trade/week, that requires ~3 years
of paper trading. A higher-frequency signal or multi-symbol expansion is needed
to accumulate sufficient trade count faster.

### Infrastructure Status

| Component | Status |
|-----------|--------|
| FIX adapter | ✅ Complete — circuit breaker, heartbeat, all stubs implemented |
| Risk stack | ✅ Production — RiskManager, CVaR gate, kill switch, VaR/EWMA |
| Execution | ✅ Wired — paper broker, smart router, position tracker |
| MacroStore | ✅ Fixed — bootstraps at startup, daily refresh, wired to inference |
| Signal engine | ✅ Refactored — 6 sub-functions, macro_df passed to predict_proba |
| place_order() | ✅ Refactored — 5 sub-functions, was 201-line monolith |
| OANDA routing | ✅ Added — us/eu/sg region routing, streaming URL resolution |
| Sentry | ✅ Production config — performance monitoring, ML fallback alerts |
| Discord bot | ✅ Added — rich signal embeds, rate-limited, fallback warnings |
| Load tests | ✅ Enhanced — k6 (6 scenarios) + Locust (3 user classes) |
| Paper trading | ❌ Not started — **start now** |

---

## Architecture

### Entry Point
```
app.py  →  uvicorn app:app --host 0.0.0.0 --port 8000
```

### Module Map
```
app.py                      FastAPI application, lifespan, ComponentRegistry startup
├── api/                    REST + WebSocket routers (22 registered)
├── brain/                  HOPEFXBrain — orchestrates all subsystems
├── config/                 Settings (Pydantic), feature flags, vault
├── core/
│   ├── component_registry.py   Dependency-ordered startup
│   ├── startup_factories.py    Component factories (MacroStore, signal engine, etc.)
│   ├── signal_engine.py        Strategy → ML → risk → order pipeline
│   └── position_reconciler.py
├── ml/
│   ├── advanced_features.py    122-feature pipeline (COT, regime, macro)
│   ├── train_advanced.py       Advanced model training with OOS evaluation
│   ├── live_inference.py       AdvancedModelPredictor + Redis feature cache
│   ├── macro_store.py          Daily macro series → hourly alignment
│   └── macro_bootstrap.py      yfinance fetch + daily refresh scheduler
├── data/                   Price feeds, macro CSVs, DataScheduler
├── execution/              FIX adapter, OMS, trade executor, position tracker
├── risk/                   RiskManager, circuit breakers, VaR, CVaR, FIA compliance
├── notifications/
│   ├── discord_bot.py      Community signal bot (rich embeds, rate-limited)
│   ├── telegram_bot.py     Telegram alerts
│   └── alert_engine.py     Multi-channel alert routing
├── monitoring/
│   └── sentry_config.py    Error tracking + performance + ML fallback alerts
├── brokers/                OANDA (region-routed), MT5, Alpaca, IB, Binance, CCXT
├── research/               LSTM/Transformer/TCN, online learning, drift detection
│                           (research-only — see research/README.md)
├── grafana/                4 dashboards, 27 panels
├── k6/load_tests.js        6 load test scenarios
└── locust/load_tests.py    3 user classes
```

### Key Design Decisions

**ML inference**
- `advanced_oos.pkl` is a calibrated XGBoost pipeline (scaler + model) trained on
  122 stationary features: technical indicators, COT/central-bank proxies, regime
  features (Hurst, ADX), and macro cross-asset (DXY, VIX, yields, SPX)
- `MacroStore` bootstraps historical macro CSVs at startup via yfinance; a daily
  18:00 UTC background job keeps them current
- At inference, `macro_store.align_to_hourly(ohlcv_df)` forward-fills daily macro
  values onto the hourly OHLCV index before calling `predict_proba()`
- Feature cache: Redis-backed (1-min TTL) prevents recomputing 122 features on
  every concurrent tick under load

**Risk management**
- `RiskManager` uses Kelly criterion with safety caps (configurable `kelly_fraction`)
- Kill switch persists halt state to disk (`risk/halt_state.json`) — survives restarts
- CVaR pre-trade gate runs independently of `assess_risk()` — a CVaR breach always
  blocks order submission even if `assess_risk()` was skipped or errored
- VaR: historical, parametric, Monte Carlo, `calculate_var_multiday` (no sqrt(t)),
  `calculate_var_ewma` (RiskMetrics volatility-weighted HS)

**Execution**
- `place_order()` decomposed into 5 sub-functions: `_validate_order()`,
  `_apply_risk_checks()`, `_log_compliance()`, `_route_to_broker()`, `_record_fill()`
- `_tick()` decomposed into 6 sub-functions: `_compute_signal()`, `_build_ohlcv_df()`,
  `_fetch_macro_df()`, `_compute_ml_probability()`, `_publish_and_broadcast()`,
  `_execute_if_approved()`
- FIX adapter: full QuickFIX/J implementation with circuit breaker and heartbeat

**Observability**
- Sentry: FastAPI/SQLAlchemy/Redis/aiohttp integrations; `before_send` scrubs 15
  sensitive field names; `capture_ml_fallback_event()` fires fatal-level issue on
  model degradation
- Discord bot: rich embeds with confidence bar, R/R ratio, fallback warning field;
  rate-limited per symbol (default 5 min cooldown)

---

## Open Items

### P1 — Start the 30-Day OANDA Paper Trading Run (do this now)

The ML edge is proven (68%, p=0.0000). The risk stack is solid. The execution is
wired. The macro inference gap is fixed. The only remaining requirement before live
capital is 30 days of paper trading with a real OANDA practice API key.

```bash
# Set in .env:
BROKER_OANDA_TOKEN=your-practice-api-key
BROKER_OANDA_ACCOUNT=your-account-id
OANDA_ENVIRONMENT=practice
OANDA_REGION=us

# Start the server — signal engine auto-starts
uvicorn app:app --host 0.0.0.0 --port 8000
```

After 30 days: real fill data, real slippage numbers, real latency measurements.
The clock does not start until you flip the switch.

### P2 — Accumulate Trade Count

N=45 trades is insufficient for Sharpe significance (SE ≈ ±0.54). Options:
- Run paper trading for 6+ months at current ~1 trade/week frequency
- Expand to multi-symbol (EURUSD, GBPUSD, USDJPY) to increase signal frequency
- Lower the abstain threshold (currently 27.5% of bars filtered) — but only if
  OOS accuracy remains above 60% on the expanded signal set

### P3 — Research Pipeline Integration Path

`research/` contains 4,500 lines of LSTM/Transformer/TCN, online learning with
drift detection, multi-timeframe fusion, microstructure features, and anomaly
weighting. None of this is imported by the live signal engine.

See `research/README.md` for the intended integration path. The research pipeline
is not a gap — it is a deliberate separation of research from production. The
integration path document explains how each component would be promoted to live.

### P4 — VaR sqrt(t) Remaining Paths

`calculate_var_historical` and `calculate_var_parametric` still use sqrt(t) for
multi-day scaling. Use `calculate_var_multiday` or `calculate_var_ewma` for
production risk limits on XAUUSD. This is documented but not yet enforced.

---

## Roadmap

### Now (before live capital)
- [x] ML edge demonstrated: 68.0% OOS, p=0.0000
- [x] Macro features wired to live inference
- [x] Fallback model cleaned (no close_lag_N features)
- [x] place_order() and _tick() decomposed for safety
- [x] Sentry + Discord alerts for ML fallback
- [ ] **Start 30-day OANDA paper trading run**

### This Month
- [ ] Accumulate 30 days of paper trading data (fills, slippage, latency)
- [ ] Update performance.json with real paper trading metrics
- [ ] Expand to 2–3 symbols to increase trade count
- [ ] Wire research/pipeline LSTM as an optional signal layer (feature-flagged)

### Next Quarter
- [ ] Replace sqrt(t) VaR in all remaining paths
- [ ] Add GARCH(1,1) volatility model for VaR
- [ ] Frontend: real-time WebSocket chart, live P&L dashboard
- [ ] Monetisation: end-to-end payment flow test

---

## Running the ML Pipeline

```bash
# Production model (122 features, 50-year data, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Basic model (65 features, macro walk-forward)
python ml/train_with_macro.py --years 50 --oos-years 3

# Fetch latest XAUUSD H1 bars
python -m data.scheduler
```

## Running Tests

```bash
# Full suite
pytest tests/ --ignore=tests/integration/test_redis.py -q
# Expected: 2390 passed, 29 skipped

# With coverage
pytest tests/ --cov=. --cov-report=term-missing -q

# Specific suites
pytest tests/test_auth_gates.py -q
pytest tests/unit/ -q
pytest tests/integration/ -q
```
