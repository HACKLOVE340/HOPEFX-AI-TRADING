# HOPEFX — Roadmap

> Last updated: 2026-07-14 (v1.17)

---

## Current Status: Paper Trading — Promotion and Operations Gated

The platform is actively maintained in paper-trading mode. Live trading is not
considered ready solely because the paper run reaches 30 days: model promotion,
broker reconciliation, restart recovery, execution safety, security scans, and
operator approval must also pass. Do not enable live trading by only flipping
environment variables.

| Component | Status |
|-----------|--------|
| ML model (`advanced_oos.pkl`) | ⚠️ Paper-trading candidate; promotion requires current OOS metadata and reviewed gates |
| Stacking ensemble (XGB+LGB+RF+ET) | ✅ Production |
| Fractal geometry features (Lyapunov, HFD, DFA, ApEn) | ✅ Production |
| EWC online learning (SGD + daily regime loop) | ✅ Production — enable with `ML_HOURLY_ENABLED=true` |
| RL agent (PPO, walk-forward eval) | ✅ Production |
| GARCH(1,1) VaR + multi-day VaR (overlapping returns) | ✅ Production |
| Multi-symbol backtest (7 symbols) | ✅ N>919 trades, SE≤0.10 gate satisfied |
| Nuclear strategy system (Itô cones + shadow backtest) | ✅ Production |
| Geopolitical risk + WORDMAP scorer | ✅ Production |
| Risk engine (CVaR, kill switch, drawdown gate, Kelly) | ✅ Production |
| Prop-firm compliance (FTMO, The5ers, TopStep, MFF, Goat) | ✅ Production |
| Execution (FIX, TWAP/VWAP/Iceberg, Almgren-Chriss TCA) | ✅ Production |
| Smart order router (latency + OFI + sentiment scoring) | ✅ Production |
| OMS + position tracker | ✅ Production |
| Broker connectors (OANDA, IBKR, MT5, Binance, Bybit, Alpaca, CCXT) | ✅ Production |
| MT5 ZeroMQ bridge + MQL5 EA | ✅ Production |
| L2 order book (Polygon quotes + Finnhub trade tape collated) | ✅ Production |
| Microstructure engine (Kyle's lambda, Lee-Ready, OBI, VWAP dev) | ✅ Production |
| Multi-source WebSocket streamer (Polygon + Finnhub + Twelve Data) | ✅ Production |
| Signal engine (regime-gated ML inference) | ✅ Production |
| HOPEFXBrain (multi-TF fusion, confidence-weighted aggregation) | ✅ Production |
| REST + WebSocket + GraphQL API (108+ endpoints) | ✅ Production |
| JWT auth + RBAC + 2FA | ✅ Production |
| AML gate + KYC + regulatory reporter | ✅ Production |
| Security (HSM vault, global fortress, RL-based response, self-healer) | ✅ Production |
| Stripe subscription platform (dunning, plan gates, invoicing) | ✅ Production |
| Strategy marketplace (submission, purchase, revenue split, licensing) | ✅ Production |
| Copy trading + social feed + leaderboards | ✅ Production |
| White-label API (per-tenant auth, rate limiting, branding) | ✅ Production |
| React frontend (38 pages, real-time charts, order book depth) | ✅ Production |
| Mobile app (19 screens, biometric auth, push notifications) | ✅ Production |
| No-code strategy builder | ✅ Production |
| Observability (Prometheus, Grafana, Sentry, Discord) | ✅ Production |
| Docker + Kubernetes + Helm + ArgoCD | ✅ Production |
| Chaos engineering (7 fault injection scenarios) | ✅ Production |
| CI/CD (15 GitHub Actions workflows, mypy, bandit, ruff) | ✅ Production |
| Test suite (2,560+ tests, 70% coverage gate) | ⚠️ Must be verified by current CI; local environments may lack test dependencies |
| Dual license (AGPL-3.0 + commercial) | ✅ LICENSE-COMMERCIAL.md + CLA.md |

---

## Milestone 1 — Statistical Robustness ✅ DONE

**Result:** Multi-symbol backtest (7 symbols: XAU/USD, BTC/USD, ETH/USD, EUR/USD,
GBP/USD, Silver, Oil) confirmed N>919 trades. SE≤0.10 gate satisfied. OOS model
validated: 66.4% accuracy, p=0.0000, N=1,260 bars, 176 features.

- [x] Multi-symbol backtest: XAU/USD N=302, BTC/USD N=69, ETH/USD N=257 → pooled N=628
- [x] Expanded to 7 symbols → pooled N>919, SE≤0.10
- [x] OOS metadata validated and stamped (`advanced_oos_meta.json`)
- [x] OrderGateway wired to TradeExecutor — real routing, no stub
- [x] Walk-forward validation: 5-fold anchored expanding windows
- [x] Sharpe circuit breaker — pulls model mid-session if live Sharpe degrades
- [x] API endpoints: /api/ml/health, /api/backtest/multi-symbol, /api/online-learner/status+partial-fit

---

## Milestone 2 — Monetization ✅ DONE

**Result:** Full subscription platform live. Stripe SDK integrated, plan gating
enforced on all trading and ML endpoints, dunning active, marketplace complete.

- [x] Real Stripe PaymentIntent creation with idempotency keys
- [x] Stripe Refund API with partial-refund support
- [x] Dunning: 3x retry at 24h / 72h / 168h, then subscription suspended
- [x] `plan_gate()` enforcement in all endpoints — raises `403 PLAN_LIMIT_EXCEEDED`
- [x] ML `/predict` endpoint gated at Professional plan
- [x] Trading `/order` endpoint gated at Starter plan
- [x] Prometheus: `hopefx_mrr_usd`, `hopefx_arr_usd`, `hopefx_churn_rate_pct`
- [x] Payment / cancellation / renewal / trial expiry emails
- [x] Admin role guard on all `/api/admin/*` endpoints
- [x] Admin impersonation JWT (5 min, audit-logged)
- [x] Strategy marketplace: submission, purchase flow, license key generation/validation
- [x] Revenue split: 70% seller / 30% platform, monthly payout logic
- [x] Affiliate system, access codes, crypto checkout
- [x] Multi-currency pricing engine with coupon support

---

## Milestone 3 — Live OANDA Run ⏳ NEXT

**Target:** First real-money trade on OANDA live account.

Three switches to flip — no code changes required:

- [ ] Complete 30-day paper trading run (gate: `data/oanda_paper_start.json`, started 2026-03-27)
- [ ] 200+ paper trades logged with zero execution errors
- [ ] Set `OANDA_ENVIRONMENT=live` and `FEATURE_LIVE_TRADING=true`
- [ ] Switch Stripe to live mode (`sk_test_` → `sk_live_`)
- [ ] Rotate all API keys, review JWT config before go-live
- [ ] Start with 0.01 lot size, scale after 50 live trades
- [ ] Monitor daily drawdown gate — halt if −2% daily DD hit

```bash
python scripts/enable_live_trading.py --check-only
```

---

## Milestone 4 — MT5 Export ✅ DONE

**Result:** Full ZeroMQ bridge implemented with custom MQL5 EA.

- [x] `brokers/mt5_broker.py` — MT5 broker connector (MetaTrader5 Python API)
- [x] `brokers/mt5_zmq_bridge.py` — ZeroMQ bridge: send_order, close_position, modify_position, ping, publish_signal
- [x] `brokers/mql5/HopeFX_ZMQ_EA.mq5` — MT5 EA subscriber (custom MQL5 protocol)
- [x] `data_feed/mt5_backup.py` — MT5 backup price feed
- [x] JSON message protocol: ORDER / CLOSE / MODIFY / PING commands
- [x] Round-trip fill confirmation with timeout handling

---

## Milestone 5 — Multi-Symbol Expansion ✅ DONE

**Result:** 7-symbol backtest complete. Portfolio-level risk wired.

- [x] Multi-symbol backtest: N=628 trades (XAU+BTC+ETH), Sharpe gate PASSED
- [x] Expanded to 7 symbols (+ EUR/USD, GBP/USD, Silver, Oil) → N>919, SE≤0.10
- [x] Portfolio factor model (`portfolio/factor_model.py`)
- [x] Cross-asset correlation limits in risk manager
- [x] Broker connectors for crypto: Binance, Bybit, CCXT (50+ exchanges)

---

## Milestone 6 — Strategy Marketplace ✅ DONE

**Result:** Full marketplace built with submission, validation, purchase, and payout.

- [x] Strategy submission with code upload
- [x] Automated quality audit: bandit + ruff on submitted code
- [x] Performance validation: win rate, Sharpe, drawdown gates
- [x] Strategy listing with filters (tier, symbol, Sharpe)
- [x] Purchase flow with Stripe integration
- [x] Revenue split: 70% seller / 30% platform
- [x] License key generation, validation, revocation
- [x] Monthly seller payout logic (minimum threshold)

---

## Milestone 7 — Reinforcement Learning ✅ DONE

**Result:** PPO agent implemented with walk-forward evaluation framework.

- [x] `ml/rl_agent.py` — Stable-Baselines3 PPO on real Gymnasium environment
- [x] `ForexTradingEnv` — 32-dim feature vector, Discrete(3) action space, Sharpe-like reward
- [x] `RLAgent` — train / evaluate / predict API, saves to `ml/saved_models/rl/`
- [x] `walk_forward_eval` — 5-fold anchored expanding windows, per-fold metrics
- [x] `RLAgentTrainer` — async trainer, broker-agnostic candle source
- [x] `ml/train_rl_nuclear.py` — nuclear security RL agent (separate action space)

---

## Milestone 8 — Web Frontend ✅ DONE

**Result:** Full React dashboard built and wired to all API endpoints.

- [x] React + Vite + TypeScript + Tailwind CSS in `frontend/`
- [x] 38 pages: Trading, Dashboard, Performance, Nuclear, TCA, WalkForward, PropFirmTracker, SecurityDashboard, SuperAdmin, Marketplace, CopyTrading, SocialFeed, Leaderboard, Wallet, TradeJournal, and more
- [x] Real-time candlestick chart (`lightweight-charts`, wired to `/api/trading/ohlcv/{symbol}`)
- [x] Live price via Zustand WebSocket store with REST fallback
- [x] Order book depth panel, microstructure panel, ML model panel, risk dashboard
- [x] Live signal feed, order entry form, positions table
- [x] Subscription gate component, global attack map, fix approval queue
- [x] Super admin dashboard with impersonation, white-label admin panel
- [x] E2E tests (Playwright)

---

## Milestone 9 — Mobile App ✅ DONE

**Result:** Full React Native app built with 19 screens.

- [x] Expo React Native + TypeScript in `mobile-app/`
- [x] Screens: Dashboard, Trading, Signals, Portfolio, Alerts, Performance, Risk, Watchlist, Notifications
- [x] Auth: Login, Register, ForgotPassword, TwoFactor, BiometricSetup
- [x] Trading: PlaceOrder, OrderDetail, OrdersScreen, PositionDetail
- [x] Biometric authentication, FCM/APNs push notifications
- [x] PWA manifest + service worker, mobile JWT auth + 2FA
- [x] Mobile-specific REST endpoints (`mobile/api.py`, `mobile/api_v2.py`)

---

## Milestone 10 — White-Label API ✅ DONE

**Result:** Full white-label platform built with per-tenant auth and rate limiting.

- [x] HMAC-SHA256 API key auth with `require_api_key` + `require_feature` guards
- [x] Per-tenant branding overrides, rate limit config, schema
- [x] Tenant API key registration, revocation, tier management
- [x] Per-tier feature gating (`ml_signals`, `live_trading`, etc.)
- [x] Rate limiting with Redis backend + in-memory fallback
- [x] White-label admin panel in frontend

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

---

## Running the ML Pipeline

```bash
# Production model (176 features, 50-year data, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Stacking ensemble (XGB + LGB + RF + ET)
python ml/train_advanced.py --years 50 --oos-years 3 --stacking

# Multi-symbol backtest (7 symbols, 10-year real data)
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3

# Smoke test (~30 s)
python ml/train_advanced.py --smoke
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
pytest tests/unit/ -q
pytest tests/integration/ -q
```
