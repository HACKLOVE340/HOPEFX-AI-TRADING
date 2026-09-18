# 0019. Drift blocking, model quality blocking, and the z threshold

- Status: proposed
- Date: 2026-09-13

## Context

`DRIFT_BLOCK` decides whether a detected feature-distribution drift stops
inference or merely logs. The code default is `false`
(`ml/inference_engine.py:120`). Every surface that deploys this system sets it
`true`:

| Surface | `DRIFT_BLOCK` | `DRIFT_Z_THRESHOLD` |
|---|---|---|
| `helm/hopefx/values.yaml` — the chart ArgoCD syncs | `true` | `3.0` |
| `k8s/k8s-configmap.yaml` | `true` | — |
| `deployments/k8s/configmap.yaml` | `true` | — |
| `.env.example` | `true` | — |
| **`ml/inference_engine.py` code default** | **`false`** | **`4.0`** |

So the flag is recorded here as an owner decision (F146, and S4-04 in
`docs/HARDENING_BACKLOG.md`), but four of the five surfaces have already chosen.
What remains is a code default that disagrees with every deployment, and a
threshold that disagrees between the code and the deployed chart.

Two facts found while measuring this, neither of which is in the register's
framing of F146.

**`DRIFT_BLOCK` is the fourth of four conditions, not a switch.** For a drifted
model to be refused, all of these must hold: the stats file loads (else
`reason=no_training_stats`); coverage clears `DRIFT_MIN_COVERAGE` (else
`reason=insufficient_coverage`); the rolling buffer has filled
`DRIFT_WINDOW=50` scored predictions; and some feature's z exceeds the
threshold. Each of the first three returns `False`, which at the
`if drift and _DRIFT_BLOCK` site is indistinguishable from "measured, clean".
The engine is honest about this — `drift_guard_active()` and `drift_status()`
exist to separate the cases — but it means `DRIFT_BLOCK=true` on a guard whose
coverage is below floor is a control that cannot fire. The guard also cannot
fire for the first 49 predictions after any restart.

**A third flag rides on this decision.** `_MODEL_QUALITY_BLOCK`
(`ml/inference_engine.py:141`) is advisory by default, and its comment says so
explicitly: *"Advisory by default, exactly like `_DRIFT_BLOCK`. Wiring a gate in
must not silently change when this system declines to trade; that is the
owner's decision, and it is tracked with the DRIFT_BLOCK default."* Deciding
`DRIFT_BLOCK` without deciding `MODEL_QUALITY_BLOCK` leaves half the intent
unrecorded.

### What the guard measures today

