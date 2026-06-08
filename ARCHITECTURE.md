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
| `hopefx_engine.py` | Standalone trading engine entry point (NuclearStreamer → Brain → Risk → Broker) |
| `data_layer/orchestrator.py` | `MarketDataOrchestrator` — all price data, microstructure, and ML features flow through here |
| `strategies/strategy_brain.py` | 5-phase signal pipeline: MTF fusion → ML → regime → routing → confidence |
| `core/decision/HOPEFXDecisionEngine.py` | Central 5-phase decision pipeline: Signal → ML Enrichment → Risk Gate → Execution → Post-Trade |
| `core/startup_factories.py` | Component factory functions wired into FastAPI startup sequence |
| `ml/inference_engine.py` | Live inference: feature build → stale check → drift check → predict |
| `ml/train_advanced.py` | Offline training: XGBoost + LightGBM + RF + ET stacking, walk-forward CV |
| `risk/manager.py` | Pre-trade gate, GARCH VaR, CVaR, Kelly sizing, kill switch, prop firm enforcement |
| `execution/oms.py` | OMS: 9 order states, GTC/IOC/FOK/GTD/DAY, OCO/bracket |
| `execution/smart_router.py` | Microstructure-aware broker routing with OFI alignment and circuit breakers |
| `api/server.py` | FastAPI router aggregator — mounts all sub-routers |

---

## ML Model Facts

Source of truth: `ml/saved_models/advanced_oos_meta.json` (trained 2026-05-08, validated 2026-05-13).

| Metric | Value | Notes |
|--------|-------|-------|
| OOS accuracy | **56.5%** (SE=0.011) | Held-out OOS set, 2017-03-09 → 2026-03-18 |
| OOS F1 | **0.6885** | |
| OOS AUC | **0.5427** | Held-out OOS (2016 bars) |
| p-value | 0.0000 | One-sided binomial H0: accuracy ≤ 0.5 |
| OOS bars (N) | 2016 | 8 OOS years, 50 total years of data |
| Walk-forward AUC | 0.5936 (mean) | 6 folds; fold 2 below-chance — see `docs/FOLD2_REGIME_ANALYSIS.md` |
| Sharpe | 1.52 | SE=0.033; gate PASSED (N=2016 ≥ 600, SE ≤ 0.10) |
| Features | 193 | Stationary-tested (ADF + KPSS) |
| Horizon | 5 bars | Matches execution engine hold period |
| Trained | 2026-05-08 | `advanced_oos.pkl` — `--years 50 --oos-years 8 --stacking` |

**Nuclear RL model** (`ml/rl_models/nuclear_decision_ppo.zip`, 449 KB):
Trained via `ml/train_rl_nuclear.py`. Powers `brain/nuclear_supervisor.py`.
7-dim observation → 4 actions (NORMAL / PAUSE / HEDGE / NUCLEAR).

---

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| XGBoost stacking ensemble | ✅ Trained & deployed | `ml/saved_models/advanced_oos.pkl` — active production model |
| Nuclear PPO RL agent | ✅ Trained | `ml/rl_models/nuclear_decision_ppo.zip` — powers nuclear supervisor |
| LSTM / Transformer / TCN / Hybrid | ⚙️ Architecture complete, weights not trained | Full PyTorch implementation in `research/pipeline/models_deep.py`. Train with `DeepPredictor.fit()`, save to `ml/saved_models/lstm_signal.pt`, enable with `LSTM_SIGNAL_ENABLED=true LSTM_SIGNAL_WEIGHT=0.3` |
| PPO RL agent (live forex trading) | ⚙️ Architecture complete, weights not trained | Full SB3 PPO implementation in `ml/rl_agent.py` with `ForexTradingEnv`. Train with `RLAgentTrainer`. Saves to `ml/saved_models/rl/hopefx_ppo.zip` |
| TimeGAN synthetic data | ⚙️ Architecture complete, never run | Full WGAN-GP implementation in `research/pipeline/synthetic.py`. Run `RegimeSynthesizer.fit()` on rare-regime bars to generate augmentation data |
| C++ execution shim | ⚙️ Source complete, not compiled | ZMQ + FIX 4.4, CPU affinity, SO_BUSY_POLL in `execution/cpp_shim/hopefx_shim.cpp`. Build: `apt-get install -y cmake libzmq3-dev && cd execution/cpp_shim && make`. Enable: `CPP_SHIM_ENABLED=true` |
| Live broker credentials | ❌ Not configured | `BROKER_TYPE=paper` by default. Set `BROKER_TYPE=oanda` + `OANDA_API_KEY` + `OANDA_ACCOUNT_ID` to go live |
| OOS accuracy (full retrain) | ✅ 56.5% (N=2016) | Retrained 2026-05-08: `python ml/train_advanced.py --years 50 --oos-years 8 --stacking`. See `advanced_oos_meta.json` for full metrics. |

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

## WORDMAP.json — Nuclear/Geopolitical Risk Scorer

`WORDMAP.json` is **gitignored** (contains tuned severity weights). The nuclear
strategy system (`news/nuclear_wordmap_scorer.py`, `brain/nuclear_supervisor.py`)
loads it at startup to score geopolitical and macro events on a 0–10 severity
scale.

**The scorer works without the file.** If `WORDMAP.json` is absent, built-in
default keywords are used automatically. You only need the file to override or
extend the default weights.

### Setting up WORDMAP.json for development

```bash
cp WORDMAP.json.example WORDMAP.json
```

The example file is a fully functional starting point. It contains the same
structure as the production file with representative severity weights across
eight risk categories: `nuclear_military`, `geopolitical_conflict`,
`financial_crisis`, `central_bank`, `commodity_supply`, `pandemic_disaster`,
`political_instability`, and `sanctions_trade`.

### Customising weights

Edit `WORDMAP.json` — the `nuclear_risk` section is merged with built-in
defaults. Keys present in the file override built-in values; keys absent fall
back to built-in values. Severity scores are floats from 0.0 (no impact) to
10.0 (maximum impact).

```json
{
  "nuclear_risk": {
    "geopolitical_conflict": {
      "my custom event phrase": 7.5
    }
  }
}
```

### Verifying the scorer

```python
from news.nuclear_wordmap_scorer import NuclearWordMapScorer
scorer = NuclearWordMapScorer()
severity, action, score, meta = scorer.score_event("Central bank raises rates amid geopolitical tensions")
print(severity, meta["category_scores"])
```

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

*Last updated: 2026-04-17 (v1.19 — corrected ML model facts, component status, and key entry points)*
