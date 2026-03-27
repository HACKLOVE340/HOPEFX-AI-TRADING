# CHANGELOG

All notable changes to HOPEFX-AI-TRADING are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Fixed
- `X-Forwarded-For` header now only accepted from trusted proxies (`TRUSTED_PROXY_IPS`
  env var, default `127.0.0.1,::1`). Prevents IP spoofing to bypass rate limiting.
- `FEATURE_DARK_POOL_DETECTION` description corrected: on retail feeds (OANDA,
  yfinance) this is an intraday volume z-score anomaly detector, not true dark-pool
  flow detection (which requires FINRA ATS data).

### Changed
- `FEATURE_ML_PREDICTIONS` promoted from BETA/off to STABLE/on by default.
  The 68% OOS accuracy (p=0.0000) model is the platform's core signal edge.

---

## [1.14.0] — 2026-05-30 (V14)

### Fixed
- Test suite: 2,560 passed, 0 failed (was 20 failed + 154 silent import skips).
  - Installed missing CI deps: passlib, pyjwt, hypothesis, pydantic-settings,
    aiohttp, bcrypt, keyring, lz4, msgpack, redis, structlog, xgboost, hmmlearn.
  - Fixed TestWatchlistFlow cross-test JWT secret mutation via monkeypatch autouse fixture.
  - Fixed module-scope fixture state leakage to function-scope + _reset_watchlists().
- Dedicated watchlists table: Alembic migration f1a2b3c4d5e6 verified end-to-end.
  - WatchlistEntry SQLAlchemy model added to database/models.py.
  - api/watchlist.py rewritten: DB-first, memory fallback, unique constraint at DB
    level (uq_watchlist_user_symbol).
- Sentry DSN wired for production:
  - sentry-sdk[fastapi]>=1.40.0 added to requirements.txt.
  - .env.example expanded with full production setup guide.
  - 23 unit tests covering init, PII scrubbing, health-check filtering, ML fallback alert.

---

## [1.13.0] — 2026-03-26 (V13)

### Added
- Multi-timeframe scheduler: M1, M5, M15, M30, H1, H4, D, W, M all supported.
- train_advanced.py: OOS metadata sidecar (advanced_oos_meta.json), Sharpe SE block.
- recommended_var() helper routes 1-day to historical, multi-day to EWMA.
- performance.json v13: sharpe_se, avg_hold_days, _disclaimer block.

### Fixed
- VaR sqrt(t) enforcement: ENFORCE_MULTIDAY_VAR=True blocks historical/parametric
  for time_horizon > 1.
- calculate_var_ewma: multi-day now uses overlapping windows, not sqrt(t).
- train_with_macro.py: removed deprecated use_label_encoder=False (XGBoost 2.x).
- ml/__init__.py: reads OOS metadata sidecar on load, warns if accuracy < 60%.
- Equity curve regenerated: trade-level Sharpe 1.524 +/-0.21 (N=48, avg hold 9.2d).

---

## [1.12.0] — 2026-03-25 (V12)

### Added
- FIX 4.4 execution adapter with circuit breaker and all stubs completed.
- backtest/__init__.py added; startup validation for broker/kill-switch wiring.
- Stress test module in risk/; pre_trade_gate Sentry alert wired.

### Fixed
- Silent exceptions logged in circuit breaker, kill switch, and OANDA broker.
- Vault silent failures, credential rotation, MT5 Sentry swallow fixed.
- Auth: removed duplicate constants, restricted dev token exposure to test env.

---

## [1.11.0] — 2026-03-25 (V11 — Security Audit)

### Added
- JWT auth on watchlist routes (api/watchlist.py) — previously open.
- JWT auth on chat route (api/chat.py) — eliminates OpenAI bill risk.
- 18 new API to DB to response integration tests.
- 148 source files reformatted with ruff.

### Fixed
- Sharpe ratio corrected: 5.637 to 1.817 (annualisation error fixed).
- Equity curve regenerated from real trade ticks with drawdown panel.
- Silent except ValueError: pass replaced with logging in api/monetization.py
  and api/calendar.py.
- production_fastapi_app.py deleted (was a 12-line sys.exit stub).

---

## [1.10.0] — 2026-03-24 (V10)

### Added
- ATR-based SL/TP, ML probability gate, upgraded position sizing.
- Mobile API hardening: CORS, JWT claims, risk gate, WebSocket auth.

### Fixed
- Price engine aiohttp session closed on shutdown; end-to-end wiring verified.
- Model checksum verification; dependency upper bounds; env validation.

---

## [1.9.0] — 2026-03-23 (V9)

