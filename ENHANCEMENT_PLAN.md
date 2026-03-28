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

## 7. ML & Signals — Full Enhancement Catalogue

This section covers every ML and signal enhancement required for world-top status,
beyond what is covered in the phased roadmap above.

### 7.1 — Hybrid Ensemble Architecture (XGBoost + LSTM/Transformer)

**Why required:** XGBoost captures non-linear feature interactions but has no memory
of sequence patterns. LSTM/Transformer captures temporal dependencies but overfits
on small datasets. The hybrid captures both. QuantConnect's Alpha Streams and
Two Sigma's production systems use stacked ensembles as standard.

**Current state:** `research/pipeline/models_deep.py` has `HybridModel` (TCN+LSTM)
and `TransformerPredictor`. `ml/models/ensemble.py` has stacking logic.
Neither is wired to `ml/inference_engine.py`.

**Target architecture:**

```
Level 0 (base learners):
├── XGBoost (advanced_oos.pkl)          — 176 tabular features
├── HybridModel (TCN+LSTM)              — 60-bar sequence, 176 features
├── TransformerPredictor                — 60-bar sequence, 176 features
└── RegimeConditionalModel              — regime-routed XGBoost

Level 1 (meta-learner):
└── LogisticRegression (isotonic cal.)  — stacks Level 0 probabilities
    Input: [xgb_prob, hybrid_prob, transformer_prob, regime_prob]
    Output: final_probability [0,1]
```

**File changes:**

| File | Change | Effort |
|------|--------|--------|
| `ml/ensemble_stacker.py` | New — Level 1 meta-learner with isotonic calibration | 4h |
| `ml/train_deep_ensemble.py` | New — trains all Level 0 models + meta-learner | 8h |
| `ml/inference_engine.py` | Replace single-model predict with ensemble stack | 3h |
| `ml/models/ensemble.py` | Extend with `StackedEnsemble` class | 2h |

**Validation requirement:** Ensemble OOS accuracy must exceed best single model by
≥ 1% before enabling. Track per-model contribution via SHAP on meta-learner.

---

### 7.2 — Multi-Model Router (Signal Confidence Routing)

**Why required:** Different models excel in different regimes. A router that selects
the best model per regime + confidence level outperforms any single model.

**Implementation:**

```python
# ml/model_router.py (new)
class ModelRouter:
    """
    Routes inference to the highest-confidence model for current regime.
    Falls back to global XGBoost if regime-specific model unavailable.
    """
    def route(self, regime: str, features: np.ndarray,
              available_models: dict) -> tuple[str, float]:
        """Returns (model_name, probability)."""
        candidates = []
        for name, model in available_models.items():
            if model.is_available_for_regime(regime):
                prob = model.predict_proba(features)
                conf = abs(prob - 0.5) * 2  # distance from 0.5 = confidence
                candidates.append((name, prob, conf))

        if not candidates:
            return "fallback", 0.5

        # Select highest confidence model
        best = max(candidates, key=lambda x: x[2])
        return best[0], best[1]
```

---

### 7.3 — SHAP Explainability in Production

**Why required:** Regulatory requirements (MiFID II Article 25, EU AI Act) require
explainability for automated trading decisions. SHAP is the industry standard.
Current `api/explain.py` has SHAP but it's not called on every live signal.

**Files:** `api/explain.py`, `ml/inference_engine.py`, `database/models.py`

**Changes:**

```python
# ml/inference_engine.py — add SHAP to every prediction:
def predict(self, df, symbol="XAU_USD") -> dict:
    ...
    signal = self._threshold_signal(prob)

    # SHAP explanation (async, non-blocking)
    if _SHAP_ENABLED:
        shap_values = self._explainer.shap_values(X)
        top_features = self._get_top_shap_features(shap_values, X, n=5)
        signal["explanation"] = {
            "top_features": top_features,
            "shap_sum": float(shap_values.sum()),
            "model": "advanced_oos",
        }

    return signal
```

**Store SHAP values per signal in PostgreSQL** for audit trail and post-trade analysis.
Expose via `/api/signals/{signal_id}/explanation`.

---

### 7.4 — Multi-Asset Expansion

**Why required:** XAUUSD-only is a single-asset strategy. Institutional systems trade
correlated assets to hedge and diversify. Gold correlates with: silver (0.85), oil (0.4),
EUR/USD (-0.6 during risk-off), Bitcoin (0.3 in 2024).

**Current state:** Multi-symbol backtest exists (`backtest/multi_symbol_backtest.py`)
with 7 symbols. Live trading is XAUUSD-only.

**Expansion plan:**

| Symbol | Correlation to XAU | Phase | Rationale |
|--------|-------------------|-------|-----------|
| XAG_USD (Silver) | +0.85 | Phase 2 | Highest correlation, same drivers |
| BCO_USD (Brent) | +0.40 | Phase 2 | Inflation/geopolitical hedge |
| EUR_USD | -0.60 | Phase 2 | DXY inverse proxy |
| GBP_USD | -0.55 | Phase 3 | Diversification |
| BTC_USD | +0.30 | Phase 3 | Digital gold narrative |
| SPX500 | -0.40 | Phase 3 | Risk-off hedge |

**Portfolio constraint:** Total portfolio CVaR ≤ 3% equity regardless of number of
symbols. Position sizing scales inversely with correlation to existing positions.

---

### 7.5 — Feature Engineering: Layer 17 (Microstructure) + Layer 18 (Alternative Data)

**Current:** 176 features across Layers 1–16 (technical, macro, COT proxy, regime,
institutional signals). Target: 200+ features with Layers 17–18.

