# HOPEFX — Roadmap

> Last updated: 2026-07-14 (v1.17)

---

## Current Status: Paper Mode Active

The platform is live in paper trading mode on OANDA practice.

| Component | Status |
|-----------|--------|
| ML model (`advanced_oos.pkl`) | ✅ 66.4% OOS accuracy, p=0.0000, 176 features, N=1,260 bars |
| Multi-symbol backtest (7 symbols) | ✅ N>919 trades, SE≤0.10 gate satisfied |
| Online learning (SGD + EWC daily loop) | ✅ Wired — enable with `ML_HOURLY_ENABLED=true` |
| Dual license (AGPL-3.0 + commercial) | ✅ LICENSE-COMMERCIAL.md + CLA.md |
| Risk engine (CVaR, kill switch, drawdown gate) | ✅ Production |
| OANDA paper broker | Active — clock started 2026-03-27 |
| Signal engine (regime-gated ML inference) | ✅ Wired |
| Execution (OMS, position tracker, smart router) | ✅ Wired |
| Observability (Prometheus, Sentry, Discord) | ✅ Production |
| REST + WebSocket API (108 endpoints) | ✅ Stable |
| Test suite (2,560+ tests) | ✅ CI green |
| Documentation (30 main docs + 103 archive) | ✅ Complete |

---

## Milestone 1 — Statistical Robustness ✅ DONE

**Result:** Multi-symbol backtest (7 symbols: XAU/USD, BTC/USD, ETH/USD, EUR/USD, GBP/USD, Silver, Oil)
confirmed N>919 trades. SE≤0.10 gate satisfied. OOS model validated: 66.4% accuracy, p=0.0000,
N=1,260 bars, 176 features.

- [x] Multi-symbol backtest: XAU/USD N=302, BTC/USD N=69, ETH/USD N=257 → pooled N=628
- [x] Expanded to 7 symbols → pooled N>919, SE≤0.10
- [x] OOS metadata validated and stamped (`advanced_oos_meta.json`)
- [x] OrderGateway wired to TradeExecutor — real routing, no stub
- [x] New API endpoints: /api/ml/health, /api/backtest/multi-symbol, /api/online-learner/status+partial-fit
- [ ] Run paper trading for 60+ days on OANDA practice (started 2026-03-27)
- [ ] Log every signal, fill, and P&L to PostgreSQL
- [ ] Auto-generate weekly performance report (win rate, Sharpe, drawdown)
- [ ] Validate live signal distribution matches OOS backtest distribution

---

## Milestone 2 — Live OANDA Run

**Target:** First real-money trade on OANDA live account.

Prerequisites:
- [ ] Complete 30-day paper trading run (gate: `data/oanda_paper_start.json`)
- [ ] 200+ paper trades logged with zero execution errors
- [ ] Security audit: rotate all API keys, review JWT config
- [ ] Set `OANDA_ENVIRONMENT=live` and `FEATURE_LIVE_TRADING=true`
- [ ] Start with 0.01 lot size, scale up after 50 live trades
- [ ] Monitor daily drawdown gate — halt if −2% daily DD hit

Check gate status:
```bash
python scripts/enable_live_trading.py --check-only
```

---

## Milestone 3 — MT5 Export

**Target:** Export signals to MetaTrader 5 via ZeroMQ bridge.

- [ ] Implement `brokers/mt5_zmq_bridge.py` signal publisher
- [ ] MT5 EA subscriber (MQL5) that receives signals and places orders
- [ ] Round-trip latency test: target < 50ms signal-to-order
- [ ] Paper test on MT5 demo for 2 weeks before live

---

## Milestone 4 — Multi-Symbol Expansion ✅ BACKTEST DONE

**Target:** Trade BTC/USD and ETH/USD alongside XAUUSD, plus forex and commodities.

- [x] Multi-symbol backtest: N=628 trades (XAU+BTC+ETH), Sharpe gate PASSED
- [x] Expanded to 7 symbols (+ EUR/USD, GBP/USD, Silver, Oil) → N>919, SE≤0.10
- [ ] Retrain `advanced_oos.pkl` on BTC/USDT + ETH/USDT (Binance hourly)
- [ ] Portfolio-level risk: cross-asset correlation limits
- [ ] Validate live multi-symbol signal distribution before deployment

