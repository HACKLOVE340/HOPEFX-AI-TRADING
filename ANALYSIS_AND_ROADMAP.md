# HOPEFX — Architecture Analysis & Roadmap

## Current State (as of this commit)

### Test Coverage
| Metric | Value |
|--------|-------|
| Tests collected | 2,267 |
| Tests passing | 2,239 |
| Tests skipped | 29 |
| Failures | 0 |
| Collection errors | 0 |

### ML Model Accuracy
| Model | Accuracy | F1 | Notes |
|-------|----------|----|-------|
| XGBoost (baseline) | 49.0% | 0.419 | Technical features only |
| RandomForest (baseline) | 48.6% | 0.389 | Technical features only |
| XGBoost + macro | TBD | TBD | Run `python ml/train_with_macro.py` |
| RandomForest + macro | TBD | TBD | Run `python ml/train_with_macro.py` |

**Target:** ≥ 55% out-of-sample accuracy with p < 0.05 (t-test vs random) before live deployment.  
**Stretch:** ≥ 75% with positive Sharpe on 500+ real trades.

---

## Architecture

### Entry Point
```
app.py  →  uvicorn app:app --host 0.0.0.0 --port 8000
```
All other `main*.py` files are deprecated stubs.

### Module Map
```
app.py                  FastAPI application, lifespan, router registration
├── api/                REST + WebSocket routers
├── brain/              HOPEFXBrain — orchestrates all subsystems
├── config/             Settings (Pydantic), feature flags, vault
├── core/               Domain models, enums, exceptions, event bus
├── data/               Price feeds (WebSocket + REST), macro feeds (FRED/Yahoo)
├── execution/          PaperExecutor, FIX adapter, position tracker
├── ml/                 XGBoost/RF/LSTM training, macro features, RL agent
├── risk/               RiskManager, VaR analytics, position sizing
├── social/             Copy trading, marketplace, affiliates
├── portfolio/          Portfolio construction, optimization, risk contribution
├── transparency/       Execution quality audit trail
├── explainability/     SHAP-based signal explanation
├── replay/             Chart replay engine
└── frontend/           React + Vite + TypeScript UI
```

### Key Design Decisions

**Risk management**  
- `RiskManager` uses Kelly criterion with safety caps (configurable `kelly_fraction`)
- Kill switch persists halt state to disk (`risk/halt_state.json`) — survives restarts
- VaR: three methods available — historical, parametric, Monte Carlo, plus new
  `calculate_var_multiday` (overlapping/non-overlapping windows, no sqrt(t) assumption)
  and `calculate_var_ewma` (RiskMetrics volatility-weighted HS)

**ML pipeline**  
- Feature engineering: 50+ technical indicators + 19 macro features (DXY, VIX,
  US yields, SPX) + 4 regime features (trend, vol, momentum, mean-reversion)
- Walk-forward cross-validation enforced — no look-ahead bias
- `ml/train_with_macro.py` runs the full pipeline and reports t-test significance

**Execution**  
- `PaperExecutor`: rejects naked shorts, uses realistic 35 bps commission
- FIX adapter: full QuickFIX/J implementation with circuit breaker and heartbeat
- RL agent: 2 bps/day overnight financing cost (≈ 7.3% annualised)

---

## Known Limitations

### Critical (block live deployment)

1. **ML edge not yet demonstrated**  
   Baseline models are at ~49% accuracy (coin-flip). The macro feature pipeline
   is built and ready — run `python ml/train_with_macro.py` to measure improvement.
   Do not deploy to live capital until out-of-sample accuracy > 55% with p < 0.05.

2. **Backtest sample too small**  
   The synthetic backtest produced 17 trades. Statistical significance requires
   300–1,000+ trades. Use `ml/train_with_macro.py --years 8` for a proper backtest.

### Warnings (fix before institutional use)

3. **VaR sqrt(t) still used in some paths**  
   `calculate_var_historical` and `calculate_var_parametric` still use sqrt(t)
   for multi-day scaling. Use `calculate_var_multiday` or `calculate_var_ewma`
   for production risk limits on XAUUSD.

4. **Frontend is a skeleton**  
   No real-time WebSocket integration, no state management library, Chart.js only.
   See roadmap below.

5. **Monetisation modules are pre-revenue**  
   Payments, whitelabel, social trading, affiliates, and marketplace are implemented
   but untested at scale. Each is a product in its own right.

---

## Roadmap

### Phase 1 — Signal Validation (before any live capital)
- [ ] Run `python ml/train_with_macro.py --years 8` on real XAUUSD data
- [ ] Achieve ≥ 55% out-of-sample accuracy, p < 0.05
- [ ] Run walk-forward backtest producing ≥ 500 trades
- [ ] Report Sharpe, Calmar, max drawdown, monthly return distribution
- [ ] If results are poor, iterate on features before proceeding

### Phase 2 — Production Hardening
- [ ] Replace sqrt(t) VaR in all remaining paths with `calculate_var_multiday`
- [ ] Add GARCH(1,1) volatility model for VaR (replaces EWMA approximation)
- [ ] Wire COT (Commitment of Traders) data into macro features
- [ ] Add geopolitical risk score (World Monitor integration — feature flag exists)
- [ ] Stress-test kill switch under simulated flash crash conditions

### Phase 3 — Frontend
- [ ] Add Zustand or Jotai for state management
- [ ] Real-time price chart via WebSocket (replace polling)
- [ ] Order book depth visualisation
- [ ] Live P&L dashboard with drawdown chart
- [ ] Mobile-responsive layout

### Phase 4 — Monetisation
- [ ] End-to-end payment flow test (Stripe + crypto)
- [ ] Whitelabel onboarding flow
- [ ] Social trading copy latency benchmark (target < 50ms)
- [ ] Prop firm challenge mode with real drawdown enforcement

---

## Running the ML Training Pipeline

```bash
# Full 8-year backtest with macro features
python ml/train_with_macro.py --years 8 --symbol GC=F

# Without macro features (baseline comparison)
python ml/train_with_macro.py --years 8 --no-macro

# Results saved to
#   ml/saved_models/xgb_macro.pkl
#   ml/saved_models/rf_macro.pkl
#   ml/saved_models/training_report.json
```

## Running Tests

```bash
# Full suite
python -m pytest tests/ -q

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing -q

# Specific module
python -m pytest tests/unit/test_risk_manager.py -v
```