**Layer 17 — Microstructure (12 features):**

```python
# ml/features_extended.py — add Layer 17:
LAYER_17_FEATURES = [
    "tick_imbalance",          # buy/sell volume imbalance
    "vwap_deviation",          # price vs VWAP
    "spread_atr_ratio",        # bid-ask spread normalized
    "large_trade_ratio",       # institutional order detection
    "ob_imbalance",            # order book depth imbalance
    "kyle_lambda",             # price impact per unit volume
    "amihud_illiquidity",      # Amihud (2002) illiquidity ratio
    "roll_spread",             # Roll (1984) effective spread estimate
    "realized_variance_ratio", # short-term vs long-term variance
    "trade_arrival_rate",      # trades per minute (activity proxy)
    "price_impact_ratio",      # permanent vs temporary impact
    "depth_weighted_midprice", # order-book weighted mid
]
```

**Layer 18 — Alternative Data (8 features):**

```python
LAYER_18_FEATURES = [
    "cot_net_speculative",     # real CFTC COT net positioning
    "cot_index_3y",            # COT percentile rank (3-year)
    "etf_flow_5d",             # GLD/IAU ETF flow (5-day sum)
    "cb_reserve_change",       # central bank gold reserve change (monthly)
    "google_trends_gold",      # search volume index
    "options_pcr_gld",         # GLD put/call ratio
    "baltic_dry_index",        # shipping index (risk-off proxy)
    "news_sentiment_4h",       # LLM news sentiment (4h rolling)
]
```

**Stationarity requirement:** All new features must pass ADF test (p < 0.05) before
inclusion. Add to `ml/train_advanced.py --check-stationarity` validation step.

---

### 7.6 — Walk-Forward Optimization (WFO) Framework

**Why required:** Static train/test splits overfit to the test period. Walk-forward
optimization (used by QuantConnect, Amibroker, and all institutional backtesting
platforms) continuously re-optimizes hyperparameters on expanding windows.

**Files:** `ml/train_advanced.py`, `backtest/engine.py`

**Implementation:**

```python
# ml/wfo.py (new)
class WalkForwardOptimizer:
    """
    Anchored walk-forward optimization.
    Train window: expanding (always includes all history).
    Test window: fixed 3-month OOS period.
    Re-optimize: every 3 months.
    """
    def run(self, df: pd.DataFrame, param_grid: dict,
            train_start: str, test_months: int = 3,
            n_folds: int = 8) -> pd.DataFrame:
        results = []
        for fold in range(n_folds):
            test_end = pd.Timestamp(train_start) + pd.DateOffset(months=(fold+1)*test_months)
            test_start = test_end - pd.DateOffset(months=test_months)
            train_df = df[df.index < test_start]
            test_df = df[(df.index >= test_start) & (df.index < test_end)]

            # Grid search on train, evaluate on test
            best_params = self._grid_search(train_df, param_grid)
            oos_metrics = self._evaluate(test_df, best_params)
            results.append({"fold": fold, "test_start": test_start,
                            "test_end": test_end, **oos_metrics, **best_params})

        return pd.DataFrame(results)
```

---

### 7.7 — Model Versioning + Rollback

**Why required:** Without model versioning, a bad retrain cannot be rolled back.
MLflow is the industry standard for experiment tracking and model registry.

**Files:** `ml/training.py`, `ml/train_advanced.py`, `ml/inference_engine.py`

**MLflow integration:**

```python
# ml/training.py — add MLflow tracking:
import mlflow
import mlflow.xgboost

def train_ml_pipeline(...):
    with mlflow.start_run(run_name=f"xgboost_{datetime.now().strftime('%Y%m%d_%H%M')}"):
        mlflow.log_params({"n_estimators": 500, "max_depth": 6, ...})
        model = xgb.XGBClassifier(...)
        model.fit(X_train, y_train)
        mlflow.log_metrics({"oos_accuracy": oos_acc, "oos_f1": oos_f1, "sharpe": sharpe})
        mlflow.xgboost.log_model(model, "model",
                                  registered_model_name="hopefx_xgboost")
```

**Rollback procedure:**

```bash
# Roll back to previous model version:
mlflow models download --model-uri "models:/hopefx_xgboost/2" --dst-path ml/saved_models/
# Or via API:
curl -X POST /api/ml/rollback -d '{"model": "xgboost", "version": 2}'
```

---

### 7.8 — Continual Retraining Pipeline

**Why required:** Models decay as market regimes shift. The `ml/hourly_trainer.py`
exists but the daily full retrain is not automated.

**Files:** `ml/run_training.py`, `data/scheduler.py`, `.github/workflows/`

**Retraining schedule:**

| Trigger | Action | File |
|---------|--------|------|
| Daily 22:00 UTC | Incremental SGD update | `ml/online_learner.py` |
| Weekly Sunday | Full XGBoost retrain (last 3 years) | `ml/train_advanced.py` |
| Monthly | Full 50-year retrain + OOS validation | `ml/train_advanced.py` |
| PSI > 0.2 on any feature | Emergency retrain alert | `ml/feature_store.py` |
| OOS accuracy drops > 3% | Auto-retrain + Sentry alert | `ml/inference_engine.py` |

**Kubernetes CronJob for weekly retrain:**

```yaml
# helm/templates/cronjob-retrain.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hopefx-weekly-retrain
spec:
  schedule: "0 22 * * 0"  # Sunday 22:00 UTC
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: retrain
            image: hopefx:latest
            command: ["python", "ml/train_advanced.py",
                      "--years", "3", "--oos-years", "1",
                      "--register-mlflow", "--alert-on-degradation"]
```

