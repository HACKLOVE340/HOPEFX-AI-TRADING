# Research Pipeline

`research/pipeline/` contains ML components that feed into the live signal
engine as optional layers. Each phase is gated by a feature flag and an OOS
accuracy threshold. All four phases are now wired — see integration status below.

> **Last updated:** 2026-07-14 — reflects Phase 1–4 wiring complete.

---

## Module Inventory

| Module | Lines | Description |
|--------|-------|-------------|
| `models_deep.py` | ~800 | LSTM, Transformer, TCN architectures (PyTorch) |
| `online_learning.py` | ~600 | Online learning with concept drift detection (ADWIN, DDM) |
| `mtf_fusion.py` | ~500 | Multi-timeframe feature fusion (H1 + H4 + D1) |
| `microstructure.py` | ~400 | Bid-ask spread, order flow imbalance, VWAP deviation |
| `anomaly.py` | ~350 | Anomaly detection for signal weighting (Isolation Forest, LOF) |
| `models_ensemble.py` | ~300 | Stacking ensemble: XGBoost + LSTM + TCN |
| `regime_models.py` | ~250 | Regime-conditional deep models |
| `feature_engineering.py` | ~200 | Research-specific feature transforms |
| `data_ingestion.py` | ~150 | Data loading for research experiments |
| `orchestrator.py` | ~100 | Pipeline orchestration for research runs |
| `synthetic.py` | ~100 | Synthetic data generation for testing |
| `run_pipeline.py` | ~50 | CLI entry point for research runs |

Total: ~3,800 lines of research code.

---

## Integration Status

| Phase | Component | Flag | Status | Gate |
|-------|-----------|------|--------|------|
| 1 | MTFFusionStore | `FEATURE_MTF_FUSION` | Wired (default: on) | OOS >= 65% |
| 2 | AnomalyWeightStore | `FEATURE_ANOMALY_WEIGHTING` | Wired (default: off) | Paper Sharpe drop < 0.2 |
| 3 | OnlineLearnerStore | `FEATURE_ONLINE_LEARNING` | Wired (default: off) | 90-day paper run |
| 4 | DeepEnsembleStore | `FEATURE_DEEP_ENSEMBLE` | Wired (default: off) | OOS >= 70%, p < 0.001 |

All four phases are wired in `core/signal_engine.py` and
`core/startup_factories.py`. Each is gated by its feature flag and an OOS
accuracy threshold. A phase that fails its gate is silently bypassed and the
signal engine falls back to the previous layer.

---

## Performance Metrics (Corrected)

> **Sharpe correction notice** — the previously reported Sharpe of **4.68**
> was computed at bar level (equity curve pct_change). This method is inflated
> by flat no-trade days suppressing the return standard deviation.
>
> The corrected figure uses **trade-level Sharpe**:
> `mean(net_pnl) / std(net_pnl) x sqrt(252 / avg_hold_days)`

| Metric | Value | Notes |
|--------|-------|-------|
| OOS accuracy | 68.0% | p = 0.0000 — use this as the credible number |
| Sharpe (trade-level, corrected) | 1.52 | N=48 trades at time of report |
| Sharpe (bar-level, deprecated) | ~~4.68~~ | Inflated — do not use |
| Sharpe SE at N=48 | +/-0.21 | Not statistically robust |
| Sharpe SE at N=250 | +/-0.045 | Minimum acceptable |
| Sharpe SE at N=600 | +/-0.029 | Target — statistically robust |
| Trade count (current) | ~48 | Need ~202 more for SE <= +/-0.045 |
| Trade count (target) | 600 | SE <= +/-0.029 — use multi-symbol backtest |

**Credible number to cite:** OOS accuracy = 68.0% (p = 0.0000).
Sharpe of 1.52 is directionally correct but has SE +/-0.21 at N=48 — not
statistically robust until N >= 250.

---

## Why Phases 2-4 Are Off By Default

- **Phase 2 (Anomaly)**: Requires 30-day paper trading run to establish
  baseline false-positive rate. Enable with `FEATURE_ANOMALY_WEIGHTING=true`
  after the OANDA paper run completes.

- **Phase 3 (Online learning)**: Requires 90-day paper run and >= 500 fills
  to calibrate the drift detector. Enable with `FEATURE_ONLINE_LEARNING=true`.

- **Phase 4 (Deep ensemble)**: Requires GPU training and OOS accuracy > 70%
  with p < 0.001. The OOS gate is enforced in `DeepEnsembleStore.load()` —
  a model that fails the gate will not activate even if the flag is on.

---

## Integration Path

### Phase 1 — Multi-timeframe fusion (complete)

Wired in `core/startup_factories.py::init_mtf_store()` and
`core/signal_engine.py::_fetch_mtf_df()`.

Gate: OOS accuracy on the held-out period must remain >= 65% after adding
MTF features. Controlled by `FEATURE_MTF_FUSION` (default: true).

### Phase 2 — Anomaly weighting (wired, awaiting paper run)

Wired in `core/signal_engine.py::_get_anomaly_store()`.

Enable after 30-day OANDA paper trading run:
```
FEATURE_ANOMALY_WEIGHTING=true
```

Gate: Paper trading Sharpe must not decrease by more than 0.2 over a
30-day window after enabling.

### Phase 3 — Online learning with drift detection (wired, awaiting paper run)

Wired in `core/signal_engine.py::_get_online_learner_store()` and
`core/signal_engine.py::notify_fill()`.

Enable after 90-day paper run with >= 500 fills:
```
FEATURE_ONLINE_LEARNING=true
```

Blend: `0.7 x advanced_prob + 0.3 x online_prob` (configurable via
`OnlineLearnerStore(primary_weight=0.7, online_weight=0.3)`).

### Phase 4 — Deep learning ensemble (wired, awaiting trained model)

Wired in `core/signal_engine.py::_get_deep_ensemble_store()`.

Enable after training and OOS evaluation:
```
FEATURE_DEEP_ENSEMBLE=true
DEEP_ENSEMBLE_MODEL_PATH=/path/to/deep_model.pt
DEEP_ENSEMBLE_META_PATH=/path/to/deep_meta.json
```

The meta JSON must contain `{"oos_accuracy": 0.72, "p_value": 0.0001}`.
`DeepEnsembleStore.load()` enforces `oos_accuracy >= 0.70` and `p_value < 0.001`
before activating. A model that fails either gate is silently bypassed.

---

## Running Research Experiments

```bash
# Full research pipeline (training + evaluation)
python research/pipeline/run_pipeline.py --config research/config.yaml

# Individual components
python -m research.pipeline.models_deep --model lstm --epochs 100
python -m research.pipeline.online_learning --window 500
python -m research.pipeline.mtf_fusion --timeframes H1,H4,D1
```

---

## Contributing Research

1. All experiments must include an OOS evaluation on the held-out period
   using `ml/train_advanced.py::oos_eval_advanced()`
2. Results must be documented in `research/results/` with the full confusion
   matrix, p-value, and feature importance
3. A research component is only promoted to production after passing all
   gates in the integration path above
4. Do not import research modules from `core/`, `api/`, or `ml/` without
   completing the integration path — use the feature flag gates instead
