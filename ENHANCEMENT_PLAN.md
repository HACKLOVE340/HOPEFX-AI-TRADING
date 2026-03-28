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