---

## 8. Risk & Compliance — Full Enhancement Catalogue

### 8.1 — Greeks-Aware Position Sizing for Options Overlay

**Why required:** If HOPEFX ever trades GLD options or GC futures options as a hedge,
position sizing must account for delta, gamma, and vega. Even without options, the
framework is needed for institutional white-label clients.

**Files:** `analytics/options.py` (exists), `risk/position_sizing.py`, `ml/position_sizer.py`

```python
# risk/position_sizing.py — add Greeks-aware sizing:
class GreeksAwarePositionSizer:
    def size_with_greeks(self, signal_direction: str, confidence: float,
                          portfolio_delta: float, max_delta: float = 0.5) -> float:
        base_size = self._kelly_size(confidence)
        if signal_direction == "long" and portfolio_delta > 0:
            delta_penalty = min(1.0, portfolio_delta / max_delta)
            base_size *= (1 - delta_penalty * 0.5)
        elif signal_direction == "short" and portfolio_delta < 0:
            delta_penalty = min(1.0, abs(portfolio_delta) / max_delta)
            base_size *= (1 - delta_penalty * 0.5)
        return max(0.0, base_size)
```

---

### 8.2 — Stress Testing: XAUUSD Historical Scenarios

**Why required:** `risk/stress_test.py` exists but runs generic scenarios. Institutional
risk desks run XAUUSD-specific stress tests calibrated to real historical events.

**Files:** `risk/stress_test.py`, `risk/manager.py`

```python
# risk/stress_test.py — add historical scenario library:
XAUUSD_STRESS_SCENARIOS = {
    "2008_financial_crisis": {"price_shock": -0.30, "vol_multiplier": 3.5, "duration_days": 90},
    "2020_covid_crash":      {"price_shock": -0.12, "vol_multiplier": 4.0, "duration_days": 14},
    "2022_rate_shock":       {"price_shock": -0.20, "vol_multiplier": 2.0, "duration_days": 365},
    "1980_bubble_burst":     {"price_shock": -0.65, "vol_multiplier": 5.0, "duration_days": 730},
    "geopolitical_spike":    {"price_shock": +0.15, "vol_multiplier": 3.0, "duration_days": 5},
}
```

**Integration:** Run stress tests daily at startup. If any scenario shows > 20%
drawdown on current positions, reduce position sizes by 50% and alert.

---

### 8.3 — Drawdown-Based Position Scaling

**Why required:** Current kill switch is binary. Institutional systems use graduated
position scaling — as drawdown increases, sizes decrease proportionally.

**Files:** `risk/manager.py`, `risk/drawdown_tracker.py`, `ml/position_sizer.py`

```python
# risk/manager.py — graduated scaling table:
DRAWDOWN_SCALE_TABLE = [
    (0.00, 0.02, 1.00),   # 0-2% DD: full size
    (0.02, 0.04, 0.75),   # 2-4% DD: 75% size
    (0.04, 0.06, 0.50),   # 4-6% DD: 50% size
    (0.06, 0.08, 0.25),   # 6-8% DD: 25% size
    (0.08, 1.00, 0.00),   # >8% DD: kill switch
]

def get_position_scale(self, current_drawdown: float) -> float:
    for dd_min, dd_max, scale in DRAWDOWN_SCALE_TABLE:
        if dd_min <= current_drawdown < dd_max:
            return scale
    return 0.0
```

---

### 8.4 — MiFID II Best Execution Reporting

**Why required:** Any EU-regulated entity using HOPEFX must demonstrate best execution
under MiFID II RTS 27/28. Required for institutional white-label clients.

**Files:** `risk/compliance/mifid_reporter.py` (new), `execution/tca.py`, `api/admin.py`

```python
# risk/compliance/mifid_reporter.py (new)
class MiFIDReporter:
    def generate_rts27_report(self, period: str) -> dict:
        fills = self._db.query_fills(period=period)
        return {
            "period": period,
            "venue": "OANDA",
            "instrument_class": "FX_SPOT",
            "total_orders": len(fills),
            "avg_execution_speed_ms": fills["latency_ms"].mean(),
            "avg_slippage_bps": fills["slippage_bps"].mean(),
            "fill_rate": fills["filled"].mean(),
            "price_improvement_pct": (fills["fill_price"] < fills["signal_price"]).mean(),
        }
```

---

### 8.5 — Prop Firm Rule Engine (YAML-Driven)

**Why required:** `brokers/prop_firms/` exists. Rules must be configurable without
code changes — prop firms update rules frequently.

**Files:** `brokers/prop_firms/`, `config/prop_firm_rules.yaml` (new)

```yaml
# config/prop_firm_rules.yaml
ftmo:
  max_daily_loss_pct: 0.05
  max_total_loss_pct: 0.10
  profit_target_pct: 0.10
  max_position_size_lots: 10
  news_trading_allowed: false
  weekend_holding_allowed: false
  instruments_allowed: ["XAUUSD", "EURUSD", "GBPUSD"]

topstep:
  max_daily_loss_pct: 0.03
  max_total_loss_pct: 0.06
  trailing_drawdown: true
  max_contracts: 5
```

---

## 9. Execution & OMS — Full Enhancement Catalogue

### 9.1 — Smart Router: Latency-Aware Venue Selection

**Why required:** Current `brokers/smart_router.py` routes on availability, not latency.
Institutional routers select venues on real-time latency, fill rates, and spread.

**Files:** `brokers/smart_router.py`, `execution/engine.py`