Measured by execution on 2026-09-13, driving `ml/inference_engine.py` over the
committed daily series (`scripts/predict_offline.py`'s harness):

```
active True · reason ok · covered 176/193 (91.2%) · min_coverage 0.5
```

The guard is live — this is not a dead control. Both directions of the gate
were proven by injection: with `DRIFT_BLOCK=false` a drifted vector returned
`fallback=False` and a tradable signal; with `DRIFT_BLOCK=true` the same vector
returned `fallback=True`, `reason='feature_drift'`,
`model_version='drift_blocked'`. The gate works.

**And on clean data, with nothing injected, it already reads drift:
`drift_detected=True`, `z_max=19.168` — nearly 5× the 4.0 threshold.**

Ranking every feature by z against its training statistics explains why:

```
     z  feature                     live     train_mean   zeroed?
 19.17  frac_perm_ent_10          0.0000       0.8290     YES
 11.99  frac_perm_ent_5           0.0000       0.8774     YES
  9.89  inst_buy_pressure_20      0.0000       0.5521     YES
  6.80  inst_buy_pressure_10      0.0000       0.5492     YES
  6.04  frac_hfd_20               0.0000      -0.7710     YES
  4.83  breakout_low              1.0000       0.0412
  4.67  frac_dfa_40               0.0000       1.2381     YES
```

**12 of the 14 features over the threshold have a live value of exactly `0.0`.**
They are not drifted; they are missing and zero-filled. 103 of the 176 compared
features were exactly zero, and the predictor separately reported 93 of 193
columns zero-filled as absent.

The guard is therefore measuring *imputation* far more than *drift*. The
repository already knows imputing `0.0` is not neutral — S4-02 says so in terms
("zero is a *meaningful* value… a feed outage yields high-confidence trades
rather than abstention") — and already knows `DRIFT_BLOCK` defaults false
(S4-04). No document connects the two, and the connection is what decides this
ADR: **with `DRIFT_BLOCK=true`, a macro-feed outage stops all trading, reported
to the operator as `feature_drift`.** Two conditions with two different
remedies, arriving under one name.

These measurements are offline: the cached series ends 172 days ago and the
macro store is absent, which is itself why so much is imputed. A production run
with a healthy macro feed will impute less and read a lower `z_max`. The
mechanism does not depend on the magnitude — whenever features go missing in
production, they arrive as zeros and inflate the same z.

## Options considered

- **Flip the code default to `true`, and change nothing else.** Aligns the
  fifth surface with the four that already agree, and makes a deployment that
  forgets the key fail safe rather than trading a drifted model silently. It is
  one line. Costs: on the vector measured above it halts inference outright, and
  it makes every future feed outage a full trading halt labelled as drift. It
  also converts S4-04's dormant fail-closed handler — which sets
  `_drift_detected = True` when the drift computation throws — into a live
  refusal, which is the intent, but is a behaviour change nobody has watched.

- **Leave the code default `false`.** Costs: the disagreement stays, and it is
  the disagreement that bites. Any surface not built from the four templates —
  a container, a CI run, a developer's shell, a new chart — silently trades a
  drifted model, and `STALE_MODEL_BLOCK` (which defaults `true`) proves this
  codebase already knows which direction a safety default should point. This is
  the status quo and it is not defensible on its own; it is listed because
  "change nothing until imputation is separated" is a coherent position.

- **Separate imputation from drift, then flip the default.** Exclude
  zero-imputed features from the z computation, or report them as their own
  condition, so that `feature_drift` means distribution shift and a feed outage
  reports as a feed outage. Both then get the refusal they deserve, under their
  own names and with their own remedies. Costs: real work, and it needs the
  predictor to tell the guard which columns it filled — `live_inference.py`
  knows (it computes `missing` at the point of imputation) but does not
  currently expose it. This is the only option that makes the resulting block
  interpretable by an operator at 3am.

- **Raise `DRIFT_Z_THRESHOLD` until the imputed features stop tripping it.**
  Rejected, and recorded so nobody proposes it later. The z-scores are
  arithmetically correct; a threshold chosen to swallow them is tolerance
  widening to silence a real measurement, which `CLAUDE.md` forbids in terms.
  It would also have to sit above 19.17, which is far above any value that
  could still detect genuine drift.

## Decision

**Proposed: option three — separate imputation from drift, then default
`DRIFT_BLOCK=true`.** Awaiting the owner; this record is `proposed` and the
status line is the only thing that changes when it is accepted.

The sequencing is the substance of the recommendation. Flipping the flag first
is not a safe intermediate step: it takes a system that currently trades
through feed outages and turns it into one that halts on them without saying
so, and the operator's first encounter with that is an unexplained total stop.

Two riders, both of which need an answer in the same breath:

1. **`MODEL_QUALITY_BLOCK` goes the same way as `DRIFT_BLOCK`**, because the
   code comment already ties them and leaving it advisory reproduces this exact
   finding one flag over.
2. **`DRIFT_Z_THRESHOLD` stays at `4.0` in code, and the chart's `3.0` is
   brought to match — but not yet.** Choosing between 3.0 and 4.0 today means
   choosing a number against a signal that is mostly imputation. The threshold
   is worth deciding once the z it governs measures drift; until then the two
   values should at least be made to agree, and a disagreement between code and
   chart is its own defect regardless of which number wins.

## Consequences

Makes the guard's block interpretable. `feature_drift` will mean distribution
shift, and a feed outage will report as a feed outage — which are the two
conditions S4-02 and S4-04 describe separately and which the current z conflates.

Couples this decision to A8, and that coupling should be stated plainly:
`feature_scaler.pkl` and `stacking_ensemble.pkl` currently fail the sha256 in
`model_checksums.json` and do not load in production. `feature_stats.json` — the
drift guard's only reference distribution — was carried by the same commit
(`05efdbab`) that ML-LEAK identifies as having swept up artifacts unrelated to
its subject. Turning drift blocking on while the reference distribution's
provenance is unestablished means enforcing against a baseline nobody has
verified. **A8 should close before this ADR is accepted.**

Leaves the threshold open on purpose. That is a second decision, and recording
it as open is better than settling it now against a number this record has just
shown to be measuring something else.

Does nothing about the first 49 predictions after a restart, during which the
guard cannot fire whatever the flag says. That window is inherent to a rolling
comparison and is recorded here so it is not rediscovered as a defect.

## Evidence

Every figure in this record is reproducible. The report was written for this
decision and stays useful after it:

```bash
python scripts/drift_guard_report.py            # flags, liveness, and the z split
python scripts/drift_guard_report.py --json     # same, machine-readable
python scripts/correction_register.py --id F146 # the tracked status
```

Measured 2026-09-13 on the committed daily series (1,567 bars, ends 172 days
ago), against `ml/saved_models/feature_stats.json`:

```
DRIFT_BLOCK False · MODEL_QUALITY_BLOCK False · STALE_MODEL_BLOCK True
DRIFT_Z_THRESHOLD 4.0 · DRIFT_MIN_COVERAGE 0.5 · DRIFT_WINDOW 50

active True · reason ok · coverage 176/193 (91.2%), floor 50%

compared 176 · zero-filled 103 · over z=4.0: 14
  of which zero-filled  12   <- absent data, not drift
  of which drifted       2
```

The gate itself was proven to work in both directions by injection — shifting
every training mean by 1000σ with a filled buffer, then driving `predict()`:

| `DRIFT_BLOCK` | result |
|---|---|
| `false` | `fallback=False`, tradable signal, drift logged only |
| `true` | `fallback=True`, `reason='feature_drift'`, `model_version='drift_blocked'` |

So this ADR is not about a dead control. The guard runs, and the gate refuses
when told to. It is about what the guard is measuring when it does.

Two things were checked and ruled out, recorded so the next reader does not
repeat them. The live vector and the training statistics are both in **raw**
feature space — `write_feature_stats(X_cv)` is called on the CV training matrix
(`ml/train_advanced.py:1485`) and `last_scored_features` is captured before the
pipeline scales (`ml/live_inference.py:471`) — so the comparison is sound and
the inflated z is not a scaled-versus-raw mismatch. And `ml/saved_models/` was
clean in `git status` throughout, so the artifacts read here are the committed
ones and not an ML-LEAK residue.
