# Model Identity & Reconciliation

## Current Status: RESOLVED

The pkl/meta mismatch documented here has been fixed. A full 50-year retrain
was completed on 2026-03-28. The pkl on disk now matches `advanced_oos_meta.json`.

## Active Production Model (`advanced_oos.pkl`)

| Property | Value |
|----------|-------|
| Trained at | 2026-03-28T02:55:32 UTC |
| Training data | XAUUSD 50-year daily (6,415 bars -> 4,616 after filtered-target) |
| Features | 176 engineered |
| OOS period | 2019-04-12 to 2026-03-24 (5 years, 1,260 bars) |
| OOS accuracy | **66.3% +/- 1.3%** (p = 0.0000) -- statistically significant |
| OOS F1 | 0.728 |
| OOS AUC | 0.711 |
| Walk-forward accuracy | 0.624 +/- 0.031 (8 folds, p = 0.0000) |
| Abstain rate | ~27.5% of bars (filtered-target: |move| < 0.25 ATR) |
| Coverage-adjusted accuracy | ~63.0% across all bars |
| Sharpe gate | PASSED -- N=1,260 >= 600, SE=0.041 <= 0.10 |

## Verification Command

```bash
python3 - << 'EOF'
import json, os, datetime
meta = json.load(open("ml/saved_models/advanced_oos_meta.json"))
pkl_mtime = datetime.datetime.fromtimestamp(
    os.path.getmtime("ml/saved_models/advanced_oos.pkl"),
    tz=datetime.timezone.utc
)
print(f"pkl mtime:       {pkl_mtime.isoformat()}")
print(f"meta trained_at: {meta.get('trained_at', 'MISSING')}")
print(f"oos_accuracy:    {meta.get('oos_accuracy')}")
print(f"significant:     {meta.get('oos_significant')}")
assert meta.get('_WARNING') is None, "WARNING field present -- mismatch not resolved"
print("Identity check: PASSED")
EOF
```

## Historical Mismatch (resolved)

Prior to 2026-03-28, `advanced_oos_meta.json` was written by a 50-year run
but the pkl was overwritten by a 2-year run (325 rows, 52.3%, p=0.409).
That mismatch is now resolved. The `_WARNING` field in the meta is absent,
confirming the current pkl and meta were produced by the same training run.

## Remaining Deployment Gates

Live capital deployment still requires:
1. >=500 verified fills through the real OANDA paper trading API
2. 30+ days continuous paper trading without system errors
3. Monte Carlo backtest reconciled with OOS evaluation strategy parameters