---

## Milestone 5 — Reinforcement Learning

**Target:** Replace or augment XGBoost ensemble with a trained RL agent.

- [ ] Implement `ml/rl_agent.py` using Stable-Baselines3 (PPO)
- [ ] Custom gym environment: XAUUSD H1 with realistic slippage + spread
- [ ] Walk-forward evaluation: RL agent vs XGBoost ensemble
- [ ] Deploy only if RL OOS accuracy ≥ 65% with p < 0.05

---

## Milestone 6 — Web Frontend

**Target:** React/Vue dashboard connected to the REST + WebSocket API.

- [ ] React or Vue.js project scaffold in `frontend/`
- [ ] Real-time WebSocket chart (price + signals)
- [ ] Live P&L dashboard
- [ ] Strategy control panel (start/stop/configure)
- [ ] Risk monitor (drawdown, CVaR, kill switch status)
- [ ] Social trading feed (copy trading, leaderboards)

---

## Milestone 7 — White-Label API

**Target:** Expose HOPEFX as a signal API for third-party consumers.

- [ ] `/api/v1/signals` endpoint with API key auth
- [ ] Rate limiting per tier (free: 10 req/min, pro: 100 req/min)
- [ ] Stripe billing integration for pro tier
- [ ] SLA: 99.9% uptime, < 200ms p99 latency
- [ ] White-label branding config in `whitelabel/`

---

## Milestone 8 — Mobile App

**Target:** iOS and Android apps via React Native.

- [ ] React Native project scaffold
- [ ] Core screens: Dashboard, Chart, Positions, Alerts
- [ ] Push notifications via FCM/APNs
- [ ] Biometric authentication
- [ ] Offline mode with cached signals
- [ ] App Store + Google Play submission

---

## Research Pipeline (Feature-Flagged)

All four research phases are wired in `core/signal_engine.py` and activate
after their respective paper trading gates are met.

| Phase | Component | Flag | Gate |
|-------|-----------|------|------|
| 1 | MTFFusionStore | `FEATURE_MTF_FUSION` | On by default |
| 2 | AnomalyWeightStore | `FEATURE_ANOMALY_WEIGHTING` | After 30-day paper run |
| 3 | OnlineLearnerStore | `FEATURE_ONLINE_LEARNING` | After 90-day paper run + 500 fills |
| 4 | DeepEnsembleStore | `FEATURE_DEEP_ENSEMBLE` | After LSTM OOS ≥ 70% |

See `research/README.md` for gate conditions and enable instructions.

---

## Type Safety (Ongoing)

- [ ] Add `mypy` to CI with `--strict` on `api/`, `risk/`, `ml/`
- [ ] Replace remaining `Any` type hints in `brokers/`
- [ ] Add `py.typed` marker to all public packages

---

## VaR Remaining Work

`calculate_var_historical` and `calculate_var_parametric` still use sqrt(t) for
multi-day scaling. Use `calculate_var_multiday` or `calculate_var_ewma` for
production risk limits on XAUUSD. This is documented but not yet enforced.

- [ ] Replace sqrt(t) in all remaining VaR paths
- [ ] Add GARCH(1,1) volatility model for VaR

---

## Running the ML Pipeline

```bash
# Production model (176 features, 50-year data, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Basic model (65 features, macro walk-forward)
python ml/train_with_macro.py --years 50 --oos-years 3

# Multi-symbol backtest (7 symbols, 10-year real data)
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3

# Fetch latest XAUUSD H1 bars
python -m data.scheduler
```

## Running Tests

```bash
# Full suite
pytest tests/ --ignore=tests/integration/test_redis.py -q
# Expected: 2560 passed, 0 failed

# With coverage
pytest tests/ --cov=. --cov-report=term-missing -q

# Specific suites
pytest tests/test_auth_gates.py -q
pytest tests/unit/ -q
pytest tests/integration/ -q
```
