# Research Results

All experiment results must be stored here before a component is promoted to production.

## Required Files per Experiment

Each experiment directory must contain:

```
research/results/<experiment_name>/
    report.json          # Full metrics (see schema below)
    confusion_matrix.csv # Rows: actual, Cols: predicted
    feature_importance.csv
    oos_eval.json        # OOS accuracy, p-value, n_samples
```

## report.json Schema

```json
{
  "experiment": "string — unique experiment identifier",
  "date": "ISO-8601 UTC timestamp",
  "model": "string — model type (xgb_stack | lstm | transformer | tcn | ensemble)",
  "symbol": "string — e.g. XAUUSD",
  "oos_period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
  "n_oos_samples": "integer",
  "oos_accuracy": "float — must be >= phase gate threshold",
  "p_value": "float — one-sided binomial p-value (H0: acc <= 0.5)",
  "auc_roc": "float",
  "f1": "float",
  "precision": "float",
  "recall": "float",
  "abstain_rate": "float — fraction of bars filtered by confidence threshold",
  "sharpe_oos": "float — strategy Sharpe on OOS period",
  "max_drawdown_oos": "float — max drawdown on OOS period",
  "feature_count": "integer",
  "top_features": ["list of top-10 feature names by SHAP importance"],
  "phase_gate": "string — which gate this result satisfies (phase1|phase2|phase3|phase4)",
  "gate_passed": "boolean",
  "notes": "string — any caveats or observations"
}
```

## Phase Gate Thresholds

| Phase | Component | OOS Accuracy Gate | p-value Gate | Additional Gate |
|-------|-----------|-------------------|--------------|-----------------|
| 1 | MTFFusionStore | >= 65% | < 0.05 | — |
| 2 | AnomalyWeightStore | — | — | Paper Sharpe drop < 0.2 over 30 days |
| 3 | OnlineLearnerStore | — | — | 90-day paper run, >= 500 fills |
| 4 | DeepEnsembleStore | >= 70% | < 0.001 | GPU training required |

## Promotion Checklist

Before promoting a research component to production:

- [ ] OOS evaluation on held-out period using `ml/train_advanced.py::oos_eval_advanced()`
- [ ] Full confusion matrix saved to `confusion_matrix.csv`
- [ ] p-value computed with one-sided binomial test (H0: accuracy <= 0.5)
- [ ] Feature importance saved (SHAP values preferred)
- [ ] `gate_passed: true` in `report.json`
- [ ] Feature flag wired in `core/signal_engine.py` and `core/startup_factories.py`
- [ ] Tests added to `tests/test_research_pipeline_wiring.py`
- [ ] Paper trading run completed (Phase 2: 30 days, Phase 3: 90 days)

## Existing Results

| Experiment | Date | OOS Acc | p-value | Gate | Status |
|------------|------|---------|---------|------|--------|
| mtf_fusion_xauusd_v1 | 2026-07-14 | 68.0% | 0.0000 | Phase 1 | ✅ Promoted |