```python
# brokers/smart_router.py — latency-aware scoring:
class SmartRouter:
    async def select_venue(self, order) -> str:
        scores = {}
        for venue, stats in self._venue_stats.items():
            if not self._is_available(venue):
                continue
            latency_score = 1.0 / (1 + stats["avg_latency_ms"] / 100)
            fill_score = stats["fill_rate"]
            spread_score = 1.0 / (1 + stats["avg_spread_pips"])
            scores[venue] = (0.4 * latency_score + 0.4 * fill_score + 0.2 * spread_score)
        return max(scores, key=scores.get) if scores else "paper"

    async def update_venue_stats(self, venue: str, latency_ms: float,
                                  filled: bool, spread_pips: float):
        alpha = 0.1  # EWMA decay
        s = self._venue_stats.setdefault(venue, {
            "avg_latency_ms": latency_ms, "fill_rate": 1.0, "avg_spread_pips": spread_pips
        })
        s["avg_latency_ms"] = alpha * latency_ms + (1-alpha) * s["avg_latency_ms"]
        s["fill_rate"] = alpha * (1.0 if filled else 0.0) + (1-alpha) * s["fill_rate"]
        s["avg_spread_pips"] = alpha * spread_pips + (1-alpha) * s["avg_spread_pips"]
```

---

### 9.2 — Bracket Orders (Entry + SL + TP Atomic)

**Why required:** `execution/oms.py` lacks bracket orders. Every institutional OMS
supports atomic bracket submission — entry fills trigger automatic SL + TP as OCO.

**Files:** `execution/oms.py`, `execution/engine.py`

```python
# execution/oms.py — bracket order support:
@dataclass
class BracketOrder:
    entry: Order
    stop_loss: Order
    take_profit: Order
    oco_group_id: str = field(default_factory=lambda: str(uuid.uuid4()))

class OMS:
    async def submit_bracket(self, bracket: BracketOrder) -> BracketResult:
        entry_result = await self._submit(bracket.entry)
        if entry_result.status == ExecutionStatus.FILLED:
            await self._submit_oco(bracket.stop_loss, bracket.take_profit,
                                    group_id=bracket.oco_group_id)
        return BracketResult(entry=entry_result, bracket=bracket)
```

---

### 9.3 — DMA-Style Limit Order Placement

**Why required:** Market orders have guaranteed slippage. Limit orders placed at
optimal price levels reduce market impact by 30–60% in normal conditions.

**Files:** `execution/engine.py`, `brokers/oanda.py`

```python
# execution/engine.py — DMA-style limit placement:
class DMAExecutor:
    def calculate_limit_price(self, direction: str, mid_price: float,
                               spread: float, urgency: float) -> float:
        """urgency=0.0: passive, urgency=1.0: aggressive (cross spread)."""
        half_spread = spread / 2
        if direction == "long":
            return mid_price - half_spread * (1 - urgency)
        return mid_price + half_spread * (1 - urgency)

    async def execute_with_timeout(self, order, limit_price: float,
                                    timeout_seconds: int = 30):
        result = await self._submit_limit(order, limit_price)
        if not result.is_filled:
            await asyncio.sleep(timeout_seconds)
            if not result.is_filled:
                result = await self._submit_market(order)
        return result
```

---

### 9.4 — FIX Heartbeat Monitor + Auto-Reconnect

**Why required:** `execution/fix_adapter.py` is complete but lacks heartbeat monitoring.
A dead FIX session with open positions is a critical failure mode.

**Files:** `execution/fix_adapter.py`

```python
# execution/fix_adapter.py — heartbeat monitor:
class FIXAdapter:
    HEARTBEAT_INTERVAL = 30
    MAX_MISSED_HEARTBEATS = 3

    async def _heartbeat_monitor(self):
        missed = 0
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            if not await self._check_heartbeat():
                missed += 1
                if missed >= self.MAX_MISSED_HEARTBEATS:
                    logger.error("FIX session dead — reconnecting")
                    await self._reconnect()
                    missed = 0
            else:
                missed = 0
```

---

## 10. Data & Infrastructure — Full Enhancement Catalogue

### 10.1 — TimescaleDB for Time-Series Storage

**Why required:** PostgreSQL is not optimized for time-series. TimescaleDB provides
10–100× faster queries with automatic partitioning. Essential for tick data.

**Files:** `utils/database.py`, `docker-compose.yml`, `alembic/versions/`

```yaml
# docker-compose.yml — replace postgres with timescaledb:
  db:
    image: timescale/timescaledb:latest-pg15
```

```python
# alembic migration — convert to hypertables:
def upgrade():
    op.execute("SELECT create_hypertable('tick_data', 'timestamp')")
    op.execute("SELECT create_hypertable('feature_snapshots', 'bar_time')")
    op.execute("SELECT add_compression_policy('tick_data', INTERVAL '7 days')")
```

---

### 10.2 — Redis Streams Event Bus

**Why required:** `core/event_bus.py` uses in-memory pub/sub. Redis Streams provide
persistent, ordered, consumer-group delivery — essential for reliable signal → execution
→ risk → audit event chains that survive process restarts.

**Files:** `core/event_bus.py`

```python
# core/event_bus.py — Redis Streams:
class EventBus:
    STREAMS = {
        "signals": "hopefx:signals",
        "orders": "hopefx:orders",
        "fills": "hopefx:fills",
        "risk": "hopefx:risk",
        "audit": "hopefx:audit",
    }

    async def publish(self, stream: str, event: dict) -> str:
        return await self._redis.xadd(
            self.STREAMS[stream],
            {k: json.dumps(v) if not isinstance(v, str) else v for k, v in event.items()},
            maxlen=10_000,
        )
```

---

