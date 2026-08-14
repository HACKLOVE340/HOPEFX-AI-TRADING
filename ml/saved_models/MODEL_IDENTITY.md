# Model Identity & Reconciliation

## Retraining

Production retraining uses 25 years of XAUUSD history with an 8-year held-out
OOS period. Run via:

```bash
./scripts/retrain.sh                    # full production retrain (25Y, 8Y OOS)
./scripts/retrain.sh --smoke            # CI smoke test (2Y, no OOS)
```

The Sharpe gate requires N ≥ 600 OOS trades before the model is considered
credible for live deployment. The current model has N=2016 (gate PASSED).

**Why 25 years and not 50.** `data/XAUUSD_50Y.csv` reaches back to 1968 and
15.2% of the bars a 50-year window selects move more than 20% in one session —
one by 519%; its 1990 rows dip to $81 in a year gold traded near $380.
`api/trading.py` has always refused to serve that file to charts for exactly
this reason, while training loaded it by preference. `ml/train_advanced.py` now
rejects a source that corrupt, so 25 years (from 2001-08, 6,424 bars, zero
implausible moves) is the deepest window that is actually real. The figures
recorded below predate that gate and were measured over the wider, partly
fictional window — treat them as unverified until the next retrain.

## Current Status: Active model `xgb_horizon5_v3`

`advanced_oos.pkl` was retrained **in place** on 2026-06-26 (`horizon=5`, to
match the execution engine's 5-bar hold period). Retraining over the same
filename left every older registry entry pointing at the new file while still
describing the model it replaced:

| Registry key      | Claimed (before) | Now | History |
|-------------------|------------------|-----|---------|
| `advanced_oos_v1` | 56.5% | **57.34%** | originally described the pre-2026-06-26 model |
| `advanced_oos_v2` | 56.5% | **57.34%** | same |
| `xgb_horizon5_v1` | 56.5% | **57.34%** | same (this file previously named it active) |
| `xgb_horizon5_v3` | 57.34% | **57.34%** | always matched the artifact — **active** |

The authority is `advanced_oos_meta.json`, written by the trainer in the same
run as the `.pkl`: `oos_accuracy 0.5734`, `oos_n 2016`, `horizon 5`, trained
`2026-06-26T22:30:43Z`. The 59.9% previously quoted below belonged to the
2026-04-02 model, which no longer exists on disk.

**Repaired 2026-08-14** with `scripts/repair_model_registry.py --resync`. All
four entries point at the same `advanced_oos.pkl`, so every one of them now
records that file's own measured 0.5734 rather than a score from a model it no
longer refers to. `audit_manifest()` reports zero `stale_metrics` and zero
`metric_conflicts`; the previous manifest is kept beside it as a timestamped
`.bak` (gitignored).

The trade-off is worth stating, because `--resync` is not the only reading. It
asserts each entry describes the artifact it currently points at, which is true
— but it means the manifest no longer records that `v1`/`v2` were *originally*
measured at 56.5% against a model that has since been overwritten. That history
now lives only in this table. The alternative, `--prune-stale`, would have
deleted those entries instead; resync was chosen so the version lineage stays
intact. Nothing was averaged: 0.5692 (the midpoint of the two disputed scores)
describes no model that was ever trained.

`ModelRegistry.audit_manifest()` detects this class of drift, and the superadmin
diagnostics page reports it as `model_registry`.

### `mtf_ensemble_v1` — pruned 2026-08-14

The entry pointed at `ml/saved_models/mtf_ensemble.pkl`, which does not exist,
while advertising `oos_accuracy` 0.6135 — the highest figure the ML Models
table displayed, with no artifact behind it. Removed with
`scripts/repair_model_registry.py --prune-missing`.

Only the manifest entry was removed; no file was deleted (there was none). If
the artifact is ever restored, re-register it rather than reinstating the entry
by hand — the sidecar beside the `.pkl` is the measurement, and a
hand-written entry is how this class of drift started.

`audit_manifest()` now reports `ok: True`: no stale metrics, no metric
conflicts, no missing artifacts.

## Active Production Model (`advanced_oos.pkl` ← `current.pkl`)

Registry key: **`xgb_horizon5_v3`** (`active_version` in registry.json)

| Property | Value |
|----------|-------|
| Trained at | 2026-06-26T22:30:43 UTC |
| Training data | XAUUSD 50-year daily (15,197 rows → 9,410 after filtered-target) |
| Features | 193 engineered |
| Horizon | **5 bars** (aligned with execution hold period) |
| OOS period | 2018-04-12 → 2026-03-18 (8 years, 2,016 bars) |
| OOS accuracy | **57.34%** (p = 0.0000, SE 0.011) — per `advanced_oos_meta.json` |
| OOS F1 | 0.6767 |
| OOS AUC | 0.582 |
| Walk-forward accuracy | 56.26% ± 6.26% (6 folds) |
| Walk-forward Fold-2 | **44.4%** (below-chance — parabolic regime; see `docs/FOLD2_REGIME_ANALYSIS.md`) |
| Sharpe gate | PASSED — N=2016 ≥ 600, SE=0.033 ≤ 0.10, Sharpe=1.52 |
| Regime filter | `HIGH_VOL_PARABOLIC` abstain gate active |

## Staged Model: MTF Ensemble (`mtf_ensemble.pkl`)

Registry key: `mtf_ensemble_v1` — **removed from registry.json on 2026-08-14,
and `ml/saved_models/mtf_ensemble.pkl` does not exist.** The 61.4% below is
retained as a historical record of what this model measured; it is no longer in
the registry and no longer appears in the ML Models table. Restoring the
artifact means re-registering it from its sidecar, not re-adding the entry.

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
| Sharpe gate | NOT passed |
| State at removal | retired |
| sha256 (of the absent file) | `d270cf34336527ce6d12ec9d8a0eaa20f9be615356f59095b0a7178e0c1695dd` |
| Regenerate with | `python scripts/retrain_mtf_accuracy.py` |

### Leakage bug — fixed 2026-04-20

**This record was carried in the registry entry and moved here when the entry
was pruned, because deleting it would have destroyed the audit trail of a
data-leakage fix.** Four tests in `tests/unit/test_mtf_ensemble_leakage.py`
exist solely to guarantee it survives; they now read this file.

`CalibratedClassifierCV(cv=3)` re-trained base learners on the test fold,
leaking test data into training and inflating walk-forward CV accuracy to
**~99%** — a number that was never real. True CV accuracy is ~57–60%.

Fixed with a three-way split: `X_fit` (60%) trains the base learners, `X_oof`
(20%) builds the out-of-fold meta-features, `X_cal` (20%) calibrates the
meta-LR. Every `CalibratedClassifierCV` call now uses `cv=prefit`, so nothing
re-trains on held-out data.

The 61.4% OOS figure above post-dates the fix and is the reliable metric; the
99% CV figure must never be quoted as this model's accuracy.

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
