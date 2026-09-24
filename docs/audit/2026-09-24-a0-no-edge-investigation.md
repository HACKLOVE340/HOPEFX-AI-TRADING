# A0: why the dry-run retrain has no edge (investigation, 2026-09-24)

> **Status: research only.** Nothing under `ml/saved_models/` or `ml/rl_models/`
> was modified. The sha256 of every `*.pkl` and `*.json` there, in this worktree
> and in the main checkout, matches the pre-run snapshot (checked with `diff`).
> All scratch output is under `/tmp/a0-investigate/`. No defect found here has
> been fixed. Each one is described with a file, a line, a repro and the
> expected versus actual result.
>
> **Context:** `docs/ai/MASTER_OUTSTANDING.md` §A0 and
> `docs/audit/plans/2026-09-24-a0-model-retrain.md` (dry-run results).

## The answer in one paragraph

**The labels are correct.** 0 of 1,190 differ from an independent recomputation,
and their correlation with the forward return is +0.779, so they are not
inverted. **0.387 is what an uninformative model scores on this data.** The
out-of-sample window went up 65.5% of the time, while the training window went up
50.2% of the time. The model predicted "down" on 84.5% of out-of-sample bars. A
classifier with no skill and that bias scores 0.392, against the 0.387 observed.
It predicts "down" because features it learned in the range-bound 2021–24 market
(price levels, distance from the 200-day moving average, 60-day momentum) sit at
extremes throughout the 2024–26 rally. **There is no ranking skill underneath:**
AUC is 0.499 out of sample and 0.48 walk-forward. The same model trained on
shuffled labels does as well or better (acc 0.485, AUC 0.507). So do tiny
baselines with five features.

**The incumbent's 0.5734 is not an edge either.** It reproduces exactly from
the committed artifact (0.5734, AUC 0.582). But on the same window,
**always-predict-up scores 0.5516**, and the window comes from `XAUUSD_50Y.csv`.
In 2016–26, 37% of that file's bars are synthetic: flat bars priced at their
**month's mean close**, which carries future information. Scored on clean
`XAUUSD_40Y.csv` features, the same artifact gets **0.534 against always-up
0.558 (AUC 0.520)**. **Recent data alone would not produce an edge.** Buy the
feed to satisfy the age gate, not in the expectation that the model improves.

## Environment and reproduction