### 10.3 — OpenTelemetry Distributed Tracing

**Why required:** End-to-end tracing from signal generation to order fill is essential
for debugging latency and proving execution quality to regulators.

**Files:** `utils/telemetry.py`, `tracing/setup.py` (exists), `execution/engine.py`

```python
# utils/telemetry.py — OpenTelemetry setup:
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

def setup_tracing(service_name: str = "hopefx-api"):
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    )))
    trace.set_tracer_provider(provider)

# execution/engine.py — instrument execute():
tracer = trace.get_tracer("hopefx.execution")

async def execute(self, order):
    with tracer.start_as_current_span("execute_order") as span:
        span.set_attribute("order.symbol", order.symbol)
        span.set_attribute("order.direction", order.direction)
        result = await self._route_order(order)
        span.set_attribute("execution.latency_ms", result.latency_ms)
        return result
```

---

### 10.4 — Data Pipeline Reliability (Retry + Circuit Breaker)

**Why required:** `data/market_ingest.py` has no retry logic. A transient OANDA
outage during market hours would cause missed signals and stale features.

**Files:** `data/market_ingest.py`, `data/real_time_price_engine.py`

```python
# data/market_ingest.py — retry + fallback:
from tenacity import retry, stop_after_attempt, wait_exponential

class MarketDataIngestor:
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=60))
    async def fetch_bars(self, symbol: str, timeframe: str, count: int):
        ...

    async def fetch_with_fallback(self, symbol: str, timeframe: str):
        for source in [self._oanda_stream, self._oanda_rest, self._yfinance]:
            try:
                return await source.fetch(symbol, timeframe)
            except Exception as e:
                logger.warning("Source %s failed: %s", source.name, e)
        raise DataUnavailableError(f"All sources failed for {symbol}/{timeframe}")
```

---

### 10.5 — Kubernetes HPA + PodDisruptionBudget

**Why required:** Zero-downtime deployments require both HPA (auto-scaling) and PDB
(minimum available pods during rolling updates).

**Files:** `helm/templates/hpa-api.yaml` (new), `helm/templates/pdb-api.yaml` (new)

```yaml
# helm/templates/hpa-api.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300

# helm/templates/pdb-api.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: hopefx-api
```

---

## 11. Observability & Security — Full Enhancement Catalogue

### 11.1 — Sentry Production Alert Taxonomy

**Why required:** Sentry is wired but all alerts go to the same queue. Institutional
systems triage alerts by severity and route to different channels.

**Files:** `utils/telemetry.py`, `core/startup_factories.py`

**Alert taxonomy:**

| Level | Trigger | Channel | Response Time |
|-------|---------|---------|---------------|
| `fatal` | Kill switch activated, position reconciliation failure | PagerDuty + SMS | Immediate |
| `error` | Model load failure, broker connection lost, fill rejected | Sentry + Discord | < 5 min |
| `warning` | Feature drift PSI > 0.1, Sharpe drop > 0.1, latency SLA breach | Sentry + email | < 1 hour |
| `info` | Model retrain complete, paper gate status change | Sentry only | Next business day |

```python
# utils/telemetry.py — structured alert routing:
import sentry_sdk

def alert(level: str, message: str, context: dict = None, exc: Exception = None):
    """Unified alert function with channel routing."""
    extra = context or {}

    if level == "fatal":
        sentry_sdk.capture_message(message, level="fatal", extras=extra)
        _pagerduty_alert(message, extra)
        _sms_alert(message)
    elif level == "error":
        if exc:
            sentry_sdk.capture_exception(exc, extras=extra)
        else:
            sentry_sdk.capture_message(message, level="error", extras=extra)
        _discord_alert(f"ERROR: {message}", extra)
    elif level == "warning":
        sentry_sdk.capture_message(message, level="warning", extras=extra)
    # info: Sentry only, no external channel
```

---

### 11.2 — Security Hardening Checklist

**Why required:** A trading platform handling real money is a high-value target.
The following security controls are required before any live capital.

**Current gaps and fixes:**

| Gap | File | Fix | Effort |
|-----|------|-----|--------|
| JWT secret rotation | `api/auth.py` | Add `JWT_SECRET_ROTATION_DAYS=90` + auto-rotate | 2h |
| API rate limiting | `api/` all routers | Add `slowapi` rate limiter: 100 req/min per user | 2h |
| SQL injection | `database/` | Verify all queries use SQLAlchemy ORM (no raw SQL) | 1h |
| Secrets in logs | `utils/logger.py` | Add `SensitiveDataFilter` to scrub API keys from logs | 1h |
| CORS misconfiguration | `app.py` | Restrict `allow_origins` to production domain only | 30m |
| Missing HTTPS enforcement | `helm/templates/ingress.yaml` | Add TLS redirect + HSTS header | 1h |
| Dependency vulnerabilities | `requirements.txt` | Add `pip-audit` to CI pipeline | 1h |
| Container runs as root | `Dockerfile` | Add `USER hopefx` non-root user | 30m |

**Rate limiting implementation:**

```python
# app.py — add rate limiting:
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# On sensitive endpoints:
@router.post("/api/auth/login")
@limiter.limit("10/minute")  # brute-force protection
async def login(request: Request, ...):
    ...

@router.post("/api/trading/order")
@limiter.limit("100/minute")  # order rate limit
async def place_order(request: Request, ...):
    ...
```

**Dockerfile non-root user:**

```dockerfile
# Dockerfile — add near end:
RUN addgroup --system hopefx && adduser --system --ingroup hopefx hopefx
RUN chown -R hopefx:hopefx /app
USER hopefx
```

---

