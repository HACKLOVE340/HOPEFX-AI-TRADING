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
| Documentation (38 main docs + 98 archive) | ✅ Complete |
| Stripe payment processing (real SDK) | ✅ Production |
| Subscription plan gating (require_plan) | ✅ Production |
| Dunning / failed payment recovery | ✅ Production |
| Prometheus monetization metrics | ✅ Production |
| Admin role guard on all /api/admin/* | ✅ Production |

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

## Milestone 2 — Monetization ✅ DONE (v1.17)

**Result:** Full subscription platform live. Stripe SDK integrated, plan gating enforced on all
trading and ML endpoints, dunning active, Prometheus metrics wired.

- [x] Real Stripe PaymentIntent creation (not simulated) with idempotency keys
- [x] Stripe Refund API with partial-refund support
- [x] Dunning: 3x retry at 24h / 72h / 168h, then subscription suspended
- [x] `plan_gate()` inline enforcement in endpoints — raises `403 PLAN_LIMIT_EXCEEDED`
- [x] `plan_gate()` boolean helper for non-FastAPI contexts (strategies/manager.py)
- [x] ML `/predict` endpoint gated at Professional plan
- [x] Trading `/order` endpoint gated at Starter plan
- [x] Strategy subscription gating in `strategies/manager.py`
- [x] Prometheus: `hopefx_mrr_usd`, `hopefx_arr_usd`, `hopefx_churn_rate_pct`
- [x] Prometheus: `hopefx_payment_failures_total`, `hopefx_trial_conversions_total`
- [x] Payment confirmation email (plan, amount, invoice_id, access_code)
- [x] Subscription cancelled email (access_until, data_deleted_at)
- [x] Subscription renewal email (next_renewal date)
- [x] Trial expiry warning email (7d + 1d before expiry)
- [x] Admin role guard on all `/api/admin/*` endpoints (ADMIN_USER_IDS env var)
- [x] Admin impersonation JWT (5 min, `impersonated_by` claim, audit-logged)
- [ ] Switch Stripe from test mode to live (`sk_test_` → `sk_live_`)
- [ ] Publish pricing page at `hopefx.com/pricing`
- [ ] Enable Stripe Radar fraud rules
- [ ] Multi-currency support (EUR, GBP, AED, NGN)

---

## Milestone 3 — Live OANDA Run

**Target:** First real-money trade on OANDA live account.

Prerequisites:
- [ ] Complete 30-day paper trading run (gate: `data/oanda_paper_start.json`)
- [ ] 200+ paper trades logged with zero execution errors
- [ ] Security audit: rotate all API keys, review JWT config
- [ ] Set `OANDA_ENVIRONMENT=live` and `FEATURE_LIVE_TRADING=true`
- [ ] Start with 0.01 lot size, scale up after 50 live trades
- [ ] Monitor daily drawdown gate — halt if -2% daily DD hit

Check gate status:
```bash
python scripts/enable_live_trading.py --check-only
```

---

## Milestone 4 — MT5 Export

**Target:** Export signals to MetaTrader 5 via ZeroMQ bridge.

- [x] `brokers/mt5_broker.py` — MT5 broker connector (MetaTrader5 Python API)
- [x] `market_data/mt5_live_feed.py` — MT5 live price feed
- [x] `market_data/mt5_backup.py` — MT5 backup feed
- [ ] `brokers/mt5_zmq_bridge.py` — ZeroMQ signal publisher for MT5 EA
- [ ] MT5 EA subscriber (MQL5) that receives signals and places orders
- [ ] Round-trip latency test: target < 50ms signal-to-order
- [ ] Paper test on MT5 demo for 2 weeks before live

---

## Milestone 5 — Multi-Symbol Expansion ✅ BACKTEST DONE

**Target:** Trade BTC/USD and ETH/USD alongside XAUUSD, plus forex and commodities.

- [x] Multi-symbol backtest: N=628 trades (XAU+BTC+ETH), Sharpe gate PASSED
- [x] Expanded to 7 symbols (+ EUR/USD, GBP/USD, Silver, Oil) → N>919, SE≤0.10
- [ ] Retrain `advanced_oos.pkl` on BTC/USDT + ETH/USDT (Binance hourly)
- [ ] Portfolio-level risk: cross-asset correlation limits
- [ ] Validate live multi-symbol signal distribution before deployment

---

## Milestone 6 — Strategy Marketplace

**Target:** Allow Professional+ subscribers to submit, review, and purchase strategies.

- [ ] `POST /api/marketplace/strategies` — strategy submission with code upload
- [ ] Automated quality audit: bandit + ruff on submitted code
- [ ] Performance validation: minimum 55% win rate, Sharpe > 1.0, drawdown < 20%
- [ ] `GET /api/marketplace/strategies` — listing with filters (tier, symbol, Sharpe)
- [ ] `POST /api/marketplace/strategies/{id}/purchase` — purchase flow
- [ ] Revenue split: 70% to seller, 30% to platform
- [ ] Monthly seller payout (minimum $500 threshold)

---

## Milestone 7 — Reinforcement Learning

**Target:** Replace or augment XGBoost ensemble with a trained RL agent.

- [ ] Implement `ml/rl_agent.py` using Stable-Baselines3 (PPO)
- [ ] Custom gym environment: XAUUSD H1 with realistic slippage + spread
- [ ] Walk-forward evaluation: RL agent vs XGBoost ensemble
- [ ] Deploy only if RL OOS accuracy >= 65% with p < 0.05

---

## Milestone 8 — Web Frontend

**Target:** React dashboard connected to the REST + WebSocket API.

- [x] React + Vite scaffold in `dashboard/` (TypeScript, Tailwind CSS)
- [x] `dashboard/src/` — component structure in place
- [x] `web_dashboard.py` — FastAPI static file mount for the built dashboard
- [ ] Real-time WebSocket chart (price + signals)
- [ ] Live P&L dashboard with subscription tier badge
- [ ] Strategy control panel (start/stop/configure)
- [ ] Risk monitor (drawdown, CVaR, kill switch status)
- [ ] Subscription management UI (upgrade/downgrade/cancel)
- [ ] Social trading feed (copy trading, leaderboards)
- [ ] Production build: `npm run build` → `dashboard/dist/`

---

## Milestone 9 — Mobile App

**Target:** iOS and Android apps via React Native (Expo).

- [x] Expo React Native scaffold in `mobile-app/` (TypeScript, EAS build config)
- [x] `mobile/api.py` + `mobile/api_v2.py` — mobile-specific REST endpoints
- [x] `mobile/push_notifications.py` — FCM/APNs push notification service
- [x] `mobile/auth.py` — mobile JWT auth flow
- [x] `mobile/trading.py` — mobile trading endpoints
- [x] PWA manifest + service worker in `mobile/pwa/`
- [x] `POST /api/mobile/register-push` — device registration endpoint
- [ ] Core screens: Dashboard, Chart, Positions, Alerts (mobile-app/src/)
- [ ] Biometric authentication (LocalAuthentication)
- [ ] Subscription gate on all premium screens
- [ ] Offline mode with cached signals
- [ ] App Store + Google Play submission via EAS Submit

---

## Milestone 10 — White-Label API

**Target:** Expose HOPEFX as a signal API for third-party consumers.

- [x] `whitelabel/` module — branding config, API auth, rate limiting
- [x] `whitelabel/branding.py` — per-tenant branding overrides
- [x] `whitelabel/api_auth.py` — API key authentication for white-label clients
- [x] `whitelabel/rate_limiting.py` — per-tenant rate limit config
- [ ] `/api/v1/signals` public signal endpoint with API key auth
- [ ] Per-tier rate limits enforced at NGINX level
- [ ] Tenant onboarding flow (create tenant, issue API key, configure branding)
- [ ] SLA monitoring: 99.9% uptime target, < 200ms p99 latency gate

---

## Research Pipeline (Feature-Flagged)

All four research phases are wired in `core/signal_engine.py` and activate
after their respective paper trading gates are met.

| Phase | Component | Flag | Gate |
|-------|-----------|------|------|
| 1 | MTFFusionStore | `FEATURE_MTF_FUSION` | On by default |
| 2 | AnomalyWeightStore | `FEATURE_ANOMALY_WEIGHTING` | After 30-day paper run |
| 3 | OnlineLearnerStore | `FEATURE_ONLINE_LEARNING` | After 90-day paper run + 500 fills |
| 4 | DeepEnsembleStore | `FEATURE_DEEP_ENSEMBLE` | After LSTM OOS >= 70% |

See `research/README.md` for gate conditions and enable instructions.

---

## Type Safety (Ongoing)

- [x] `py.typed` marker present in: `api/`, `auth/`, `audit/`, `brokers/`, `config/`,
  `core/`, `execution/`, `ml/`, `mobile/`, `monetization/`, `payments/`, `risk/`,
  `strategies/`, `teams/`, `whitelabel/`
- [ ] Add `mypy` to CI with `--strict` on `api/`, `risk/`, `ml/`
- [ ] Replace remaining `Any` type hints in `brokers/`
- [ ] Add `py.typed` to remaining packages: `social/`, `notifications/`, `compliance/`, `data_layer/`

---

## VaR Remaining Work

`calculate_var_historical` and `calculate_var_parametric` still use sqrt(t) for
multi-day scaling. Use `calculate_var_multiday` or `calculate_var_ewma` for
production risk limits on XAUUSD.

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

---

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