- Python 3.12.3, xgboost 3.4.1, scikit-learn 1.9.1, pandas 3.0.6
  (`/tmp/a0-venv312`, the plan's Task 2 venv). yfinance was import-blocked with
  `PYTHONPATH=/tmp/a0-noyf`, so no `GC=F` path could run. Macro data came from
  `data/macro/*.csv` (1,256 rows, 2021-03-29 → 2026-03-25).
- HEAD at the start: `10d54a12` (after `git merge claude/add-new-skills-lys862`).
- The scripts below are scratch files under `/tmp/a0-investigate/`. None of them
  calls a function that writes. `ml.train_advanced.MODEL_DIR` is also
  redirected to `/tmp/a0-investigate/model_dir`, which stayed empty.

| Script | What it does |
|---|---|
| `build.py <tag>` | Rebuilds the feature frame exactly as `train_advanced.main` does (`fetch_gold_ohlcv` → `fetch_macro` → `build_extended_features`) and pickles it. Tags: `dry` (the dry run: 40Y, 6y, macro, filtered), `dry_nomacro`, `dry_unfiltered`, `inc50` (the incumbent's recipe: 50Y, 50y, no macro, with the plausibility gate bypassed *for measurement only*), `clean40_26y`, `clamped_26y` |
| `labels.py` | Q1: independent label recompute, class balance per split, base-rate arithmetic |
| `features.py dry` | Q2: constant and near-constant features, per-group liveness, train→OOS range extrapolation, per-feature contributions to the OOS margin |
| `models.py <tag> <oos_years>` | Q3/Q5: the production OOS model (verbatim hyper-parameters), the CV model, tiny baselines, rule baselines, and a shuffled-label null, all on the same walk-forward split and OOS window |
| `topk.py` | Q3: top-k features selected on TRAIN-only univariate AUC, then a regularised logit, scored OOS with a bootstrap CI |
| `stability.py` | Per-feature AUC in train versus OOS; the incumbent's binomial test against the right null |
| `incumbent.py` | Q4: loads a `/tmp` **copy** of `advanced_oos.pkl` (sha256 `dc7454d8…`, verified) in memory and predicts only |
| `variants.py <tag> <oos_years>` | Hypothesis tests: drop price-level features, drop dead features, use longer clean history |
| `fifty_flat.py`, `defects.py` | Data-quality and code-defect reproductions |

`build.py dry` reproduces the dry run exactly: 1,190 rows × 222 features, class
balance `{1: 673, 0: 517}`. Refitting the production model in memory gives the
same **OOS acc 0.387, AUC 0.499** as `/tmp/a0-dryrun2.log`.

---

## Q1. Labels: correct, and the sub-0.5 accuracy is base-rate arithmetic

The target is `ml/advanced_features.py:556 build_filtered_target`. The entry is
`open[t+1]` and the exit is `close[t+5]`. Label 1 means the return is above 0,
and bars that move less than 0.25×ATR14 are dropped.

```
$ /tmp/a0-venv312/bin/python /tmp/a0-investigate/labels.py
independent label recompute: rows compared 1190 mismatches 0
corr(label, fwd ret) = 0.779 (positive => not inverted)
corr(label, same-bar return) = -0.033                 # no same-bar leak
corr(label, next-bar open->close) = 0.297             # overlaps the window: expected
fraction of 5-bar windows skipped by the ATR filter: 0.093
class balance per split:
  all                          n=1190  P(up)=0.566  2020-12-22..2026-03-18
  train/CV                     n= 709  P(up)=0.502  2020-12-22..2024-02-13
  final-model train (80%)      n= 567  P(up)=0.519
  final-model holdout (20%)    n= 142  P(up)=0.437  2023-07-10..2024-02-13
  OOS                          n= 476  P(up)=0.655  2024-02-23..2026-03-18
walk-forward test folds: P(up) ranges 0.397 .. 0.641 (8 folds of 78)
OOS P(up)=0.655; dry-run predicted DOWN on 0.847 of OOS bars
expected accuracy of an UNINFORMATIVE classifier with that predict-down rate: 0.392  (observed 0.387)
```

- There is no off-by-one, no look-ahead and no sign inversion. The purge gap
  (`TimeSeriesSplit(gap=5)`) and the 5-bar train/OOS purge are both present.
- **Always-up scores 0.655 out of sample.** Always-majority-of-train is also
  "up" (0.502), so it scores 0.655 too. Both beat 0.387 by 27 points. Each
  walk-forward fold's always-up accuracy ranges from 0.397 to 0.641. A
  fold-mean accuracy of 0.474 ± 0.066 is well within the noise of these
  fold-to-fold swings in the base rate.

## Q2. Features: 30 of 222 are dead, and the rest carry no transferable signal

```
$ /tmp/a0-venv312/bin/python /tmp/a0-investigate/features.py dry
constant (nunique<=1): 22   near-constant (one value on >=95% of rows): 8   >=50% exactly zero: 64
constant: cot_geo_score20 cot_geopolitical im_gold_oil_div im_gold_spx_div macro_copper_ret macro_oil_ret
          macro_spx_ret macro_spx_z20 macro_usdcny_ret macro_wgc_{central_bank_chg,demand_score,etf_flow,
          etf_flow_z4,investment_chg,jewellery_chg,total_demand_chg} oi_chg oi_price_confirm oi_z20
          ri_regime_mom ri_trend_vol_confirm ri_vol_adj_mom
live features: 192; rows per live feature in train/CV: 3.7
rows before macro CSV start (<2021-03-29): 58; macro-ish cols all-zero on those rows: 39 of 50
```

| Group | n | dead | near-dead | live | note |
|---|---:|---:|---:|---:|---|
| `macro_` | 29 | 12 | 1 | 16 | SPX, oil, copper, USDCNY and all 7 WGC series have no offline source, so they are zero-filled |
| `oi_` | 3 | 3 | 0 | 0 | No open-interest source offline |
| `cot_` | 9 | 2 | 1 | 6 | The geopolitical proxies are constant |
| `im_` | 5 | 2 | 0 | 3 | The gold/SPX and gold/oil divergences are constant |
| `ri_` | 26 | 3 | 4 | 19 | **3 are constant by construction; see D3** |
| `inst_` | 39 | 0 | 1 | 38 | **Includes 3 raw price levels; see D4** |
| all others | 111 | 0 | 2 | 109 | Price, volatility, momentum, calendar, order-flow proxies |

**Why the model says "down" out of sample.** Summing the XGB per-feature
contributions (`pred_contribs`) for the walk-forward model gives a mean OOS
margin of **−1.643 log-odds**. On its own training rows the mean margin is
+0.011. The largest downward pushes:

```
inst_poc -0.355  inst_cum_delta_50 -0.234  dist_to_swing_high -0.162  dist_ma_200 -0.145  mom_60 -0.136
inst_poc     train mean 1844  OOS mean 3034  (a raw PRICE LEVEL; 95.8% of OOS rows lie outside the train range)
dist_ma_200  train mean 0.92  OOS mean 9.99   corr(label) train -0.158
mom_60       train mean 0.008 OOS mean 0.107  corr(label) train -0.114
```

In the 2021–24 training window, gold was range-bound. High price, a large
distance from the 200-day MA and strong 60-day momentum all went with the next
5 days being *down*. In the 2024–26 rally, every bar looks like that, so the
model calls "down" almost everywhere. Removing the three price-level features
alone does not fix it: `variants.py dry 2` gives OOS acc 0.397 and P(pred=0)
0.809.

**Per-feature stability** (`stability.py`): 22 live features have a train
univariate |AUC − 0.5| ≥ 0.05. Only 8 keep that sign and strength out of
sample, and 7 flip sign. Across all 200 live features, the correlation between
train and OOS univariate AUC is **0.079**. What the model learns in training
does not carry over to OOS.

## Q3. Data volume and overfitting: the baselines are no better, so this is not mainly overfit

Same split, same OOS window (`models.py dry 2`; the OOS SE of accuracy is 0.023
and of AUC about 0.046):

| Model | WF acc | WF AUC | OOS acc | OOS AUC | P(pred=0) |
|---|---:|---:|---:|---:|---:|
| Production calibrated XGB, 222 features | 0.500 ± 0.071 | 0.488 | **0.387** | **0.499** | 0.845 |
| CV XGB (no calibration), 222 features | 0.474 ± 0.066 | 0.483 | 0.368 | 0.489 | 0.868 |
| Logit C=0.1, 5 simple features (ret 1/5/20, vol20, dist MA50) | 0.521 ± 0.121 | 0.586 | 0.475 | 0.489 | 0.529 |
| XGB depth 2 × 100, same 5 features | 0.492 ± 0.097 | 0.536 | 0.485 | 0.487 | 0.536 |
| Logit C=0.1, 222 features | 0.486 ± 0.041 | 0.528 | 0.372 | 0.531 | 0.918 |
| Always up | — | — | **0.655** | — | 0 |
| Sign of the 20-day return | — | — | 0.544 | — | 0.208 |
| **Production model on SHUFFLED train labels** (5 seeds) | — | — | 0.485 ± 0.050 | 0.507 ± 0.026 | 0.575 |

Top-k features chosen on train-only AUC, then a logit (`topk.py`): OOS AUC
ranges from 0.519 to 0.540 for k = 3 to 200, and **every bootstrap 95% CI
includes 0.5**. At k ≤ 10 the model predicts "down" on 100% of OOS bars,
because the train-selected leaders are `inst_poc`, `inst_vah` and
`dist_ma_200`. The iid bootstrap is also optimistic here, because 5-bar labels
overlap.

**Conclusion:** there are 709 training rows for 192 live features, so the model
is over-parameterised. But reducing it to 3–5 features gains nothing out of
sample. The 5-year daily window has no measurable 5-bar directional signal on
these features, and the out-of-sample prior moved from 50% to 65% up.

**Longer clean history is the only lever that moved AUC.** Here `clamped_26y`
is `XAUUSD_40Y_clamped.csv`, 2000–2026, with an 8-year OOS window 2017-03 →
2026-03 (n = 2,016, AUC SE ≈ 0.013–0.022):

| Model | WF acc | WF AUC | OOS acc | OOS AUC | P(pred=0) |
|---|---:|---:|---:|---:|---:|
| Production calibrated XGB, 193 features | 0.535 | 0.554 | 0.565 | **0.561** | **0.000** |
| Same, minus price levels and dead features | 0.535 | 0.544 | 0.565 | 0.573 | 0.000 |
| CV XGB (no calibration) | 0.539 | 0.550 | 0.533 | 0.578 | 0.613 |
| Logit, 5 simple features | 0.549 | 0.521 | 0.564 | 0.493 | 0.074 |
| Always up | — | — | **0.565** | — | 0 |
| Shuffled-label null (5 seeds) | — | — | 0.563 ± 0.003 | 0.509 ± 0.023 | 0.021 |

With 26 years of clean data there is a weak ranking signal, AUC 0.56–0.58
against a null of 0.51 ± 0.02. But the production model then predicts "up" on
every bar, so its **accuracy equals always-up**. That is the incumbent's
pattern (Q4).

## Q4. The incumbent: reproducible, but measured on leaky data and never above base rate

`incumbent.py` loads a `/tmp` copy of the committed `advanced_oos.pkl` in memory
(a Pipeline with 193 `feature_names_in_`; every feature is present in the
rebuilt frame, and none is missing).

```
recorded window: last 2016 rows of 50Y frame     2016-08-17..2026-03-25 acc=0.5734 AUC=0.582 always-up=0.5516 P(pred=1)=0.768
dry-run OOS window, 50Y features   (n=432)       2024-02-23..2026-03-18 acc=0.5903 AUC=0.602 always-up=0.6435
dry-run OOS window, CLEAN 40Y features (n=476)   2024-02-23..2026-03-18 acc=0.5252 AUC=0.557 always-up=0.6555
recorded window, CLEAN 40Y features (n=2146)     2016-08-17..2026-03-18 acc=0.5340 AUC=0.520 always-up=0.5578
binomial, k=1156/2016: p vs 0.5 = 2.3e-11 ; p vs the window's always-up rate 0.5516 = 0.026
```

1. **The 0.5734 is reproducible and honest about its method.** The committed
   artifact, the 50Y file and `build_extended_features(no macro, h=5,
   filtered)` give exactly 0.5734 / AUC 0.582 on the recorded window. There is
   no train/OOS leakage: the incumbent's training rows all predate
   2016-08-17. Retraining the recipe today (`variants.py inc50 8`) gives OOS acc
   0.553 against always-up 0.552, AUC 0.569. It is not byte-identical, because
   the 50-year cutoff moved 3 months (7,960 rows now against 7,994 then).
2. **The null hypothesis was wrong.** `ml/train_advanced.py:1126` tests
   against p = 0.5. The window's base rate is 0.5516, and against that the
   incumbent is +2.2 points, p = 0.026, on the leaky data.
3. **The data was leaky.** `fifty_flat.py`, on `XAUUSD_50Y.csv` for 2016-08 →
   2026-03:

   ```
   50Y rows 2517, 40Y rows 2425; 50Y-only dates 92; flat o=h=l=c rows in 50Y 931 (696 are real bars in 40Y)
   months with flat bars: 114; median |flat value - that month's MEAN close| = 0.091%
                                (vs month's last close 1.403%, previous month's last close 1.779%)
   flat bars: sign(flat value - previous real close) agrees with sign(next 5-bar real move): 0.651 (n=929)
   ```

   Example from June 2025: 3, 5, 9 and 11 June are all `3352.66`, with O=H=L=C
   and zero volume, while the real closes were 3350.20, 3350.70, 3332.10 and
   3321.30. A bar priced at the month's mean close embeds that month's future.
   Those bars change both the features and the labels. The existing
   `_assert_price_history_is_plausible` looks only for >20% spikes, so it
   accepts this window (D2).
4. **On clean data the incumbent is below always-up**: 0.534 against 0.558 on
   its own window, and 0.525 against 0.655 on the dry run's window. It keeps a
   weak AUC of 0.52–0.56, about what a clean retrain gets (Q3). **So the
   candidate and the incumbent are not "0.387 against 0.573". Neither beats
   always-up on clean data.**
5. **The registry metadata for these bytes contradicts itself.** Four entries
   share sha256 `dc7454d8…`: `advanced_oos_v1`, `advanced_oos_v2`,
   `xgb_horizon5_v1` and `xgb_horizon5_v3`. They record `oos_auc` values of
   0.7108, 0.5427, 0.5427 and 0.582. `advanced_oos_v1`'s notes say "OOS
   accuracy=66.35%" while its field says 0.5734. `advanced_oos_v2` and
   `xgb_horizon5_v1` say `macro_features: True`, but their notes say
   "Macro=False". All three older entries say `feature_count 222` while the
   bytes have 193. `xgb_horizon5_v1` and `xgb_horizon5_v3` say `symbol:
   GC=F`, but v3's own notes say it was trained on `XAUUSD_50Y.csv`. **Only
   `xgb_horizon5_v3`'s metrics reproduce from the bytes.**

## Q5. Other defects found (not fixed)

| ID | Where | Defect | Repro | Expected | Actual |
|---|---|---|---|---|---|
| **D1** | `ml/advanced_features.py:669-674` | The unfiltered target labels the last `horizon` bars as **0**. `NaN > 0` is `False`, and line 674 (`y_raw[y_raw.isna()] = np.nan`) is a no-op after `.astype(float)` of a bool | `defects.py`: a strictly rising synthetic series, `use_filtered_target=False`, horizon 5 | Every knowable label is 1, and the last 5 are dropped | `{1: 335, 0: 5}`, last labels `[1,0,0,0,0,0]`. On real data (`dry_unfiltered`) the last label is dated 2026-03-25, the last bar |
| **D2** | `ml/train_advanced.py:100-159, 189-192` | `fetch_gold_ohlcv` tries `XAUUSD_50Y.csv` **first**. The plausibility gate counts only >20% spikes, so it **accepts** the 50Y file for any window of 10 years or less, although 37% of those bars are synthetic month-mean bars (Q4.3). `train_advanced.py --use-cached --years 6` without `--cached-csv` would silently train on leaky data | `defects.py` | Refused | `50Y last 10y: 2607 bars, flat 36.9% -> ACCEPTED`; `last 6y: 1564 bars, flat 36.3% -> ACCEPTED` |
| **D3** | `ml/features_extended.py:499-515` (cause: `:904`) | `ri_regime_mom`, `ri_vol_adj_mom` and `ri_trend_vol_confirm` are **constant 0.0 by construction**. `build_extended_features` runs the extended layers on a fresh copy of raw OHLCV (`d = ohlcv.copy()`, :904), so `mom_20`, `rvol_20`, `regime_trend` and `adx_14`, which are base-builder columns, never exist there, and the `else` branch always runs | `features.py dry` | Varying interaction terms | All three are `nunique == 1` |
| **D4** | `ml/features_extended.py:664-667` against the docstrings at `:888` and `ml/advanced_features.py:623` | `inst_poc`, `inst_vah` and `inst_val` are **raw price levels** (\|corr with close\| > 0.9), although both builders promise "all stationary". Out of sample, 94–96% of their values lie outside the training range. They are the #1 train-selected features and the #1 driver of the OOS "down" bias | `features.py dry`, `variants.py dry 2` | Normalised distances (`inst_dist_poc` etc. already exist) | Raw levels are fed to the model |
| **D5** | `ml/train_advanced.py:1126`, `:511`, `:525` | Significance is tested against **0.5**, not the base rate. The OOS gate is a binomial test on accuracy against 0.5, and the walk-forward test is a t-test against 0.5. On a window that is 55–65% up, always-up "passes" | `stability.py` | p against the base rate | 0.5734 gets p = 2.3e-11 against 0.5 and p = 0.026 against 0.5516. Always-up would get p ≈ 0 against 0.5 on the dry run's OOS |
| **D6** | `ml/train_advanced.py:1417` | `--oos-years N` becomes `N×252` **filtered rows**, not calendar years. The filtered target drops ~9% of bars, and there is a cap at 40% | registry `xgb_horizon5_v3`: "8.0 years" is recorded as 2016-08-17 → 2026-03-25 | 8 calendar years | 9.6 years. The dry run's "2 years" was capped at 476 rows |
| **D7** | `ml/saved_models/registry.json` | Four entries with one sha256 carry contradictory metrics (Q4.5) | `python3 -c "import json;…"`, see Q4 | One set of metrics per sha256, reproducible | 4 different `oos_auc` values for the same bytes |
| **D8** | offline macro | 12 `macro_*`, 2 `im_*` and 3 `oi_*` columns are constant offline. For the first 58 rows (before 2021-03-29) 39 of 50 macro-ish columns are zero-filled | `features.py dry` | Dropped or marked missing | Zero-filled and fed to the model (ADR 0019's drift z is the same phenomenon) |

Checked and **not** a defect: there is no calibration inversion. The isotonic
layer keeps the ranking, since the calibrated and uncalibrated OOS AUCs are
0.499 and 0.489. The down bias comes from the base model. The mean OOS
probability is 0.23 for the uncalibrated CV model and 0.42 for the calibrated
production model. `scale_pos_weight` is about 1 on a
50/50 training set, so it is not the cause. Each `scale_pos_weight` is
recomputed from its own training labels, so it does not leak.

---

## Would recent data fix it?

**No, not on its own.** Six more months adds about 125 rows to a 1,190-row
frame. On the 5-year window, AUC is 0.50 with a CI of about ±0.05, and no
baseline or feature subset beats that. The best result measured anywhere is 26
clean years: AUC 0.56–0.58, with accuracy exactly equal to always-up.
**History length helps a little; recency does not create signal.** The data
feed is still required for the age gate, which is the A0 blocker. But the owner
should expect the retrain to land near always-up accuracy and AUC ≈ 0.55, not
near the recorded 0.5734, which was itself only base rate plus leakage.

## Recommended fixes, in order (each with the test that proves it)

1. **Make "better than always-up" the promotion bar.** Test OOS accuracy with
   a binomial test against the OOS majority rate, and gate on the lower bound of
   a block-bootstrap AUC CI being above 0.5. Report a shuffled-label null next
   to it. (D5.)
   *Test:* `tests/unit/test_oos_gate_beats_base_rate.py`. Build a synthetic OOS
   that is 65% up and pass the gate (a) an always-up predictor and (b) a random
   predictor biased the same way. Both must be refused. **It fails today**,
   because `binomtest(k, n, p=0.5)` passes (a).
2. **Retire 0.5734 as the comparison bar.** Record the incumbent's clean-data
   score (0.534 against always-up 0.558) and correct or annotate the three
   registry entries whose metrics do not describe the bytes (D7). Owner action.
   *Test:* `tests/unit/test_active_model_metrics_reproduce.py`. Predict with the
   active artifact on the data file its entry names. The recorded `oos_accuracy`
   and `oos_auc` must reproduce to within 1e-3, and every entry sharing that
   sha256 must carry the same metrics. It fails today on
   `advanced_oos_v1`/`v2`/`xgb_horizon5_v1`.
3. **Stop the 50Y file reaching training.** Remove it from the default
   candidate list at `train_advanced.py:189-192`, and teach
   `_assert_price_history_is_plausible` to detect synthetic bars: the fraction
   of O=H=L=C rows, and flat bars equal to a period mean. (D2; the same applies
   to `scripts/retrain_horizon5.py --use-cached`.)
   *Test:* `_assert_price_history_is_plausible(last 6y of XAUUSD_50Y.csv)`
   must raise `CorruptTrainingDataError`. **It passes (ACCEPTED) today.** The
   40Y file for 2020+ must still be accepted (it has 61 flat bars, 1 at a
   monthly mean).
4. **Retrain on the long clean series, not the 6-year one.** Use
   `--cached-csv data/XAUUSD_40Y_clamped.csv --years 26`, extended with the
   owner's post-2026-03-25 bars. Pre-register the acceptance rule (#1) before
   looking at the result. *Evidence it helps:* AUC 0.561 against 0.499 (Q3).
5. **Fix the feature defects.** Drop or normalise `inst_poc/vah/val` (D4).
   Compute the `ri_*` interactions on the merged frame, not raw OHLCV (D3).
   Drop features that are constant on the training frame before fitting, and
   record that list in the artifact metadata (D8).
   *Tests:* on a synthetic trending series, `build_extended_features` returns
   no column with |corr(close)| > 0.9, and `ri_vol_adj_mom.nunique() > 1`.
   Both fail today.
6. **Unfiltered-label fix (D1).** Keep the NaN where `future_ret` is NaN.
   *Test:* on a strictly rising synthetic series with
   `use_filtered_target=False`, `y` has no zeros and ends `horizon` bars before
   the data. It fails today (`{1: 335, 0: 5}`).
7. **Define `--oos-years` by date (D6).** Split at
   `last_date − N years`, not at N×252 filtered rows.
   *Test:* `--oos-years 2` on the dry frame gives an OOS window that starts
   within 5 days of `2026-03-25 − 2y`.
8. **Report accuracy with prior shift in view.** Report balanced accuracy and
   the always-up/always-down baselines in every training report. A model whose
   OOS positive rate differs from the label rate by more than 20 points should
   be flagged in the report. This is not a fix for edge; it stops a 0.387 from
   being read as a "sign inversion".

None of these fixes produces an edge. Items 1–3 stop the platform from
measuring one that is not there. Item 4 is the only one measured to move AUC,
and then only to about 0.56.
