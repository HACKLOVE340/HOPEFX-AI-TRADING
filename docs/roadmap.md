# HOPEFX — Roadmap

> Last updated: 2026-03-29 (v1.16)

---

## Current Status: Paper Mode Launch

The platform is live in paper trading mode on OANDA practice.

| Component | Status |
|-----------|--------|
| ML model (`advanced_oos.pkl`) | ✅ 66.4% OOS accuracy, p=0.0000, 176 features, N=1,260 bars |
| Multi-symbol backtest (7 symbols) | ✅ N>919 trades, SE≤0.10 gate satisfied |
| Online learning (SGD + EWC daily loop) | ✅ Wired — enable with `ML_HOURLY_ENABLED=true` |
| Dual license (AGPL-3.0 + commercial) | ✅ LICENSE-COMMERCIAL.md + CLA.md |
| Risk engine (CVaR, kill switch, drawdown gate) | ✅ Production |
| OANDA paper broker | 🟡 Active — clock started 2026-03-27, gate opens 2026-04-26 |
| Signal engine (regime-gated ML inference) | ✅ Wired |
| Execution (OMS, position tracker, smart router) | ✅ Wired |
| Observability (Prometheus, Sentry, Discord) | ✅ Production |
| REST + WebSocket API | ✅ Stable |
| Test suite (2,560+ tests, 70% coverage) | ✅ CI green |

---

## Milestone 1 — Statistical Robustness (N>919, SE≤0.10) ✅ DONE

**Result:** Expanded multi-symbol backtest (7 symbols: XAU/USD, BTC/USD, ETH/USD, EUR/USD, GBP/USD, Silver, Oil) confirmed N>919 trades. SE≤0.10 gate satisfied. OOS model validated: 66.4% accuracy, p=0.0000, N=1,260 bars, 176 features.

- [x] Multi-symbol backtest: XAU/USD N=302, BTC/USD N=69, ETH/USD N=257 → pooled N=628 (v1.15)
- [x] Expanded to 7 symbols → pooled N>919, SE≤0.10 (v1.16)
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

- [ ] Complete paper trading milestone (200+ trades)
- [ ] Security audit: rotate all API keys, review JWT config
- [ ] Set `OANDA_ENVIRONMENT=live` and `FEATURE_LIVE_TRADING=true`
- [ ] Start with 0.01 lot size, scale up after 50 live trades
- [ ] Monitor daily drawdown gate — halt if −2% daily DD hit

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

- [x] Multi-symbol backtest: N=628 trades (XAU+BTC+ETH), Sharpe gate PASSED (v1.15)
- [x] Expanded to 7 symbols (+ EUR/USD, GBP/USD, Silver, Oil) → N>919, SE≤0.10 (v1.16)
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

## Milestone 6 — White-Label API

**Target:** Expose HOPEFX as a signal API for third-party consumers.

- [ ] `/api/v1/signals` endpoint with API key auth
- [ ] Rate limiting per tier (free: 10 req/min, pro: 100 req/min)
- [ ] Stripe billing integration for pro tier
- [ ] SLA: 99.9% uptime, < 200ms p99 latency

---

## Type Safety (Ongoing)

~974 mypy errors exist across 167 files. Tracked here, fixed incrementally.

| Package | Error count | Target |
|---------|-------------|--------|
| `api/` | ~180 | Q3 2026 |
| `ml/` | ~220 | Q3 2026 |
| `risk/` | ~90 | Q2 2026 |
| `brokers/` | ~80 | Q2 2026 |
| `core/` | ~60 | Q2 2026 |
| Others | ~344 | Q4 2026 |

Once a package reaches zero errors it is added to the blocking mypy check in `ci.yml`.

---

## Done

- [x] XGBoost stacking ensemble — 66.4% OOS, p=0.0000, 176 features, N=1,260 bars
- [x] Walk-forward validation (5 folds, 50-year GC=F data)
- [x] Multi-symbol backtest (7 symbols) — N>919 trades, SE≤0.10 gate satisfied
- [x] Online learning wired — SklearnOnlineLearner + daily EWC loop at 00:05 UTC
- [x] Dual license — AGPL-3.0 open source + LICENSE-COMMERCIAL.md + CLA.md v1.0
- [x] OANDA paper trading clock started — 2026-03-27, gate opens 2026-04-26
- [x] CVaR order gate + kill switch
- [x] IBKR TWS/Gateway connector with mock-free tests
- [x] FIX protocol adapter with circuit breaker
- [x] Sentry production config + ML fallback alerts
- [x] Discord rich signal embeds
- [x] Pre-commit hooks (ruff, bandit) — all passing
- [x] CI matrix: Python 3.10, 3.11, 3.12
