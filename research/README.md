# Research Pipeline

`research/pipeline/` contains experimental ML components that are not yet
imported by the live signal engine. This document explains what each module
does and the intended path to production.

---

## Module Inventory

| Module | Lines | Description |
|--------|-------|-------------|
| `models_deep.py` | ~800 | LSTM, Transformer, TCN architectures (PyTorch/Keras) |
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

## Why It Is Not Live Yet

The research pipeline is deliberately separated from production. Reasons:

1. **Deep learning models** (LSTM/Transformer/TCN) require GPU training and
   have not been evaluated on the same 3-year held-out OOS period as
   `advanced_oos.pkl`. They cannot be promoted to production without a
   rigorous OOS evaluation matching the methodology in `ml/train_advanced.py`.

2. **Online learning** with drift detection is promising but requires a
   calibration period on live data before it can be trusted for order sizing.
   The drift detector needs to observe at least 500 bars to establish a
   baseline false-positive rate.

3. **Multi-timeframe fusion** requires H4 and D1 bar feeds in addition to H1.
   The current `data/scheduler.py` only fetches H1 bars. Adding H4/D1 feeds
   is a prerequisite.

4. **Microstructure features** (bid-ask spread, order flow imbalance) require
   a live Level 2 data feed. OANDA's practice API provides mid-prices only.
   These features cannot be computed without a real market data subscription.

---

## Integration Path

### Phase 1 — Multi-timeframe fusion (lowest risk, highest expected value)

**Prerequisite**: Add H4 and D1 bar fetching to `data/scheduler.py`.

**Integration**:
```python
# In core/startup_factories.py, add:
async def init_mtf_store(s):
    from research.pipeline.mtf_fusion import MTFFusionStore
    store = MTFFusionStore()
    await store.bootstrap()
    s.mtf_store = store
    return store

# In core/signal_engine.py::_compute_ml_probability(), add:
mtf_features = getattr(app_state, 'mtf_store', None)
if mtf_features:
    mtf_df = mtf_features.align_to_h1(ohlcv_df)
    ml_probability = adv_predictor.predict_proba(
        ohlcv_df, macro_df=macro_df, mtf_df=mtf_df
    )
```

**Gate**: OOS accuracy on the 756-bar held-out period must remain ≥ 65%
after adding MTF features. If it drops below 65%, MTF features are excluded.

### Phase 2 — Anomaly weighting

**Prerequisite**: Phase 1 complete, 30-day paper trading run complete.

**Integration**: Wrap `_compute_ml_probability()` output with an anomaly
weight from `research/pipeline/anomaly.py::AnomalyWeighter`. Signals
generated during anomalous market conditions (Isolation Forest score > 0.7)
are down-weighted by 50%.

**Gate**: Paper trading Sharpe must not decrease by more than 0.2 after
adding anomaly weighting over a 30-day window.

### Phase 3 — Online learning with drift detection

**Prerequisite**: Phase 2 complete, 90-day paper trading run complete.

**Integration**: Add `research/pipeline/online_learning.py::OnlineLearner`
as a secondary model that updates its weights on each confirmed fill. The
primary model (`advanced_oos.pkl`) remains unchanged. The online learner's
probability is blended: `0.7 * advanced_prob + 0.3 * online_prob`.

**Gate**: Online learner must demonstrate positive contribution to signal
quality over a 60-day window before the blend weight is increased.

### Phase 4 — Deep learning ensemble (highest risk, longest timeline)

**Prerequisite**: Phase 3 complete, GPU training infrastructure available.

**Integration**: Train LSTM/Transformer/TCN on the same 50-year dataset
using the same OOS methodology as `ml/train_advanced.py`. If OOS accuracy
exceeds 70% with p < 0.001, add as a third component in the stacking
ensemble (`research/pipeline/models_ensemble.py`).

**Gate**: Each deep model must independently pass the OOS significance test
before being included in the ensemble.

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

Research contributions follow a different standard than production code:

1. All experiments must include an OOS evaluation on the 756-bar held-out
   period (2023-03-22 → 2026-03-24) using `ml/train_advanced.py::oos_eval_advanced()`
2. Results must be documented in `research/results/` with the full confusion
   matrix, p-value, and feature importance
3. A research component is only promoted to production after passing all
   gates in the integration path above
4. Do not import research modules from `core/`, `api/`, or `ml/` without
   completing the integration path