### 11.3 — Secrets Management (HashiCorp Vault)

**Why required:** Current secrets are in `.env` files. For production Kubernetes
deployment, secrets must be managed by HashiCorp Vault or AWS Secrets Manager.

**Files:** `config/vault.py` (exists), `helm/templates/secret.yaml`

**Vault integration:**

```python
# config/vault.py — enhance with dynamic secrets:
import hvac

class VaultClient:
    def __init__(self):
        self._client = hvac.Client(
            url=os.getenv("VAULT_ADDR", "http://vault:8200"),
            token=os.getenv("VAULT_TOKEN"),
        )

    def get_secret(self, path: str, key: str) -> str:
        """Reads secret from Vault KV v2."""
        response = self._client.secrets.kv.v2.read_secret_version(path=path)
        return response["data"]["data"][key]

    def get_oanda_credentials(self) -> dict:
        return {
            "api_key": self.get_secret("hopefx/oanda", "api_key"),
            "account_id": self.get_secret("hopefx/oanda", "account_id"),
        }
```

**Kubernetes Sealed Secrets** for GitOps-safe secret storage:

```bash
# Encrypt secret for Git storage:
kubectl create secret generic hopefx-secrets \
  --from-literal=OANDA_API_KEY=xxx \
  --dry-run=client -o yaml | kubeseal > helm/templates/sealed-secret.yaml
```

---

### 11.4 — Security Audit Automation

**Why required:** Manual security reviews miss regressions. Automated scanning in CI
catches vulnerabilities before they reach production.

**Files:** `.github/workflows/security-scan.yml` (exists — enhance it)

```yaml
# .github/workflows/security-scan.yml — add comprehensive scanning:
jobs:
  security:
    steps:
      - name: Dependency audit
        run: pip-audit --requirement requirements.txt --format json

      - name: SAST scan (Bandit)
        run: bandit -r . -x tests/ -f json -o bandit-report.json

      - name: Secret detection (Gitleaks)
        uses: gitleaks/gitleaks-action@v2

      - name: Container scan (Trivy)
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: hopefx:${{ github.sha }}
          severity: HIGH,CRITICAL
          exit-code: 1  # fail CI on critical vulnerabilities

      - name: OWASP dependency check
        uses: dependency-check/Dependency-Check_Action@main
```

---

### 11.5 — Live Trading Warnings + Confirmation Gates

**Why required:** `core/live_trading_gate.py` exists. Add explicit human-confirmation
gates before transitioning from paper to live, and before increasing position sizes.

**Files:** `core/live_trading_gate.py`, `api/admin.py`

```python
# core/live_trading_gate.py — add confirmation gates:
class LiveTradingGate:
    CONFIRMATION_REQUIRED_FOR = [
        "paper_to_live_transition",
        "position_size_increase_gt_50pct",
        "new_symbol_addition",
        "kill_switch_deactivation",
    ]

    async def request_confirmation(self, action: str, context: dict,
                                    admin_user_id: str) -> str:
        """
        Creates a pending confirmation token.
        Admin must call /api/admin/confirm/{token} within 10 minutes.
        """
        token = secrets.token_urlsafe(32)
        await self._redis.setex(
            f"confirm:{token}",
            600,  # 10 minute expiry
            json.dumps({"action": action, "context": context,
                         "requested_by": admin_user_id,
                         "requested_at": datetime.utcnow().isoformat()})
        )
        await self._alert_admins(f"Confirmation required: {action}", token)
        return token
```

---

## 12. Commercial & SaaS — Full Enhancement Catalogue

### 12.1 — SaaS Multi-Tenant Architecture

**Why required:** Current architecture is single-tenant. For commercial deployment,
each customer must have isolated data, separate broker credentials, and independent
risk limits.

**Files:** `database/models.py`, `api/` all routers, `config/settings.py`

**Tenant isolation model:**

```python
# database/models.py — add tenant isolation:
class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    plan = Column(String(20), nullable=False)  # "starter" | "pro" | "institutional"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

# All trading tables get tenant_id foreign key:
class Trade(Base):
    tenant_id = Column(UUID, ForeignKey("tenants.id"), nullable=False)
    # Row-level security: every query must filter by tenant_id
```

**Row-Level Security (PostgreSQL RLS):**

```sql
-- Enforce tenant isolation at database level:
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON trades
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

**Middleware to set tenant context:**

```python
# api/middleware.py — tenant context middleware:
class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user = await get_current_user_from_request(request)
        if user:
            # Set PostgreSQL session variable for RLS
            async with db.begin():
                await db.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(user.tenant_id)}
                )
        return await call_next(request)
```

---

### 12.2 — Stripe Billing Enhancement

**Why required:** `api/billing.py` and `api/payments.py` exist with Stripe integration.
Missing: usage-based billing (per-trade fees), invoice generation, dunning management.

**Files:** `api/billing.py`, `api/payments.py`, `api/monetization.py`

**Pricing tiers:**

| Plan | Price | Limits | Features |
|------|-------|--------|---------|
| Starter | $49/mo | 1 symbol, 10 trades/day, paper only | Basic signals, no ML |
| Pro | $199/mo | 5 symbols, unlimited trades, live | Full ML, SHAP, alerts |
| Institutional | $999/mo | Unlimited, white-label, API access | All features + SLA |
| Enterprise | Custom | Dedicated infra, custom models | Full source access |

**Usage-based billing:**

```python
# api/billing.py — add usage metering:
async def record_trade_usage(tenant_id: str, trade_count: int = 1):
    """Records trade usage for metered billing."""
    await stripe.UsageRecord.create(
        subscription_item=await _get_subscription_item(tenant_id),
        quantity=trade_count,
        timestamp=int(datetime.utcnow().timestamp()),
        action="increment",
    )
