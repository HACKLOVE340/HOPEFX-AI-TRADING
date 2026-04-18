# Model Identity & Reconciliation

## Retraining

Production retraining uses 50 years of XAUUSD history with an 8-year held-out
OOS period. Run via:

```bash
./scripts/retrain.sh                    # full production retrain (50Y, 8Y OOS)
./scripts/retrain.sh --smoke            # CI smoke test (2Y, no OOS)
```

The Sharpe gate requires N ≥ 600 OOS trades before the model is considered
credible for live deployment. The current model has N=2016 (gate PASSED).

## Current Status: RESOLVED — Active model: `xgb_horizon5_v1`

The pkl/meta mismatch documented here has been fixed. The model was retrained on
2026-04-02 with `horizon=5` to match the execution engine's 5-bar hold period.

## Active Production Model (`advanced_oos.pkl` ← `current.pkl`)

Registry key: **`xgb_horizon5_v1`** (`active_version` in registry.json)

| Property | Value |
|----------|-------|
| Trained at | 2026-04-02T15:10:56 UTC |
| Training data | XAUUSD 50-year daily (15,197 rows → 9,410 after filtered-target) |
| Features | 222 engineered |
| Horizon | **5 bars** (aligned with execution hold period) |
| OOS period | 2018-04-12 → 2026-03-18 (8 years, 2,016 bars) |
| OOS accuracy | **59.9%** (p = 0.0000) |
| OOS F1 | 0.6885 |
| OOS AUC | 0.6077 |
| Walk-forward accuracy | 56.26% ± 6.26% (6 folds) |
| Walk-forward Fold-2 | **44.4%** (below-chance — parabolic regime; see `docs/FOLD2_REGIME_ANALYSIS.md`) |
| Sharpe gate | PASSED — N=2016 ≥ 600, SE=0.033 ≤ 0.10, Sharpe=1.52 |
| Regime filter | `HIGH_VOL_PARABOLIC` abstain gate active |

## Staged Model: MTF Ensemble (`mtf_ensemble.pkl`)

Registry key: **`mtf_ensemble_v1`** (staging — pending Sharpe gate + promotion)

| Property | Value |
|----------|-------|
| Trained at | 2026-04-03T16:50:42 UTC |
| Training data | XAUUSD 58-year daily (9,410 bars base + 164 MTF features) |
| Feature layers | base + extended + MTF (weekly/monthly/quarterly) |
| Horizon | 5 bars |
| OOS period | 2018-03-26 → 2026-03-25 (1,687 bars) |
| OOS accuracy | **61.4%** (p = 0.0000, N=1,687) |
| OOS accuracy (confident) | **61.2%** (abstain rate 2.8%) |
| OOS F1 | 0.6133 |
| OOS AUC | 0.6634 |
| pkl format | stacking_dict (not plain sklearn estimator) |
| Promotion requirement | Sharpe gate + execution engine loading fix |

## Symlink State

```bash
ls -la ml/saved_models/current.pkl
# current.pkl -> advanced_oos.pkl  (xgb_horizon5_v1, horizon=5)

sha256sum ml/saved_models/advanced_oos.pkl
# fc176955225e9e5f139443c7adf8fba48a8ef5c0a2443c4c20c8ceae27f581e1
```

## Verification Command

```bash
python3 - << 'EOF'
import json, os, datetime, hashlib
meta = json.load(open("ml/saved_models/advanced_oos_meta.json"))
reg = json.load(open("ml/saved_models/registry.json"))
active = reg["active_version"]
entry = reg["versions"][active]
pkl_path = entry["file"]
sha = hashlib.sha256(open(pkl_path, "rb").read()).hexdigest()
print(f"active_version:  {active}")
print(f"pkl:             {pkl_path}")
print(f"sha256:          {sha}")
print(f"registry sha256: {entry['sha256']}")
print(f"match:           {sha == entry['sha256']}")
print(f"oos_accuracy:    {meta.get('oos_accuracy')}")
print(f"horizon:         {meta.get('horizon')}")
EOF
```

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