### Added
- RegimeConditionalModel (ml/regime_conditional.py): separate XGBoost models
  for trending vs mean-reverting regimes (Hurst exponent + normalised ADX labels).
- COT proxy features (add_cot_proxy_features()): 9 stationary features including
  cot_cb_buying_proxy (central bank demand signature) and cot_geopolitical.
- 122-feature stationary pipeline: returns not prices, z-scores, ATR normalisation.
- OOS evaluation framework in train_advanced.py (--oos-years flag).
- 68.0% OOS accuracy on 3-year held-out period (p=0.0000, N=756 bars).

### Fixed
- Non-stationary price lags (close_lag_1 through close_lag_20) removed; replaced with
  returns_lag_N, log_ret_lag_N, ATR-normalised MA distances, z-scores.
- Wrong yield instrument: ^IRX (13-week T-bill) replaced with ^FVX (5-year Treasury).
- bfill() removed from fetch_macro_history(); only ffill() used — eliminates
  look-ahead bias affecting ~32% of the 50-year dataset.
- macro_gold_tailwind inverted signal logic corrected.
- Feature importance stored as column names, not integer indices.

---

## [1.8.0] — 2026-03-22 (V8)

### Added
- Prometheus metrics (41 metrics across trading, ML, risk, broker layers).
- Grafana dashboards: 4 dashboards, 27 panels.
- Discord and Telegram notification bots.
- Model degradation monitoring: Sentry fatal + Discord alert on fallback.

---

## [1.7.0] — 2026-03-21 (V7)

### Added
- TOTP 2FA: full setup/verify/disable flow (auth/).
- bcrypt password hashing (was a stub in earlier versions).
- Per-IP rate limiting: Redis-backed with in-memory fallback.
- PII scrubbing in logs and Sentry (15 field names).

---

## [1.6.0] — 2026-03-20 (V6)

### Added
- Alembic database migrations: 6 versions from initial schema to watchlists table.
- SQLAlchemy ORM throughout (parameterised queries, no raw SQL).
- ComponentRegistry: dependency-ordered startup for all 22 routers.

---

## [1.5.0] — 2026-03-19 (V5)

### Added
- Docker Compose full stack: app + PostgreSQL 16 + Redis 7 + Prometheus + Grafana.
- Dockerfile: python:3.10-slim, non-root user.
- Helm chart for Kubernetes (helm/hopefx/): HPA, PDB, secrets.
- docker-compose.yml uses ${VAR:?error} — no hardcoded credentials.

---

## [1.4.0] — 2026-03-18 (V4)

### Added
- Broker connectors: OANDA (region-routed), MT5, Alpaca, IBKR, Binance, CCXT.
- Paper trading broker with realistic fills, slippage, and commission simulation.
- FIX adapter skeleton.

---

## [1.3.0] — 2026-03-17 (V3)

### Added
- Risk stack: RiskManager, CVaR gate, VaR analytics (historical, parametric, EWMA),
  circuit breakers, kill switch.
- Backtesting engine: walk-forward, hyperopt, metrics.
- Real XAUUSD data: 2Y, 5Y, 40Y CSVs; multi-timeframe (M1, H1, H4, D).

---

## [1.2.0] — 2026-03-16 (V2)

### Added
- FastAPI server with 22 routers.
- JWT authentication (access + refresh tokens), RBAC.
- Initial ML pipeline: XGBoost + LightGBM + RandomForest ensemble.
- React/TypeScript dashboard (Vite + Tailwind + Recharts + lightweight-charts).

---

## [1.0.0] — 2026-03-15 (V1 — Initial Release)

### Added
- Core trading platform scaffold.
- OANDA REST integration for real-time XAUUSD data.
- Basic signal engine and order execution flow.
- SQLite database with initial schema.

---

## Roadmap

### Near-term (active)
- Start OANDA paper trading (30-day run required before live capital).
- Run multi-symbol backtest (XAU + BTC + ETH) to accumulate ~600 trades for
  statistically valid Sharpe (current N=48, SE +/-0.21).
- Wire ml/online_learner.py into daily startup schedule.

### Medium-term
- UI overhaul: integrate TradingView Charting Library or shadcn/ui component system.
- CORS production guard: startup validator rejects ALLOWED_ORIGINS=* in production.
- Calibrate Almgren-Chriss slippage model against real OANDA paper fills.

### Long-term
- Research pipeline LSTM/Transformer integration (Phase 3-4, requires GPU training).
- Regulatory compliance tooling (MiFID II reporting hooks).
- Community strategy marketplace.
