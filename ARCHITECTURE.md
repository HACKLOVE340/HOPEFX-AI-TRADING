# HOPEFX AI Trading — Architecture Reference

> For the full system architecture see [`docs/architecture.md`](docs/architecture.md).
> This file documents canonical module locations and resolves naming ambiguities.

---

## Canonical Module Map

When two directories appear to serve the same purpose, use the **canonical** one.
The legacy directory is kept as a compatibility shim and must not receive new code.

| Domain | Canonical | Legacy / Shim | Notes |
|--------|-----------|---------------|-------|
| Backtesting | `backtesting/` | `backtest/` | `backtest/` re-exports from `backtesting/` |
| Strategies | `strategies/` | `strategy/` | `strategy/` = live ML engine; `strategies/` = backtestable classes |
| Data pipeline | `data_layer/` | `data/` | `data/` = CSV files + pre-`data_layer/` utilities |
| WebSocket | `api/ws_live.py` | `websocket/manager.py` | `websocket/manager.py` = standalone server; FastAPI uses `api/ws_live.py` |

---

## Key Entry Points

| File | Purpose |
|------|---------|
| `app.py` | FastAPI application factory, startup/shutdown lifecycle |
| `core/orchestrator.py` | Single `MarketDataOrchestrator` — all price data flows through here |
| `brain/strategy_brain.py` | 5-phase signal pipeline: MTF fusion → ML → regime → routing → confidence |
| `ml/inference_engine.py` | Live inference: feature build → stale check → drift check → predict |
| `ml/train_advanced.py` | Offline training: XGBoost + LightGBM + RF stacking, 8-fold walk-forward CV |
| `risk/risk_manager.py` | Pre-trade gate, VaR, kill switch, prop firm enforcement |
| `execution/order_manager.py` | OMS: 9 order states, GTC/IOC/FOK/GTD/DAY, OCO/bracket |
| `api/router.py` | FastAPI router aggregator — mounts all sub-routers |

---

## ML Model Facts

These are the actual values from `ml/saved_models/advanced_oos_meta.json`.
Do not use the README figures — they were from an earlier run.

| Metric | Value |
|--------|-------|
| OOS accuracy | **59.92%** |
| OOS F1 | 0.6885 |
| OOS AUC | 0.6077 |
| p-value | 0.0000 |
| OOS bars (N) | 2,016 |
| Sharpe | 1.52 |
| Features | 222 (262 after MTF upgrade — requires retraining) |
| Horizon | 5 bars |
| Trained | 2026-04-02 |

---

## Confirmed Gaps (not yet implemented)

| Component | Status | Notes |
|-----------|--------|-------|
| LSTM / Transformer / TCN weights | ❌ Not trained | Architecture in `research/pipeline/models_deep.py`; no `.pt` file |
| PPO RL agent (live trading) | ❌ Not trained | `ml/saved_models/rl/` is empty |
| TimeGAN synthetic data | ❌ Never run | `research/pipeline/synthetic.py` exists; no output |
| C++ shim binary | ❌ Not compiled | Source in `execution/cpp_shim/`; run `make` to build |
| Live broker credentials | ❌ Not set | `BROKER_TYPE=paper` by default |

---

## Security Fixes Applied (v1.18)

| # | Fix | File |
|---|-----|------|
| 1 | LLM sandbox subprocess isolation | `brain/llm_agent.py` |
| 2 | WebSocket JWT auth gate | `websocket/manager.py` |
| 3 | Redis TLS enforcement in production | `cache/redis_client.py` |
| 4 | detect-secrets pre-commit hook | `.pre-commit-config.yaml` |
| 5 | Gitignore WORDMAP.json + prop_firm_mode.json | `.gitignore` |
| 6 | .env.example deduplication + path redaction | `.env.example` |
| 7 | Terms of Service + Risk Disclosure pages | `frontend/src/pages/TermsAndRiskDisclosure.tsx` |
| 8 | Signal disclaimer on all API responses | `api/signals.py` |
| 9 | C++ shim build script + Makefile | `execution/cpp_shim/` |
| 10 | Stale model blocks inference in production | `ml/inference_engine.py` |
| 11 | This file | `ARCHITECTURE.md` |
| 12 | Live/paper mode indicator on health + dashboard | `api/health.py`, frontend header |
| 13 | Prop firm 80% drawdown Telegram alert | `notifications/telegram_bot.py` |

---

## Environment Variables — Key Flags

| Variable | Default | Effect |
|----------|---------|--------|
| `BROKER_TYPE` | `paper` | `paper` / `live` — controls execution routing |
| `STALE_MODEL_BLOCK` | `true` | Block inference when model > `MODEL_MAX_AGE_DAYS` old |
| `DRIFT_BLOCK` | `true` | Block signals when feature drift detected |
| `ENFORCE_MULTIDAY_VAR` | `true` | Raise on sqrt(t) VaR scaling in production |
| `WS_AUTH_REQUIRED` | `true` | Require JWT on WebSocket connections |
| `REDIS_FORCE_TLS` | `false` | Auto-upgrade `redis://` → `rediss://` |
| `APP_ENV` | `production` | `production` enforces Redis TLS, stale model block |

---

*Last updated: 2026-04-09 (v1.18)*
