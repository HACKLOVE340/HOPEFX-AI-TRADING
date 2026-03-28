# Model Identity & Reconciliation

## Problem

Two training runs produced conflicting artifacts. The meta JSON and the pkl on
disk were written by different runs. Any system that reads `advanced_oos_meta.json`
to characterize `advanced_oos.pkl` will report incorrect metrics.

## Artifact Map

| File | Produced by | Training data | OOS accuracy | Significant? |
|------|-------------|---------------|--------------|--------------|
| `advanced_oos.pkl` | 2-year run (2026-03-27) | GC=F, 324 rows | 52.3% (p=0.409) | **NO** |
| `advanced_oos_meta.json` (stale) | 50-year run (2026-03-26) | XAUUSD, 3,860 rows | 67.3% (p=0.000) | YES |
| `advanced_training_report.json` | 2-year run (2026-03-27) | GC=F, 324 rows | 52.3% (p=0.409) | **NO** |

The pkl mtime (`2026-03-27`) is **later** than the meta mtime (`2026-03-26`),
confirming the pkl was overwritten by the 2-year run after the meta was written.

## Research Model (separate, not the production pkl)

`research/results/mtf_fusion_xauusd_v1/oos_eval.json`:
- Symbol: XAUUSD
- Training rows: ~4,600 (50-year daily)
- OOS rows: 756
- OOS accuracy: **68.0%** (p = 0.0000) — statistically significant
- Abstain rate: 27.5% of bars
- Coverage-adjusted accuracy: 63.1% across all bars

This is the model behind the 68% claim in the README. It is a research
experiment, not the file loaded by the production inference path.

## Production Inference Path

`ml/inference_engine.py` (or equivalent) loads `advanced_oos.pkl`. Until a
full retrain is completed, the production model is the 2-year run with
**52.3% accuracy (p=0.409)** — statistically indistinguishable from random.

## Required Fix

```bash
# Full retrain against 50-year dataset
python scripts/retrain_model.py --advanced --years 50 --oos-years 5

# After retrain, verify pkl mtime matches trained_at in the new meta:
python - << 'EOF'
import json, os, datetime
meta = json.load(open("ml/saved_models/advanced_oos_meta.json"))
pkl_mtime = datetime.datetime.fromtimestamp(
    os.path.getmtime("ml/saved_models/advanced_oos.pkl"),
    tz=datetime.timezone.utc
)
print(f"pkl mtime:       {pkl_mtime.isoformat()}")
print(f"meta trained_at: {meta.get('trained_at', 'MISSING')}")
EOF
```

The pkl mtime and `trained_at` must agree (within seconds) before live
deployment is approved.

## Deployment Gate

Live deployment is **BLOCKED** until:
1. Full retrain completes with `--years 50 --oos-years 5`
2. New pkl OOS accuracy >= 55% with p < 0.05
3. pkl mtime matches meta `trained_at`
4. `advanced_oos_meta.json` `_WARNING` field is removed by the retrain script