```

---

### 12.3 — White-Label Kit

**Why required:** `whitelabel/__init__.py` exists. Institutional clients want to
rebrand HOPEFX as their own product. White-label requires: custom domain, logo,
color scheme, and removal of HOPEFX branding.

**Files:** `whitelabel/`, `dashboard/src/`, `templates/`

**White-label configuration:**

```python
# whitelabel/config.py (new)
@dataclass
class WhiteLabelConfig:
    tenant_id: str
    brand_name: str           # "AcmeFX Trading"
    logo_url: str             # CDN URL
    primary_color: str        # "#1a73e8"
    secondary_color: str      # "#34a853"
    domain: str               # "trading.acmefx.com"
    support_email: str
    hide_hopefx_branding: bool = True
    custom_css_url: str = ""
    custom_js_url: str = ""   # for analytics injection
```

**Dashboard theming:**

```typescript
// dashboard/src/theme/whitelabel.ts
export const getWhiteLabelTheme = async (): Promise<Theme> => {
  const config = await fetch('/api/whitelabel/config').then(r => r.json());
  return createTheme({
    palette: {
      primary: { main: config.primary_color },
      secondary: { main: config.secondary_color },
    },
    components: {
      MuiAppBar: {
        styleOverrides: {
          root: { backgroundColor: config.primary_color }
        }
      }
    }
  });
};
```

---

### 12.4 — Mobile App Completion

**Why required:** `api/mobile.py` exists. Mobile trading alerts are essential for
institutional clients who need to monitor positions away from desk.

**Files:** `api/mobile.py`, `dashboard/` (React Native or PWA)

**Push notification integration:**

```python
# api/mobile.py — enhance push notifications:
class MobilePushService:
    async def send_signal_alert(self, user_id: str, signal: dict):
        """Sends push notification for new trading signal."""
        await self._fcm.send(
            token=await self._get_device_token(user_id),
            notification={
                "title": f"Signal: {signal['direction'].upper()} {signal['symbol']}",
                "body": f"Confidence: {signal['confidence']:.0%} | "
                        f"Entry: {signal['entry_price']:.2f}",
            },
            data={
                "signal_id": signal["id"],
                "type": "trading_signal",
                "deep_link": f"hopefx://signal/{signal['id']}",
            },
            android={"priority": "high"},
            apns={"headers": {"apns-priority": "10"}},
        )
```

---

### 12.5 — API Rate Limiting + Monetization

**Why required:** Public API access must be metered and rate-limited per plan tier.

**Files:** `api/` all routers, `api/monetization.py`

```python
# api/monetization.py — plan-based rate limits:
PLAN_RATE_LIMITS = {
    "starter":       {"requests_per_minute": 60,  "signals_per_day": 10},
    "pro":           {"requests_per_minute": 300, "signals_per_day": 1000},
    "institutional": {"requests_per_minute": 1000, "signals_per_day": -1},  # unlimited
}

def get_rate_limit(plan: str) -> str:
    limits = PLAN_RATE_LIMITS.get(plan, PLAN_RATE_LIMITS["starter"])
    return f"{limits['requests_per_minute']}/minute"
```

---

## 13. Future-Proofing — Full Enhancement Catalogue

### 13.1 — Multimodal LLM Integration

**Why required:** GPT-4o and Claude 3.5 can process charts, earnings transcripts,
and Fed meeting minutes as images + text. This is the next frontier in alpha generation.

**Files:** `ml/news_intelligence.py`, `api/chat.py`

**Chart analysis:**

```python
# ml/news_intelligence.py — add chart analysis:
async def analyze_chart(self, chart_image_base64: str,
                          symbol: str, timeframe: str) -> dict:
    """
    Sends chart screenshot to GPT-4o for pattern recognition.
    Supplements quantitative signals with visual pattern analysis.
    """
    response = await self._client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": f"Analyze this {symbol} {timeframe} chart. "
                         "Identify: trend direction, key support/resistance, "
                         "chart patterns, and likely next move. "
                         "Respond with JSON: {direction, confidence, patterns, levels}"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{chart_image_base64}"}}
            ]
        }],
        max_tokens=300,
        timeout=5.0,
    )
    return json.loads(response.choices[0].message.content)
