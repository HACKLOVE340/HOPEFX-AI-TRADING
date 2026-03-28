# HOPEFX — Institutional-Grade Enhancement Plan
# V1.0 — Definitive Blueprint for World-Top AI Trading System

> **Audit base:** commit `764f124` · CRITICAL_FLAWS.md V14 · 2560 tests passing
> **Author:** Quant Architecture Review — generated against live codebase
> **Scope:** Every file, folder, and integration point. Nothing omitted.

---

## Table of Contents

1. [Current State Snapshot](#1-current-state-snapshot)
2. [Immediate Blockers — 3 Open CRITICAL_FLAWS Items](#2-immediate-blockers)
3. [Phased Roadmap Overview](#3-phased-roadmap-overview)
4. [Phase 1 — Pre-Live Capital (Weeks 1–4)](#4-phase-1-pre-live-capital)
5. [Phase 2 — Institutional Hardening (Months 1–3)](#5-phase-2-institutional-hardening)
6. [Phase 3 — World-Top Capability (Months 3–6+)](#6-phase-3-world-top-capability)
7. [ML & Signals — Full Enhancement Catalogue](#7-ml--signals)
8. [Risk & Compliance — Full Enhancement Catalogue](#8-risk--compliance)
9. [Execution & OMS — Full Enhancement Catalogue](#9-execution--oms)
10. [Data & Infrastructure — Full Enhancement Catalogue](#10-data--infrastructure)
11. [Observability & Security — Full Enhancement Catalogue](#11-observability--security)
12. [Commercial & SaaS — Full Enhancement Catalogue](#12-commercial--saas)
13. [Future-Proofing — Full Enhancement Catalogue](#13-future-proofing)
14. [Testing & Rollback Strategy](#14-testing--rollback-strategy)
15. [Executive Summary](#15-executive-summary)

---

## 1. Current State Snapshot

| Domain | Status | Gap to World-Top |
|--------|--------|-----------------|
| ML accuracy (OOS) | 66.4%, p=0.0000 (176 features) | Need 68–72% sustained; hybrid ensemble not in prod |
| Paper trades | ~48 live fills | Need 250–500+ for Sharpe SE ≤ 0.10 |
| OANDA paper clock | Started 2026-03-27 | 30-day gate not yet confirmed complete |
| LSTM/Transformer | Exists in `research/pipeline/models_deep.py` | Not wired into `ml/inference_engine.py` |
| Online learning | SGD + EWC in `ml/online_learner.py` | `FEATURE_ONLINE_LEARNING=false` — not activated |
| Smart router | `brokers/smart_router.py` | No latency-aware routing; no DMA path |
| Risk stack | CVaR gate, kill switch, <1% cap | No portfolio-level CVaR; no TCA live calibration |
| Observability | Sentry wired, Prometheus partial | No Grafana dashboards; no chaos tests in CI |
| Feature store | None | No versioned feature store; no drift detection |
| Alternative data | COT proxy only | No real COT, no news NLP, no satellite |
| Commercial | Stripe billing exists | No SaaS multi-tenant isolation; no white-label |
| Regulatory | FIA compliance stub | No MiFID II TCA reports; no audit trail export |

---

## 2. Immediate Blockers

These 3 items from CRITICAL_FLAWS.md V14 must be resolved before any live capital.

---

### Blocker 1 — 30-Day OANDA Paper Clock Not Confirmed Complete

**Why it matters:** The `PaperTradingGate` in `research/pipeline/paper_trading_gate.py`
gates Phase 2 (anomaly weighting) and Phase 3 (online learning) on elapsed calendar days.
Without a confirmed 30-day run, these features cannot be safely enabled.

**Current state:** Clock started 2026-03-27 per `data/oanda_paper_start.json`.
The `OandaPaperClock` in `brokers/oanda_paper_clock.py` writes the stamp on first
successful OANDA connect. The gate reads `OANDA_PAPER_RUN_START_UTC` env var.

**Exact steps to resolve:**

```bash
# Step 1 — Verify stamp file exists and is valid
python -c "
import json, datetime
from pathlib import Path
stamp = json.loads(Path('data/oanda_paper_start.json').read_text())
start = datetime.datetime.fromisoformat(stamp['started_at'])
elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).days
print(f'Started: {start}')
print(f'Elapsed: {elapsed} days')
print(f'Gate open: {elapsed >= 30}')
"

# Step 2 — Check gate status via CLI
python -m research.pipeline.paper_trading_gate --status

# Step 3 — Verify OANDA_PAPER_RUN_START_UTC is set in .env
grep OANDA_PAPER_RUN_START_UTC .env || echo "MISSING — set it now"

# Step 4 — If stamp exists but env var missing, sync them
python -c "
import json
from pathlib import Path
stamp = json.loads(Path('data/oanda_paper_start.json').read_text())
print(f'Add to .env: OANDA_PAPER_RUN_START_UTC={stamp[\"started_at\"]}')
"
```

**File changes required:**

| File | Change |
|------|--------|
| `brokers/oanda_paper_clock.py` | Add `assert_clock_running()` that raises `RuntimeError` if stamp missing — called at startup |
| `core/startup_factories.py` | Call `OandaPaperClock().assert_clock_running()` in paper-mode startup |
| `api/status.py` | Expose `/api/status/paper-clock` endpoint returning days elapsed, fills, gate status |
| `.env.example` | Add `OANDA_PAPER_RUN_START_UTC=` with instructions |

**Robustness:** The stamp file must be in a Docker volume mount (`/data/`) so it
survives container restarts. Add `data/oanda_paper_start.json` to `.gitignore` but
document the volume mount in `docker-compose.yml`.

---

### Blocker 2 — Paper Trade Count ~48, Need 250–500+

**Why it matters:** At N=48, Sharpe SE ≈ ±0.21 — statistically meaningless.
The `test_trade_count_sharpe_se.py` gate requires N ≥ 250 for SE ≤ 0.10.
The multi-symbol backtest already shows N=919 across 7 symbols, but live paper
fills are what count for the Phase 3 gate.

**Root cause:** The signal threshold is too conservative (`SIGNAL_THRESHOLD_LONG=0.58`,
`SIGNAL_THRESHOLD_SHORT=0.42`). At 66.4% OOS accuracy, the model generates signals
on ~34% of bars, but the asymmetric threshold further filters to ~15% of bars.
On H1 data with ~720 bars/month, that yields ~108 signals/month — but many are
filtered by the `SignalFilter` non-neutral rate check and regime filter.

**Exact steps to resolve:**

```bash
# Step 1 — Audit current signal generation rate
python -c "
from ml.inference_engine import get_inference_engine
engine = get_inference_engine()
stats = engine.get_stats()
print(stats)
"

# Step 2 — Lower thresholds temporarily for paper accumulation
# In .env (paper mode only):
# SIGNAL_THRESHOLD_LONG=0.55
# SIGNAL_THRESHOLD_SHORT=0.45
# PAPER_TRADE_ACCUMULATION_MODE=true

# Step 3 — Enable multi-symbol paper trading (7 symbols already backtested)
# In .env:
# PAPER_SYMBOLS=XAU_USD,EUR_USD,GBP_USD,XAG_USD,BCO_USD,BTC_USD,ETH_USD

# Step 4 — Add M15/M30 timeframes to paper trading (more signals per day)
# In config/settings.py: PAPER_TIMEFRAMES = ["M15", "M30", "H1"]

# Step 5 — Monitor fill count
python -m research.pipeline.paper_trading_gate --status
```

**File changes required:**

| File | Change |
|------|--------|
| `config/settings.py` | Add `PAPER_TRADE_ACCUMULATION_MODE: bool = False`; when True, lower thresholds to 0.55/0.45 |
| `ml/signal_filter.py` | Add `accumulation_mode` bypass that skips non-neutral rate throttle |
| `brokers/paper_trading.py` | Add multi-symbol support — iterate `PAPER_SYMBOLS` env var |
| `research/pipeline/paper_trading_gate.py` | Add `fill_velocity_check()` — warn if < 5 fills/day |
| `data/scheduler.py` | Add M15 + M30 paper trading loops alongside H1 |

**Safety:** Accumulation mode must be gated behind `PAPER_MODE=true` check.
It must never activate in live mode. Add assertion in `core/live_trading_gate.py`.

---

### Blocker 3 — LSTM/Transformer Hybrid Not Wired into Production Inference

**Why it matters:** `research/pipeline/models_deep.py` contains production-quality
`LSTMPredictor`, `TransformerPredictor`, `TemporalConvNet`, and `HybridModel` classes.
`ml/models/lstm.py` has a Keras-based LSTM. Neither is called from
`ml/inference_engine.py`. The ensemble in `advanced_oos.pkl` is XGBoost-only.

**Architecture for safe wiring (optional production layer):**

```
InferenceEngine.predict()
    ├── XGBoost ensemble (advanced_oos.pkl)          ← primary (always runs)
    ├── DeepEnsembleLayer (optional, feature-flagged) ← new
    │   ├── HybridModel (TCN+LSTM)                   ← research/pipeline/models_deep.py
    │   └── TransformerPredictor                     ← research/pipeline/models_deep.py
    └── SignalFusion.combine(xgb_prob, deep_prob)    ← weighted average with confidence gate
```

**Exact steps to resolve:**

**Step 1 — Create `ml/deep_ensemble_layer.py`:**

```python
# ml/deep_ensemble_layer.py
"""
Optional deep learning signal layer.
Loaded only when FEATURE_DEEP_ENSEMBLE=true and models exist.
Falls back silently if PyTorch unavailable or models not trained.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

_SAVED = Path(__file__).parent / "saved_models"
_ENABLED = os.getenv("FEATURE_DEEP_ENSEMBLE", "false").lower() == "true"
_WEIGHT = float(os.getenv("DEEP_ENSEMBLE_WEIGHT", "0.25"))  # 25% weight in fusion


class DeepEnsembleLayer:
    """
    Wraps HybridModel + TransformerPredictor from research/pipeline/models_deep.py.
    Provides a single predict(X_seq) -> float interface for InferenceEngine.
    """

    def __init__(self) -> None:
        self._hybrid = None
        self._transformer = None
        self._loaded = False
        if _ENABLED:
            self._load()

    def _load(self) -> None:
        try:
            from research.pipeline.models_deep import HybridModel, TransformerPredictor
            hybrid_path = _SAVED / "hybrid_model.pt"
            transformer_path = _SAVED / "transformer_model.pt"
            if hybrid_path.exists():
                self._hybrid = HybridModel(...)
                self._hybrid.load(hybrid_path)
            if transformer_path.exists():
                self._transformer = TransformerPredictor(...)
                self._transformer.load(transformer_path)
            self._loaded = bool(self._hybrid or self._transformer)
            logger.info("DeepEnsembleLayer loaded: hybrid=%s transformer=%s",
                        bool(self._hybrid), bool(self._transformer))
        except Exception as exc:
            logger.warning("DeepEnsembleLayer load failed (non-fatal): %s", exc)

    def predict(self, X_seq: np.ndarray) -> Optional[float]:
        """Returns probability [0,1] or None if unavailable."""
        if not self._loaded:
            return None
        probs = []
        try:
            if self._hybrid:
                probs.append(float(self._hybrid.predict(X_seq)[0]))
            if self._transformer:
                probs.append(float(self._transformer.predict(X_seq)[0]))
            return float(np.mean(probs)) if probs else None
        except Exception as exc:
            logger.warning("DeepEnsembleLayer predict failed: %s", exc)
            return None

    @property
    def is_available(self) -> bool:
        return self._loaded
```

**Step 2 — Wire into `ml/inference_engine.py`:**

```python
# In InferenceEngine.__init__():
from ml.deep_ensemble_layer import DeepEnsembleLayer
self._deep_layer = DeepEnsembleLayer()

# In InferenceEngine._fuse_signals():
xgb_prob = self._predictor.predict_proba(X)
deep_prob = self._deep_layer.predict(X_seq)  # X_seq = last 60 bars reshaped

if deep_prob is not None and _DEEP_ENSEMBLE_WEIGHT > 0:
    fused = (1 - _DEEP_ENSEMBLE_WEIGHT) * xgb_prob + _DEEP_ENSEMBLE_WEIGHT * deep_prob
    self._metrics["deep_ensemble_active"] = True
else:
    fused = xgb_prob
    self._metrics["deep_ensemble_active"] = False
```

**Step 3 — Training script for deep models:**

```bash
# New file: ml/train_deep_ensemble.py
# Trains HybridModel + TransformerPredictor on the same 176-feature dataset
# Saves to ml/saved_models/hybrid_model.pt + transformer_model.pt
# Runs OOS evaluation and writes ml/saved_models/deep_ensemble_meta.json
python ml/train_deep_ensemble.py --years 7 --oos-years 2 --seq-len 60
```

**File changes required:**

| File | Change | Effort |
|------|--------|--------|
| `ml/deep_ensemble_layer.py` | New — wrapper with graceful fallback | 2h |
| `ml/train_deep_ensemble.py` | New — training script for HybridModel + Transformer | 4h |
| `ml/inference_engine.py` | Wire `DeepEnsembleLayer` into `_fuse_signals()` | 1h |
| `config/feature_flags.py` | Add `FEATURE_DEEP_ENSEMBLE` flag | 30m |
| `api/ml.py` | Expose `/api/ml/deep-ensemble/status` | 30m |
| `tests/unit/test_deep_ensemble.py` | Already exists — update to test new wiring | 1h |

**Safety gates:**
- `FEATURE_DEEP_ENSEMBLE=false` by default
- Deep layer weight capped at 0.35 (`MAX_DEEP_ENSEMBLE_WEIGHT=0.35`)
- If deep model OOS accuracy < XGBoost OOS accuracy, weight auto-set to 0
- Sentry alert if deep layer degrades live Sharpe by > 0.1 over 30-day window

---

## 3. Phased Roadmap Overview

| Phase | Timeline | Capital Status | Primary Goal |
|-------|----------|---------------|--------------|
| **Phase 1** | Weeks 1–4 | Paper only | Close 3 blockers; harden execution path |
| **Phase 2** | Months 1–3 | Paper → micro-live ($1k–$10k) | Institutional ML, risk, and infra hardening |
| **Phase 3** | Months 3–6+ | Scaled live | World-top capabilities; commercial launch |

### Effort Estimates

| Category | Phase 1 | Phase 2 | Phase 3 |
|----------|---------|---------|---------|
| ML & Signals | 20h | 80h | 160h |
| Risk & Compliance | 10h | 40h | 80h |
| Execution & OMS | 8h | 30h | 60h |
| Data & Infrastructure | 6h | 40h | 120h |
| Observability & Security | 8h | 20h | 40h |
| Commercial & SaaS | 0h | 20h | 80h |
| Testing | 10h | 30h | 60h |
| **Total** | **62h** | **260h** | **600h** |

---

## 4. Phase 1 — Pre-Live Capital (Weeks 1–4)

**Gate:** All items below must be green before any live capital is deployed.

### P1.1 — Close Blocker 1: Confirm Paper Clock

**Files:** `brokers/oanda_paper_clock.py`, `core/startup_factories.py`, `api/status.py`

```python
# brokers/oanda_paper_clock.py — add to OandaPaperClock class:
def assert_clock_running(self) -> None:
    """Raise RuntimeError if paper clock has not been started."""
    if not self._stamp_path.exists():
        raise RuntimeError(
            "OANDA paper clock not started. "
            "Set OANDA_API_KEY and connect to OANDA practice account. "
            "See docs/PAPER_TRADING_SETUP.md"
        )
    status = self.status()
    if status["elapsed_days"] < 1:
        raise RuntimeError(
            f"Paper clock stamp exists but elapsed={status['elapsed_days']}d. "
            "Check system clock and stamp file integrity."
        )
```

**Monitoring:** Add Grafana panel `paper_clock_elapsed_days` from Prometheus gauge.
Alert if clock stops incrementing (process crash detection).

---

### P1.2 — Close Blocker 2: Accelerate Paper Fill Accumulation

**Files:** `config/settings.py`, `ml/signal_filter.py`, `brokers/paper_trading.py`,
`data/scheduler.py`

**Key change — multi-symbol paper trading loop:**

```python
# data/scheduler.py — add alongside existing H1 loop:
PAPER_SYMBOLS = os.getenv("PAPER_SYMBOLS", "XAU_USD").split(",")
PAPER_TIMEFRAMES = os.getenv("PAPER_TIMEFRAMES", "H1").split(",")

async def paper_trading_loop():
    for symbol in PAPER_SYMBOLS:
        for tf in PAPER_TIMEFRAMES:
            bars = await fetch_bars(symbol, tf, count=200)
            signal = engine.predict(bars, symbol=symbol)
            if signal["direction"] != "neutral":
                await paper_broker.place_order(symbol, signal, timeframe=tf)
```

**Target:** 10–20 fills/day across 7 symbols × 3 timeframes = 250+ fills in 2 weeks.

---

### P1.3 — Close Blocker 3: Wire Deep Ensemble (Feature-Flagged)

**Files:** `ml/deep_ensemble_layer.py` (new), `ml/train_deep_ensemble.py` (new),
`ml/inference_engine.py`, `config/feature_flags.py`

See detailed implementation in Section 2, Blocker 3 above.

**Validation gate before enabling:**
```bash
python ml/train_deep_ensemble.py --years 7 --oos-years 2
# Must show: deep_oos_accuracy >= xgb_oos_accuracy - 0.02
# i.e., within 2% of XGBoost before enabling in production
```

---

### P1.4 — Execution Path Hardening

**Why:** Before live capital, every order path must be audited end-to-end.
Current gap: `execution/engine.py` → `brokers/smart_router.py` → `brokers/oanda.py`
has no latency SLA enforcement and no partial-fill reconciliation loop.

**Files:** `execution/engine.py`, `execution/tca.py`, `execution/oms.py`,
`brokers/smart_router.py`

**Changes:**

```python
# execution/engine.py — add latency SLA enforcement:
_LATENCY_SLA_MS = float(os.getenv("EXECUTION_LATENCY_SLA_MS", "500"))

async def execute(self, order: Order) -> ExecutionResult:
    t0 = time.monotonic()
    result = await self._route_order(order)
    latency_ms = (time.monotonic() - t0) * 1000
    if latency_ms > _LATENCY_SLA_MS:
        logger.warning("Execution SLA breach: %.1fms > %.1fms", latency_ms, _LATENCY_SLA_MS)
        sentry_sdk.capture_message(f"Execution SLA breach: {latency_ms:.1f}ms",
                                   level="warning")
    self._tca.record(order, result, latency_ms)
    return result
```

**Partial fill reconciliation:**

```python
# execution/oms.py — add reconciliation loop:
async def reconcile_partial_fills(self):
    """Called every 30s. Checks open orders for partial fills and re-routes remainder."""
    for order_id, order in self._open_orders.items():
        fill_status = await self._broker.get_order_status(order_id)
        if fill_status.is_partial:
            remainder = order.quantity - fill_status.filled_quantity
            if remainder > 0:
                await self._route_remainder(order, remainder)
```

---

### P1.5 — Pre-Trade Gate Completeness Audit

**Files:** `risk/pre_trade_gate.py`, `risk/manager.py`, `execution/engine.py`

Current `PreTradeGate` checks: risk_per_trade_cap, loss_streak, CVaR.
Missing checks that must be added before live:

| Check | File | Implementation |
|-------|------|----------------|
| Max open positions | `risk/pre_trade_gate.py` | `if open_positions >= MAX_OPEN_POSITIONS: reject` |
| Correlation limit | `risk/pre_trade_gate.py` | Reject if new position correlation > 0.7 with existing |
| News blackout | `risk/pre_trade_gate.py` | Block 5min before/after high-impact news (from `data/news_calendar_feed.py`) |
| Session filter | `risk/pre_trade_gate.py` | Block outside London/NY session for XAUUSD |
| Spread check | `risk/pre_trade_gate.py` | Reject if spread > 3× median spread (liquidity guard) |
| Margin check | `risk/pre_trade_gate.py` | Verify margin available before order submission |

---

### P1.6 — Kill Switch Hardware Redundancy

**Why:** Current kill switch in `risk/manager.py` is software-only. A process crash
during a runaway position would leave the position open.

**Files:** `risk/manager.py`, `brokers/oanda.py`, `brokers/ibkr_broker.py`

```python
# risk/manager.py — add broker-level kill switch:
async def hardware_kill(self, reason: str) -> None:
    """
    Closes all positions at broker level, bypassing all application logic.
    Called when software kill switch fires AND as a separate broker-direct path.
    """
    logger.critical("HARDWARE KILL SWITCH: %s", reason)
    # 1. Cancel all pending orders
    await self._broker.cancel_all_orders()
    # 2. Close all positions (market order, no slippage limit)
    await self._broker.close_all_positions()
    # 3. Write kill state to Redis (survives restart)
    await self._redis.set("kill_switch:active", "1", ex=86400)
    # 4. Alert all channels
    await self._alert_all(f"HARDWARE KILL: {reason}")
```

**Broker-level close-all must be tested in paper mode before live.**

---

### P1.7 — CI/CD Gate for Live Deployment

**Files:** `.github/workflows/ci.yml`, `.github/workflows/tests.yml`

Add deployment gate job that blocks merge to `main` if:
- Any test fails
- Coverage < 80%
- `python -m research.pipeline.paper_trading_gate --status` returns `phase2_ready=false`
- `python ml/train_advanced.py --check-oos` returns accuracy < 60%

```yaml
# .github/workflows/ci.yml — add gate job:
  deployment-gate:
    runs-on: ubuntu-latest
    needs: [test, lint]
    steps:
      - name: Check paper trading gate
        run: python -m research.pipeline.paper_trading_gate --ci-check
      - name: Check ML OOS accuracy
        run: python ml/train_advanced.py --check-oos --min-accuracy 0.60
      - name: Check kill switch state
        run: python -c "from risk.manager import RiskManager; assert not RiskManager().is_killed()"
```

---

### Phase 1 Completion Checklist

| # | Item | Owner File | Done |
|---|------|-----------|------|
| 1 | Paper clock confirmed ≥ 30 days | `brokers/oanda_paper_clock.py` | ☐ |
| 2 | Paper fills ≥ 250 | `research/pipeline/paper_trading_gate.py` | ☐ |
| 3 | Deep ensemble wired (flag off) | `ml/deep_ensemble_layer.py` | ☐ |
| 4 | Execution latency SLA enforced | `execution/engine.py` | ☐ |
| 5 | Partial fill reconciliation | `execution/oms.py` | ☐ |
| 6 | Pre-trade gate: 6 new checks | `risk/pre_trade_gate.py` | ☐ |
| 7 | Hardware kill switch | `risk/manager.py` | ☐ |
| 8 | CI deployment gate | `.github/workflows/ci.yml` | ☐ |
| 9 | All 2560 tests passing | `pytest` | ☐ |
| 10 | Sentry DSN set in prod `.env` | `.env` | ☐ |

---

## 5. Phase 2 — Institutional Hardening (Months 1–3)

**Gate:** Phase 1 complete + paper fills ≥ 250 + Sharpe SE ≤ 0.10 on paper.
**Capital:** Micro-live ($1k–$10k) with hard daily loss limit = 2% of account.

### P2.1 — Feature Store + Drift Detection

**Why world-top requires this:** Bloomberg Terminal, QuantConnect, and Two Sigma all
run versioned feature stores. Without one, you cannot reproduce a signal from 6 months
ago, detect when the market has drifted away from your training distribution, or safely
roll back a bad model update. This is the single most important infrastructure addition.

**Architecture:**

```
FeatureStore (new: ml/feature_store.py)
├── FeatureRegistry     — versioned feature definitions (name, transform, dtype)
├── FeatureCache        — Redis-backed L1 cache (TTL per timeframe)
├── FeatureAuditLog     — PostgreSQL table: feature_snapshots (bar_time, symbol, features JSON)
├── DriftDetector       — PSI + KS test per feature, daily batch
└── FeatureHealthAPI    — /api/ml/features/drift, /api/ml/features/snapshot
```

**File changes:**

| File | Change | Effort |
|------|--------|--------|
| `ml/feature_store.py` | New — `FeatureStore`, `FeatureRegistry`, `DriftDetector` | 8h |
| `ml/inference_engine.py` | Replace ad-hoc feature building with `FeatureStore.get(symbol, tf)` | 3h |
| `ml/features_extended.py` | Register all 176 features in `FeatureRegistry` on import | 2h |
| `database/models.py` | Add `FeatureSnapshot` SQLAlchemy model | 1h |
| `alembic/versions/` | Migration: `feature_snapshots` table | 30m |
| `api/ml.py` | Add `/api/ml/features/drift` endpoint | 1h |

**Drift detection implementation:**

```python
# ml/feature_store.py
import numpy as np
from scipy import stats

class DriftDetector:
    """
    Population Stability Index (PSI) + KS test for feature drift.
    PSI > 0.2 = significant drift — triggers model retraining alert.
    KS p < 0.05 = distribution shift — logged to Sentry.
    """
    PSI_WARN = 0.1
    PSI_CRITICAL = 0.2

    def compute_psi(self, reference: np.ndarray, current: np.ndarray,
                    n_bins: int = 10) -> float:
        """Population Stability Index."""
        ref_pct, bins = np.histogram(reference, bins=n_bins, density=True)
        cur_pct, _ = np.histogram(current, bins=bins, density=True)
        ref_pct = np.where(ref_pct == 0, 1e-6, ref_pct)
        cur_pct = np.where(cur_pct == 0, 1e-6, cur_pct)
        return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))

    def check_all_features(self, reference_df, current_df) -> dict:
        results = {}
        for col in reference_df.columns:
            psi = self.compute_psi(reference_df[col].dropna(), current_df[col].dropna())
            ks_stat, ks_p = stats.ks_2samp(reference_df[col].dropna(), current_df[col].dropna())
            results[col] = {"psi": psi, "ks_p": ks_p,
                            "status": "critical" if psi > self.PSI_CRITICAL
                                      else "warn" if psi > self.PSI_WARN else "ok"}
        return results
```

**Robustness:** Reference distribution computed from last 252 trading days of training
data. Current distribution from last 21 days of live bars. Daily batch job at 00:00 UTC.
Alert fires to Sentry + Discord if any feature hits PSI > 0.2.

---

### P2.2 — Online Continual Learning Activation

**Why:** The `ml/online_learner.py` SGD adapter + EWC regularizer is complete but
`FEATURE_ONLINE_LEARNING=false`. Phase 3 gate requires 90 days paper + 500 fills.
Phase 2 work: wire the hourly SGD update path and validate it doesn't degrade accuracy.

**Files:** `ml/online_learner.py`, `ml/hourly_trainer.py`, `ml/inference_engine.py`,
`data/scheduler.py`

**Wiring the hourly SGD update:**

```python
# data/scheduler.py — add to hourly job:
async def hourly_online_update():
    """
    Called every hour after market close bar is confirmed.
    Updates SGD adapter on last bar's confirmed outcome.
    """
    from ml.online_learner import OnlineLearner
    learner = OnlineLearner.get_instance()

    # Get last confirmed fill outcome from OMS
    fills = await oms.get_confirmed_fills(since_hours=1)
    for fill in fills:
        X = feature_store.get_snapshot(fill.bar_time, fill.symbol)
        y = 1 if fill.pnl > 0 else 0
        learner.partial_fit(X, y)

    # Daily EWC update (consolidate Fisher information)
    if datetime.utcnow().hour == 22:  # after NY close
        learner.update_ewc()
```

**Safety gates for online learning:**
- SGD learning rate capped at `1e-4` (prevents catastrophic weight updates)
- EWC lambda = 1000 (strong regularization against forgetting)
- Accuracy monitored on rolling 50-bar window; if drops > 5% from baseline, auto-disable
- `FEATURE_ONLINE_LEARNING` can be toggled via `/api/ml/online-learner/toggle` (admin only)
- All weight updates logged to `ml/saved_models/online_learner_audit.jsonl`

---

### P2.3 — Regime-Conditional Model Router

**Why:** A single global model trained on 50 years of mixed regimes underperforms
in specific regimes. `ml/regime_conditional.py` has `RegimeConditionalModel` but it's
not wired into the live inference path.

**Files:** `ml/regime_conditional.py`, `ml/inference_engine.py`, `ml/regime.py`

**Wiring:**

```python
# ml/inference_engine.py — add regime routing:
from ml.regime_conditional import RegimeConditionalModel
from ml.regime import RegimeDetector

class InferenceEngine:
    def __init__(self):
        ...
        self._regime_detector = RegimeDetector()
        self._regime_model = RegimeConditionalModel()
        self._regime_model.load(_SAVED / "regime_conditional.pkl")

    def predict(self, df, symbol="XAU_USD"):
        regime = self._regime_detector.detect(df)  # "trending" | "mean_reverting" | "volatile"
        X = self._build_features(df)

        # Route to regime-specific model if available
        if self._regime_model.has_model(regime):
            prob = self._regime_model.predict_proba(X, regime=regime)
            source = f"regime_{regime}"
        else:
            prob = self._predictor.predict_proba(X)
            source = "global"

        return self._threshold_signal(prob, source=source)
```

**Regime detection:** Rolling 20-bar Hurst exponent (R/S analysis) + normalised ADX.
- Hurst > 0.6 + ADX > 25 → trending
- Hurst < 0.4 + ADX < 20 → mean-reverting
- VIX > 30 or ATR > 2× median → volatile

**Training:** `python ml/train_advanced.py --regime-conditional --years 50 --oos-years 3`
Saves `regime_conditional.pkl` with separate XGBoost models per regime.

---

### P2.4 — Transaction Cost Analysis (TCA) Live Calibration

**Why:** `execution/tca.py` exists but records fills without calibrating the slippage
model. Bloomberg Tradebook and institutional desks run live TCA to continuously update
their market impact models. Without this, position sizing is based on stale assumptions.

**Files:** `execution/tca.py`, `execution/engine.py`, `ml/position_sizer.py`

**TCA calibration loop:**

```python
# execution/tca.py — add live calibration:
class TCAEngine:
    def calibrate_slippage_model(self, lookback_fills: int = 200) -> dict:
        """
        Fits Almgren-Chriss parameters to recent fills.
        Returns updated eta (temporary impact) and gamma (permanent impact).
        """
        fills = self._db.query_recent_fills(n=lookback_fills)
        if len(fills) < 50:
            return self._default_params  # not enough data

        # Regress: slippage = eta * sqrt(participation_rate) + gamma * participation_rate
        participation = fills["quantity"] / fills["adv"]  # ADV = avg daily volume
        slippage = (fills["fill_price"] - fills["signal_price"]) / fills["signal_price"]

        from scipy.optimize import curve_fit
        def ac_model(x, eta, gamma):
            return eta * np.sqrt(x) + gamma * x

        popt, _ = curve_fit(ac_model, participation, slippage, p0=[0.1, 0.05])
        eta, gamma = popt

        # Update position sizer with new parameters
        self._position_sizer.update_impact_params(eta=eta, gamma=gamma)
        logger.info("TCA calibration: eta=%.4f gamma=%.4f (n=%d fills)", eta, gamma, len(fills))
        return {"eta": eta, "gamma": gamma, "n_fills": len(fills)}
```

**Schedule:** Run calibration daily at 22:00 UTC. Expose via `/api/tca/calibration`.
Alert if eta or gamma changes > 50% from prior day (regime shift in liquidity).

---

### P2.5 — Portfolio-Level CVaR

**Why:** Current CVaR in `risk/manager.py` is per-trade. Institutional risk management
requires portfolio-level CVaR that accounts for correlation between open positions.
At Two Sigma / Citadel, portfolio CVaR is the primary risk constraint.

**Files:** `risk/manager.py`, `risk/analytics.py`, `risk/advanced_analytics.py`

**Implementation:**

```python
# risk/advanced_analytics.py — add portfolio CVaR:
class PortfolioCVaR:
    """
    Monte Carlo portfolio CVaR with correlation matrix.
    Runs 10,000 simulations in <100ms using numpy vectorization.
    """
    def __init__(self, confidence: float = 0.95, n_sims: int = 10_000):
        self.confidence = confidence
        self.n_sims = n_sims

    def compute(self, positions: list, returns_history,
                horizon_days: int = 1) -> dict:
        if not positions:
            return {"cvar": 0.0, "var": 0.0, "n_positions": 0}

        symbols = [p.symbol for p in positions]
        weights = np.array([p.notional for p in positions])
        weights /= weights.sum()

        rets = returns_history[symbols].dropna()
        cov = rets.cov().values * 252  # annualized

        # Cholesky decomposition for correlated simulation
        L = np.linalg.cholesky(cov + 1e-8 * np.eye(len(symbols)))
        z = np.random.standard_normal((self.n_sims, len(symbols)))
        sim_returns = (z @ L.T) * np.sqrt(horizon_days / 252)

        portfolio_returns = sim_returns @ weights
        var = np.percentile(portfolio_returns, (1 - self.confidence) * 100)
        cvar = portfolio_returns[portfolio_returns <= var].mean()

        return {
            "cvar": float(cvar),
            "var": float(var),
            "confidence": self.confidence,
            "n_positions": len(positions),
            "n_sims": self.n_sims,
        }
```

**Integration:** Called in `risk/pre_trade_gate.py` before every new order.
If portfolio CVaR would exceed `MAX_PORTFOLIO_CVAR_PCT` (default 3% of equity), reject.

---

### P2.6 — Advanced Slippage Simulator for Backtesting

**Why:** Current `backtest/engine.py` uses fixed slippage. Real XAUUSD slippage is
regime-dependent: 0.5–2 pips in normal conditions, 5–20 pips during news events.
Without realistic slippage, backtest Sharpe is overstated.

**Files:** `backtest/engine.py`, `execution/tca.py`

**Implementation:**

```python
# backtest/engine.py — replace fixed slippage with regime-aware model:
class SlippageSimulator:
    """
    Regime-aware slippage model calibrated to XAUUSD microstructure.
    Based on Almgren-Chriss with news event multiplier.
    """
    BASE_SPREAD_PIPS = 0.5      # normal market
    NEWS_MULTIPLIER = 4.0       # during high-impact news
    VOLATILE_MULTIPLIER = 2.0   # VIX > 25

    def simulate(self, order_size: float, adv: float, vix: float,
                 is_news_window: bool) -> float:
        participation = order_size / adv
        base = self.BASE_SPREAD_PIPS * (1 + 0.5 * np.sqrt(participation))
        if is_news_window:
            base *= self.NEWS_MULTIPLIER
        elif vix > 25:
            base *= self.VOLATILE_MULTIPLIER
        noise = abs(np.random.normal(0, base * 0.3))
        return base + noise
```

---

### P2.7 — Multi-User RBAC (Role-Based Access Control)

**Why:** Commercial deployment requires user isolation. Current auth is single-user JWT.
For SaaS, each user must see only their own trades, positions, and settings.

**Files:** `api/auth.py`, `database/models.py`, `api/trading.py`, `api/watchlist.py`

**RBAC roles:**

| Role | Permissions |
|------|-------------|
| `viewer` | Read-only: signals, performance, charts |
| `trader` | viewer + place/cancel orders (own account only) |
| `analyst` | trader + ML model inspection, feature importance |
| `admin` | analyst + user management, kill switch, system config |
| `superadmin` | admin + billing, white-label config, audit logs |

**Implementation:**

```python
# api/auth.py — add RBAC decorator:
from functools import wraps
from enum import Enum

class Role(str, Enum):
    VIEWER = "viewer"
    TRADER = "trader"
    ANALYST = "analyst"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

ROLE_HIERARCHY = {
    Role.VIEWER: 0, Role.TRADER: 1, Role.ANALYST: 2,
    Role.ADMIN: 3, Role.SUPERADMIN: 4
}

def require_role(min_role: Role):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=Depends(get_current_user), **kwargs):
            if ROLE_HIERARCHY[current_user.role] < ROLE_HIERARCHY[min_role]:
                raise HTTPException(403, f"Requires role: {min_role}")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator
```

---

### P2.8 — Regulatory Audit Trail

**Why:** MiFID II (EU), CFTC (US), and FCA (UK) require immutable audit trails for
all order activity. Without this, the platform cannot be used by regulated entities
or white-labeled to institutional clients.

**Files:** `risk/compliance/` (new subdirectory), `execution/engine.py`,
`database/models.py`

**Audit trail schema:**

```sql
-- alembic migration: audit_trail table
CREATE TABLE audit_trail (
    id          BIGSERIAL PRIMARY KEY,
    event_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type  VARCHAR(50) NOT NULL,
    user_id     UUID REFERENCES users(id),
    symbol      VARCHAR(20),
    order_id    VARCHAR(100),
    quantity    NUMERIC(18,8),
    price       NUMERIC(18,8),
    pnl         NUMERIC(18,8),
    metadata    JSONB,
    checksum    VARCHAR(64) NOT NULL  -- SHA-256 of (event_time||event_type||metadata)
);
CREATE INDEX idx_audit_trail_time ON audit_trail(event_time);
CREATE INDEX idx_audit_trail_user ON audit_trail(user_id);
```

**Checksum chain:** Each row's checksum includes the previous row's checksum
(blockchain-style), making tampering detectable.

---

### Phase 2 Completion Checklist

| # | Item | Owner File | Done |
|---|------|-----------|------|
| 1 | Feature store + drift detection | `ml/feature_store.py` | ☐ |
| 2 | Online learning activated (90d gate) | `ml/online_learner.py` | ☐ |
| 3 | Regime-conditional model router | `ml/inference_engine.py` | ☐ |
| 4 | TCA live calibration | `execution/tca.py` | ☐ |
| 5 | Portfolio-level CVaR | `risk/advanced_analytics.py` | ☐ |
| 6 | Advanced slippage simulator | `backtest/engine.py` | ☐ |
| 7 | Multi-user RBAC | `api/auth.py` | ☐ |
| 8 | Regulatory audit trail | `database/models.py` | ☐ |
| 9 | Deep ensemble enabled (if OOS ≥ XGB) | `ml/deep_ensemble_layer.py` | ☐ |
| 10 | Portfolio CVaR in pre-trade gate | `risk/pre_trade_gate.py` | ☐ |

---

## 6. Phase 3 — World-Top Capability (Months 3–6+)

**Gate:** Phase 2 complete + live Sharpe ≥ 1.2 over 90 days + no kill switch events.
**Capital:** Scaled live ($10k–$100k+) with full institutional risk controls.

### P3.1 — LLM News & Research Layer

**Why:** Trade Ideas Holly AI, Bloomberg Intelligence, and QuantConnect's Alpha Streams
all incorporate NLP on news. Gold is uniquely sensitive to geopolitical events, Fed
statements, and inflation data. A real-time LLM news layer can provide 2–5% edge
improvement on high-impact event days.

**Architecture:**

```
NewsIntelligenceLayer (new: ml/news_intelligence.py)
├── NewsIngestion       — Reuters/Bloomberg/Benzinga webhooks + RSS polling
├── EventClassifier     — LLM (GPT-4o-mini) classifies: bullish/bearish/neutral + confidence
├── SentimentAggregator — Rolling 4h sentiment score with decay weighting
├── EventCalendarFusion — Fuses with data/news_calendar_feed.py economic calendar
└── SignalModifier      — Adjusts XGBoost signal confidence ±0.05 based on sentiment
```

**Files:**

| File | Change | Effort |
|------|--------|--------|
| `ml/news_intelligence.py` | New — full NLP pipeline | 12h |
| `data/news_calendar_feed.py` | Extend with Reuters/Benzinga webhook receiver | 4h |
| `ml/inference_engine.py` | Wire `NewsIntelligenceLayer` as optional signal modifier | 2h |
| `api/signals.py` | Expose `/api/signals/news-sentiment` | 1h |
| `config/feature_flags.py` | Add `FEATURE_NEWS_INTELLIGENCE` flag | 30m |

**Implementation sketch:**

```python
# ml/news_intelligence.py
import openai
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import deque

@dataclass
class NewsSignal:
    timestamp: datetime
    headline: str
    sentiment: float   # -1.0 (bearish) to +1.0 (bullish)
    confidence: float  # 0.0 to 1.0
    impact: str        # "high" | "medium" | "low"
    symbols: list      # affected symbols

class NewsIntelligenceLayer:
    """
    Real-time LLM news sentiment for XAUUSD signal modification.
    Uses GPT-4o-mini for cost efficiency (~$0.002/1000 headlines).
    Falls back to keyword-based sentiment if OpenAI unavailable.
    """
    _SYSTEM_PROMPT = """You are a gold market analyst. Classify this headline's
    impact on XAUUSD price direction.
    Respond with JSON: {"sentiment": float[-1,1], "confidence": float[0,1],
    "impact": "high|medium|low", "reasoning": "one sentence"}"""

    def __init__(self, window_hours: int = 4):
        self._window = deque(maxlen=200)
        self._window_hours = window_hours
        self._client = openai.AsyncOpenAI()

    async def classify_headline(self, headline: str) -> NewsSignal:
        try:
            resp = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": headline}
                ],
                response_format={"type": "json_object"},
                max_tokens=100,
                timeout=3.0,  # hard 3s timeout — never block trading
            )
            data = json.loads(resp.choices[0].message.content)
            return NewsSignal(
                timestamp=datetime.now(timezone.utc),
                headline=headline,
                sentiment=float(data["sentiment"]),
                confidence=float(data["confidence"]),
                impact=data["impact"],
                symbols=["XAU_USD"],
            )
        except Exception:
            return self._keyword_fallback(headline)

    def get_aggregate_sentiment(self) -> float:
        """Exponentially weighted sentiment over last window_hours."""
        now = datetime.now(timezone.utc)
        signals = [s for s in self._window
                   if (now - s.timestamp).total_seconds() < self._window_hours * 3600]
        if not signals:
            return 0.0
        weights = np.array([s.confidence for s in signals])
        sentiments = np.array([s.sentiment for s in signals])
        return float(np.average(sentiments, weights=weights))
```

**Cost control:** GPT-4o-mini at $0.15/1M input tokens. 200 headlines/day × 50 tokens
= 10k tokens/day = $0.0015/day. Negligible. Hard rate limit: 500 API calls/hour.

**Safety:** News layer is additive only — it can reduce signal confidence but never
override a risk block. Max adjustment: ±0.05 on probability score.

---

### P3.2 — Reinforcement Learning Production Integration

**Why:** `ml/rl_agent.py` has a PPO agent with realistic transaction costs but it's
not in the live inference path. RL excels at position sizing and exit timing — areas
where XGBoost is weakest. Jane Street and Renaissance use RL for execution optimization.

**Architecture:**

```
RLExecutionLayer (new: ml/rl_execution_layer.py)
├── PPOAgent (existing: ml/rl_agent.py)
├── StateEncoder        — converts current position + market state to RL observation
├── ActionDecoder       — maps RL action to position size adjustment
└── SafetyWrapper       — clips RL actions to risk-approved range
```

**Files:**

| File | Change | Effort |
|------|--------|--------|
| `ml/rl_execution_layer.py` | New — production wrapper for PPO agent | 8h |
| `ml/rl_agent.py` | Add `load_production()` method + action safety clipping | 3h |
| `execution/engine.py` | Wire RL layer for position sizing (not entry/exit direction) | 2h |
| `ml/train_rl.py` | New — training script with walk-forward validation | 6h |

**Key design decision:** RL controls **position sizing** (0.25x, 0.5x, 0.75x, 1.0x of
risk-approved size), not entry/exit direction. XGBoost decides direction; RL decides
how much. This limits RL's blast radius while capturing its sizing edge.

**Safety wrapper:**

```python
# ml/rl_execution_layer.py
class SafetyWrapper:
    """Clips RL position size actions to risk-approved range."""
    MIN_SCALE = 0.25   # never less than 25% of approved size
    MAX_SCALE = 1.0    # never more than 100% of approved size

    def clip_action(self, rl_action: float, risk_approved_size: float) -> float:
        scale = np.clip(rl_action, self.MIN_SCALE, self.MAX_SCALE)
        return risk_approved_size * scale
```

**Validation:** RL must show Sharpe improvement ≥ 0.1 over XGBoost-only on 6-month
paper period before enabling in live. A/B test: 50% of signals use RL sizing,
50% use fixed sizing. Compare Sharpe after 30 days.

---

### P3.3 — Alternative Data Feeds

**Why:** Institutional alpha increasingly comes from alternative data. COT reports,
gold ETF flows, and central bank reserve data are the most directly relevant for XAUUSD.

**Data sources and integration:**

| Source | Data | Frequency | File | Effort |
|--------|------|-----------|------|--------|
| CFTC COT | Real futures positioning (not proxy) | Weekly | `data/feeds/cot_feed.py` | 4h |
| World Gold Council | ETF flows, central bank demand | Monthly | `data/feeds/wgc_feed.py` | 3h |
| Fed H.4.1 | Reserve balances, repo rates | Weekly | `data/feeds/fed_feed.py` | 2h |
| Google Trends | "gold price" search volume | Daily | `data/feeds/trends_feed.py` | 2h |
| Options flow | GLD/GC options put/call ratio | Daily | `data/feeds/options_flow.py` | 4h |
| Shipping indices | Baltic Dry (risk-off proxy) | Daily | `data/feeds/macro_extended.py` | 2h |

**COT real data integration:**

```python
# data/feeds/cot_feed.py
import requests
import pandas as pd

class COTFeed:
    """
    CFTC Commitments of Traders — Gold Futures (COMEX).
    Published every Friday at 15:30 ET for the prior Tuesday.
    URL: https://www.cftc.gov/dea/futures/deacmesf.htm
    """
    GOLD_CODE = "088691"  # COMEX Gold futures CFTC code

    def fetch_latest(self) -> dict:
        url = "https://www.cftc.gov/files/dea/history/fut_fin_xls_2024.zip"
        # Parse Excel, filter GOLD_CODE, extract:
        # - managed_money_long, managed_money_short (hedge fund positioning)
        # - commercial_long, commercial_short (producer hedging)
        # - net_speculative = managed_money_long - managed_money_short
        # - cot_index = percentile of net_speculative over 3 years
        ...

    def as_features(self) -> dict:
        data = self.fetch_latest()
        return {
            "cot_net_speculative": data["net_speculative"],
            "cot_index_3y": data["cot_index"],          # 0-100 percentile
            "cot_commercial_net": data["commercial_net"],
            "cot_change_wow": data["net_speculative"] - data["prev_net_speculative"],
        }
```

**Replace COT proxy features** in `ml/advanced_features.py` with real COT data
when available. Keep proxy as fallback when CFTC data is delayed.

---

### P3.4 — High-Frequency Tick + Order Book Feed

**Why:** H1 bars miss intraday microstructure. Institutional systems at Citadel and
Two Sigma use tick data and Level 2 order book to detect institutional order flow,
spoofing, and liquidity imbalances. Even at H1 trading frequency, tick-level features
improve signal quality.

**Architecture:**

```
TickDataPipeline (new: data/tick_pipeline.py)
├── OANDAStreamConsumer  — existing brokers/oanda_stream.py + oanda_ws.py
├── TickAggregator       — VWAP, tick imbalance, trade flow per bar
├── OrderBookAnalyzer    — bid/ask depth, imbalance ratio, large order detection
├── MicrostructureFeatures — 12 new features for ml/features_extended.py
└── TickStore            — TimescaleDB or Redis time-series for tick storage
```

**12 new microstructure features:**

```python
# ml/features_extended.py — add to Layer 17:
def add_microstructure_features(df: pd.DataFrame, tick_df: pd.DataFrame) -> pd.DataFrame:
    """
    Requires tick_df with columns: timestamp, bid, ask, last, volume, side
    """
    # 1. Tick imbalance (buy volume - sell volume) / total volume
    df["tick_imbalance"] = (tick_df["buy_vol"] - tick_df["sell_vol"]) / tick_df["total_vol"]

    # 2. VWAP deviation (price vs volume-weighted average)
    df["vwap_deviation"] = (df["close"] - tick_df["vwap"]) / tick_df["vwap"]

    # 3. Bid-ask spread normalized by ATR
    df["spread_atr_ratio"] = tick_df["avg_spread"] / df["atr_14"]

    # 4. Large trade ratio (trades > 10× median size)
    df["large_trade_ratio"] = tick_df["large_trade_count"] / tick_df["total_trades"]

    # 5. Order book imbalance (top 5 levels)
    df["ob_imbalance"] = (tick_df["bid_depth_5"] - tick_df["ask_depth_5"]) / \
                          (tick_df["bid_depth_5"] + tick_df["ask_depth_5"])

    # 6-12: Kyle's lambda, Amihud illiquidity, Roll spread, etc.
    ...
    return df
```

---

### P3.5 — Market Replay Dashboard + Backtesting Replay Engine

**Why:** QuantConnect's LEAN engine and Bloomberg's backtesting suite allow traders
to replay historical market conditions bar-by-bar with full signal visualization.
This is essential for debugging signal failures and demonstrating edge to investors.

**Files:**

| File | Change | Effort |
|------|--------|--------|
| `dashboard/src/components/MarketReplay.tsx` | New — bar-by-bar replay with signal overlay | 16h |
| `api/backtesting.py` | Add `/api/backtest/replay/{session_id}` streaming endpoint | 4h |
| `backtest/engine.py` | Add `ReplayMode` that emits events via WebSocket | 4h |
| `dashboard/src/components/SignalTimeline.tsx` | New — signal + trade timeline chart | 8h |

**Replay API:**

```python
# api/backtesting.py — add replay endpoint:
@router.get("/api/backtest/replay/{session_id}")
async def stream_replay(session_id: str, speed: float = 1.0):
    """
    Streams backtest bars as Server-Sent Events.
    Client receives: {bar, signal, position, pnl, features} per bar.
    speed=1.0 = real-time, speed=10.0 = 10× faster.
    """
    async def event_generator():
        session = await BacktestSession.load(session_id)
        for bar in session.bars:
            yield f"data: {bar.to_json()}\n\n"
            await asyncio.sleep(bar.duration_seconds / speed)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### P3.6 — Chaos Engineering Suite

**Why:** Production systems fail in unexpected ways. Netflix's Chaos Monkey and
Google's DiRT (Disaster Recovery Testing) are industry standards. Without chaos
testing, you don't know if your kill switch, circuit breakers, and failover paths
actually work under load.

**Files:** `tests/test_chaos/test_failure_modes.py` (exists — extend it),
`tests/chaos/` (new directory)

**Chaos scenarios to implement:**

```python
# tests/chaos/test_broker_failure.py
class TestBrokerChaos:
    """Simulates broker failures and verifies system response."""

    async def test_oanda_timeout_triggers_circuit_breaker(self):
        """OANDA API times out — circuit breaker must open within 3 errors."""
        with mock_oanda_timeout(delay=30):
            for _ in range(3):
                await engine.execute(test_order)
        assert circuit_breaker.is_open()
        assert kill_switch.is_active()  # belt-and-suspenders

    async def test_redis_failure_falls_back_to_memory(self):
        """Redis goes down — system must continue with in-memory state."""
        with mock_redis_down():
            signal = engine.predict(test_bars)
        assert signal is not None  # must not crash

    async def test_database_failure_blocks_new_orders(self):
        """PostgreSQL goes down — no new orders, existing positions safe."""
        with mock_db_down():
            result = await engine.execute(test_order)
        assert result.status == ExecutionStatus.BLOCKED

    async def test_kill_switch_survives_process_restart(self):
        """Kill switch state must persist across process restart."""
        await risk_manager.activate_kill_switch("test")
        # Simulate restart
        new_manager = RiskManager()
        assert new_manager.is_killed()

    async def test_concurrent_orders_no_race_condition(self):
        """100 concurrent orders must not exceed position limits."""
        tasks = [engine.execute(test_order) for _ in range(100)]
        results = await asyncio.gather(*tasks)
        filled = [r for r in results if r.status == ExecutionStatus.FILLED]
        assert len(filled) <= MAX_OPEN_POSITIONS
```

**CI integration:** Chaos tests run in a separate `chaos` stage in CI, after unit
and integration tests. They use Docker Compose with `toxiproxy` for network fault injection.

---

### P3.7 — Kubernetes Production Deployment (Helm)

**Why:** Docker Compose is not production-grade for a trading system. Kubernetes
provides auto-scaling, self-healing, rolling deployments, and resource isolation.
The existing `Dockerfile` is the foundation.

**Files to create:**

```
helm/
├── Chart.yaml
├── values.yaml
├── values.production.yaml
├── templates/
│   ├── deployment-api.yaml       — FastAPI app (2 replicas, HPA)
│   ├── deployment-worker.yaml    — Background workers (scheduler, online learner)
│   ├── deployment-redis.yaml     — Redis with persistence
│   ├── service-api.yaml          — ClusterIP + LoadBalancer
│   ├── ingress.yaml              — nginx ingress with TLS
│   ├── hpa-api.yaml              — HorizontalPodAutoscaler (2-10 replicas)
│   ├── pdb-api.yaml              — PodDisruptionBudget (min 1 available)
│   ├── configmap.yaml            — Non-secret config
│   ├── secret.yaml               — Sealed secrets (Bitnami sealed-secrets)
│   └── cronjob-retrain.yaml      — Daily model retraining job
```

**Key Kubernetes design decisions:**

```yaml
# helm/templates/deployment-api.yaml
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0      # zero-downtime deployments
      maxSurge: 1
  template:
    spec:
      containers:
      - name: hopefx-api
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

**Kill switch in Kubernetes:** The kill switch state in Redis must be checked by
the readiness probe. If kill switch is active, pod reports not-ready → load balancer
stops sending traffic → no new orders accepted.

---

### P3.8 — Grafana Dashboard Suite

**Why:** Prometheus metrics exist but there are no Grafana dashboards. Without
dashboards, you cannot monitor the system in production. Bloomberg Terminal users
expect real-time P&L, risk, and signal dashboards.

**Dashboards to create:**

| Dashboard | Panels | File |
|-----------|--------|------|
| Trading Overview | P&L curve, open positions, daily Sharpe, win rate | `grafana/dashboards/trading_overview.json` |
| ML Health | Signal confidence distribution, non-neutral rate, drift PSI, model accuracy | `grafana/dashboards/ml_health.json` |
| Risk Monitor | CVaR, drawdown, kill switch status, position limits | `grafana/dashboards/risk_monitor.json` |
| Execution Quality | Latency histogram, slippage, fill rate, TCA metrics | `grafana/dashboards/execution_quality.json` |
| Infrastructure | CPU/memory, Redis latency, DB connections, error rate | `grafana/dashboards/infrastructure.json` |

**Prometheus metrics to add:**

```python
# utils/telemetry.py — add trading-specific metrics:
from prometheus_client import Histogram, Gauge, Counter

SIGNAL_CONFIDENCE = Histogram("hopefx_signal_confidence",
    "Signal confidence distribution", buckets=[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0])
OPEN_POSITIONS = Gauge("hopefx_open_positions", "Number of open positions", ["symbol"])
DAILY_PNL = Gauge("hopefx_daily_pnl_usd", "Daily P&L in USD")
EXECUTION_LATENCY = Histogram("hopefx_execution_latency_ms",
    "Order execution latency", buckets=[10, 50, 100, 200, 500, 1000, 2000])
KILL_SWITCH_ACTIVE = Gauge("hopefx_kill_switch_active", "Kill switch state (0/1)")
FEATURE_DRIFT_PSI = Gauge("hopefx_feature_drift_psi", "Feature PSI score", ["feature"])
```

---

### Phase 3 Completion Checklist

| # | Item | Owner File | Done |
|---|------|-----------|------|
| 1 | LLM news intelligence layer | `ml/news_intelligence.py` | ☐ |
| 2 | RL production integration (sizing) | `ml/rl_execution_layer.py` | ☐ |
| 3 | Real COT data feed | `data/feeds/cot_feed.py` | ☐ |
| 4 | Tick + order book pipeline | `data/tick_pipeline.py` | ☐ |
| 5 | Market replay dashboard | `dashboard/src/components/MarketReplay.tsx` | ☐ |
| 6 | Chaos engineering suite | `tests/chaos/` | ☐ |
| 7 | Kubernetes Helm chart | `helm/` | ☐ |
| 8 | Grafana dashboard suite | `grafana/dashboards/` | ☐ |
| 9 | Microstructure features (Layer 17) | `ml/features_extended.py` | ☐ |
| 10 | RL A/B test: Sharpe ≥ +0.1 | `ml/rl_execution_layer.py` | ☐ |

---