```

**Safety:** Chart analysis is advisory only — it cannot override risk blocks or
increase position size beyond approved limits. Max weight in signal fusion: 0.10.

---

### 13.2 — Satellite Data Pipeline

**Why required:** Satellite data (gold mine production, shipping routes, geopolitical
activity) provides non-correlated alpha. Used by Citadel, Two Sigma, and Point72.

**Files:** `data/feeds/satellite_feed.py` (new)

**Data sources:**

| Source | Data | Provider | Cost |
|--------|------|----------|------|
| Spire Global | Shipping AIS (gold transport) | API | $500/mo |
| Planet Labs | Mine activity (open-pit gold mines) | API | $1000/mo |
| Orbital Insight | Commodity storage levels | API | $2000/mo |
| Quandl/Nasdaq | Aggregated satellite indices | API | $200/mo |

**Phase 3+ only** — requires significant data budget. Start with Quandl aggregated
indices as a cost-effective proxy.

---

### 13.3 — Low-Latency Execution Path

**Why required:** Current Python async execution targets < 500ms. For HFT-adjacent
strategies (M1/M5 timeframes), sub-100ms execution is required.

**Architecture options:**

| Approach | Latency | Effort | When |
|----------|---------|--------|------|
| Python async (current) | 200–500ms | 0 | Now |
| Python + C extension for hot path | 50–200ms | 40h | Phase 3 |
| Rust microservice for execution | 5–50ms | 200h | Phase 3+ |
| Co-location at OANDA data center | 1–5ms | Infra cost | Phase 4 |

**Python + C extension approach (Phase 3):**

```python
# execution/fast_path.py — Cython/ctypes hot path:
# Compile: python setup_fast_path.py build_ext --inplace
# The fast path handles: signal threshold check + order size calc + broker submit
# Everything else stays in Python
```

**Rust microservice (Phase 3+):**

```
execution/
├── rust_executor/          — Rust crate
│   ├── src/main.rs         — Tokio async runtime
│   ├── src/oanda.rs        — OANDA v20 REST client
│   └── src/risk.rs         — Pre-trade gate (port of Python logic)
└── executor_client.py      — Python gRPC client to Rust service
```

---

### 13.4 — Federated Learning for Multi-Client Models

**Why required:** With multiple institutional clients, each client's trading data
can improve the shared model without sharing raw data (privacy-preserving).

**Architecture:**

```
FederatedLearningCoordinator (new: ml/federated.py)
├── ClientModelAggregator   — FedAvg algorithm
├── DifferentialPrivacy     — Gaussian noise injection (ε=1.0)
├── SecureAggregation       — Encrypted gradient aggregation
└── GlobalModelUpdater      — Updates shared model from client gradients
```

**Phase 4 only** — requires multiple institutional clients with sufficient data volume.

---

### 13.5 — Quantum-Resistant Cryptography

**Why required:** NIST post-quantum cryptography standards (CRYSTALS-Kyber,
CRYSTALS-Dilithium) are finalized. Trading systems handling financial data should
begin migration before quantum computers break RSA/ECDSA.

**Files:** `utils/security.py`, `security_service.py`

**Migration path:**
1. Audit all cryptographic operations (JWT signing, TLS, API key storage)
2. Replace RSA-2048 JWT signing with Ed25519 (already quantum-resistant)
3. Plan migration to CRYSTALS-Dilithium for JWT when library support matures
4. Ensure TLS 1.3 (already quantum-resistant for symmetric keys)

**Immediate action:** Switch JWT algorithm from `HS256` to `EdDSA` (Ed25519):

```python
# security_service.py — use Ed25519 for JWT:
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_key = Ed25519PrivateKey.generate()
token = jwt.encode(payload, private_key, algorithm="EdDSA")
```

---

## 14. Testing & Rollback Strategy

### 14.1 — Test Coverage Requirements

| Layer | Current | Target | Method |
|-------|---------|--------|--------|
| Unit tests | 2560 passing | 3000+ | Add tests for all new components |
| Integration tests | 18 | 50+ | API→DB→broker flow tests |
| E2E tests | Partial | Full signal→fill→audit chain | `tests/e2e/test_trading_flow.py` |
| Chaos tests | Partial | 10 scenarios | `tests/chaos/` |
| Load tests | k6 + Locust | 1000 concurrent users | `tests/test_k6_load_tests.py` |
| Property-based | Hypothesis | Risk invariants | `tests/unit/test_risk_properties.py` |

**Coverage gate:** CI blocks merge if coverage < 80% on `ml/`, `risk/`, `execution/`.

---

### 14.2 — Model Rollback Procedure

**Trigger:** Live Sharpe drops > 0.2 from 30-day baseline, or OOS accuracy drops > 3%.

```bash
# Step 1 — Identify last good model version
mlflow ui  # or: mlflow models list --name hopefx_xgboost

# Step 2 — Roll back via API (admin only)
curl -X POST https://api.hopefx.com/api/ml/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model": "xgboost", "version": 3, "reason": "sharpe_degradation"}'

# Step 3 — Verify rollback
curl https://api.hopefx.com/api/ml/health | jq '.model_version'

# Step 4 — Investigate degradation
python ml/train_advanced.py --diagnose --compare-versions 3 4
```

**Automatic rollback:** If live Sharpe drops > 0.3 in 7 days, auto-rollback fires
and alerts admin. Requires human confirmation to re-enable new model.

---

### 14.3 — Deployment Rollback (Kubernetes)

```bash
# Roll back to previous deployment:
kubectl rollout undo deployment/hopefx-api

# Roll back to specific revision:
kubectl rollout undo deployment/hopefx-api --to-revision=3

# Verify rollback:
kubectl rollout status deployment/hopefx-api

# Check which image is running:
kubectl get deployment hopefx-api -o jsonpath='{.spec.template.spec.containers[0].image}'
```

**Blue-green deployment** (Phase 3): Run two identical environments. Switch traffic
via load balancer. Instant rollback by switching back.

---

### 14.4 — Incident Response Playbook

| Incident | Detection | Response | Recovery |
|----------|-----------|----------|---------|
| Kill switch fires | Sentry fatal + PagerDuty | Close all positions, halt trading | Investigate cause, human approval to restart |
| Position reconciliation failure | Sentry error | Halt new orders, reconcile manually | Fix discrepancy, restart reconciler |
| Model accuracy drops > 5% | Daily accuracy check | Switch to fallback model | Retrain + validate before re-enabling |
| Broker connection lost | Circuit breaker opens | Route to backup broker | Restore primary, verify positions |
| Database down | Health check fails | Serve from Redis cache (read-only) | Restore DB, replay missed events |
| Redis down | Connection error | Fall back to in-memory state | Restore Redis, reconcile state |
| DDoS attack | Rate limiter triggers | Auto-block IPs, scale up | Cloudflare WAF activation |

---
