# A0: a wider search for direction (research spike 2, 2026-09-25)

> **Status: research only.** No production module changed. Nothing was written
> under `ml/saved_models/` or `ml/rl_models/`, and no registry was touched.
> The one kept script is `scripts/research/a0_direction_research2.py`, which
> passes ruff. It imports the first spike's loader, features, purged
> walk-forward, block bootstrap, strategy accounting and deflated Sharpe
> unchanged, so both spikes share one protocol. It writes only to `--out`.
> Scratch output went to `/tmp/a0-research2/`.
>
> **Context:** `docs/audit/2026-09-25-a0-target-research.md` (spike 1: 52
> tests, no directional skill, EWMA volatility the only signal) and
> `docs/ai/MASTER_OUTSTANDING.md` §A0. The owner's instruction was: "research,
> find a way to predict". Spike 1 was not enough, so this spike tests six
> **different** families. It does not re-run anything spike 1 ran.

## The answer in one paragraph

**Nothing passes.** 64 new tests were run in six families, making 116 with
spike 1's 52. No new test clears all of Bonferroni at m = 116, the repo's
promotion rule (accuracy above always-majority and an AUC bound above 0.5)
and replication on 2010–2018. The families were regime-gated direction,
meta-labelling of the repo's strategies, calendar effects, cross-asset
lead-lag, tail and asymmetry targets, and a regularised ensemble of all of
them.

**One lead is real enough to name: short-horizon reversal.** Gold's daily
close-to-close returns have a small negative lag-1 autocorrelation: −0.027 on
2018–26 and −0.038 on 2010–18, with flat bars excluded as a cause. A 1-day
reversal score ranks tomorrow's direction at AUC 0.537 [0.513, 0.564], and
0.540 [0.513, 0.568] on the earlier window. The pre-registered ensemble scores
0.542, with p = 5.3e-4 and p Bonferroni 0.061, and it gets that skill from the
same `ret_1` term. **It does not survive the protocol, for three reasons:**

1. It fails the repo rule. Accuracy stays below always-up, 0.528 against
   0.544, because the score calls "down" on about half of all days in a
   rising market.
2. It is post-hoc. The one pre-registered test that carries it misses
   correction narrowly.
3. **It disappears under the protocol's one-bar execution lag.** Against the
   return the platform can actually trade, r(t+2), the AUC is 0.500. Even
   filling at the same close as the signal, which breaks the protocol, a daily
   long/short earns Sharpe −0.07 at 5 bp. It earns +0.72 at 0 bp, with a CI
   that crosses 0.

**It is a data-and-execution question, not a modelling one.** The
recommendation is unchanged: no directional weight goes into the ensemble.
The data list at the end names the data that would let the reversal lead, and the families
the literature rates highest, be tested properly.

## Method

The protocol is spike 1's, reused by import. Only the families are new.

| Choice | What was done |
|---|---|
| Data | `ml.train_advanced.fetch_gold_ohlcv(..., cached_csv="data/XAUUSD_40Y.csv", allow_download=False)`: 6,415 daily bars from 2000-08-30 to 2026-03-25. Both A0 gates pass (12.7% flat overall, 6.0% in the OOS window). **Close only.** Macro: `data/macro/*.csv`, 2021-03-29 → 2026-03-25 (see *Data-quality findings*). |
| Look-ahead proof | `/tmp/a0-research2/lookahead_check.py` rescales and adds noise to every close after row k, for k = 1,000, 4,000 and 6,000. Every new feature at rows ≤ k changes by **0**, and so does its NaN pattern. This covers the regime and asymmetry features and the expanding calendar means. Every triple-barrier event resolved by row k is identical. A one-day position decided on bar k earns exactly r(k+2). The same-close upper bound earns r(k+1). |
| OOS window | 2018-03-26 → 2026-03-25, defined by date. Fitted models are refit at the start of each OOS year on all earlier rows, with the last h rows purged. Meta-labelling purges any training event whose barrier outcome is not known before the fold starts. Cross-asset models are fitted on 2021-03 → 2023-03 and tested on 2023-03-26 → 2026-03-25. |
| Rules | Every rule's sign was fixed before the data was seen: reversal is −move, momentum is +move, and dollar and yields are negative for gold. The test is one-sided, H1: AUC > 0.5. **No sign was flipped after looking.** |
| Baselines | Classification: AUC 0.5, plus the repo rule `ml.oos_skill.skill_over_base_rate_check` (accuracy above always-majority on the same rows, and the 95% AUC lower bound above 0.5). Strategies: buy-and-hold for long/flat and overlays, zero for long/short. Costs are 5 bp per unit of turnover. A position decided at close t fills at close t+1 and earns r(t+2). Calendar: the training-mean daily return. |
| Uncertainty | Moving-block bootstrap with 1,000 draws and seed 42. The block is max(h, 20) rows, or 63 days for strategies. |
| Multiple comparisons | **m = 116**: spike 1's 52 plus 64 new, with every variant, diagnostic and post-hoc test counted. Bonferroni α = 0.05/116 = 0.00043. The deflated Sharpe covers **36 strategy trials**: spike 1's 16, re-run in the same process with `--prior-strategies`, plus 20 new. |
| Replication | The same code on data truncated before 2018-03-26, giving an OOS window of 2010-03-24 → 2018-03-23. A pass must show a 95% CI clearing the null in the same direction there too. The cross-asset family cannot be replicated: no macro series offline starts before 2021-03-29. |
| Post-hoc | Five tests marked **POST-HOC** were added after the pre-registered ensemble showed h=1 skill, to find where it came from. They are counted in m like everything else, and they are not eligible to pass. |

## Results

### Summary by family

| Family | New tests | Pass | Best result (main window) | Replicates? | Verdict |
|---|---:|---:|---|---|---|
| 6. Regime-gated direction (reversal after k-σ, momentum by vol regime, variance-ratio gate, regime-split logit, 4 rules, 5 post-hoc) | 26 | **0** | post-hoc 1-day reversal AUC 0.537 [0.513, 0.564] | yes as ranking (0.540), **no** as a tradable return (r(t+2) AUC 0.500 and 0.493) | No regime makes direction predictable at 5–20 days. Reversal after 2σ/3σ days is **not** there (h=1 AUC 0.464 and 0.521). Momentum in the high-vol or trending regime scores **below** 0.5 at h=5 in both windows (0.446 and 0.446; 0.402 and 0.450). That is the reversal effect again, with the a-priori sign wrong. |
| 7. Meta-labelling of the 8 repo strategies (triple barrier, 10 bars, ±1σ√10) | 7 | **0** | logit P(win) AUC 0.473 [0.403, 0.530] | no (0.490) | 476 OOS entries, with a 56% win rate against 59% in training. The secondary model cannot tell winners from losers, and filtering **lowers** Sharpe relative to the unfiltered primary (−0.25). The primary portfolio trails buy-and-hold by −0.54 Sharpe. |
| 8. Calendar (day-of-week, turn-of-month, month-of-year, US-holiday proximity) | 8 | **0** | holiday R² +0.0015 [−0.002, +0.004] | no | The historical patterns do not persist. The pre-2018 Friday premium (+11 bp a day) fell to +2.8 bp. The day-of-week forecast is **worse** than the mean (R² −0.003, CI below 0). The long/flat rules pay about 5%/yr in turnover costs and lose 0.1–1.4 of Sharpe. |
| 9. Cross-asset lead-lag (DXY, US10Y, US2Y, VIX, GLD; 2021+) | 9 | **0** | lagged DXY change AUC 0.502 | n/a, no pre-2021 data | Every lagged macro change is at AUC 0.49–0.50. The macro logit scores 0.504 at h=1 and 0.447 at h=5. The same-day links are strong (gold vs DXY −0.38, vs 10y −0.24), but **none of them leads**. |
| 10. Asymmetric and tail targets (sign of a large move; up-tail minus down-tail score) | 6 | **0** | sign given a large move, h=5, asym logit, AUC 0.573 [0.493, 0.690] (diagnostic, selected on the future) | no (0.481) | The sign of a large move is still unpredictable. The tradable tail score is **significantly inverted** in both windows (0.467 and 0.466), because a big up day raises the model's up-tail probability and tomorrow reverses. This is the same reversal. |
| 11. Ensemble of all weak signals (33 signals; L2 and L1 logits; plus macro on 2023–26) | 8 | **0** | ensemble + macro h=1 AUC 0.571 [0.536, 0.613], p Bonferroni **0.022** | n/a | It clears Bonferroni **on AUC alone**, but it **fails the repo rule** (accuracy 0.551 against majority 0.562). Macro adds **nothing**: ΔAUC −0.007 [−0.030, +0.016] against the same ensemble without macro columns, which alone scores 0.578. Its skill is the 1-day reversal. The ensemble at h=1 on the full window scores 0.542 (p Bonferroni 0.061), and 0.527 [0.505, 0.551] on 2010–18. At h=5 it scores 0.526, with no pass. |

### Full ranked table

Main window: OOS 2018-03-26 → 2026-03-25, except family 9 and the macro
ensemble (2021-04 → 2026-03 for rules, 2023-03 → 2026-03 for fitted models).
m = 116. "Fails correction" means the CI clears the null but the Bonferroni p
is 0.05 or higher, or the repo rule fails. "DSR" is the deflated Sharpe over
36 trials, with an expected maximum null Sharpe of 0.94 per year.

| # | Candidate | Fam | Metric | Value | Baseline | 95% CI | p (1-sided) | p Bonf (m=116) | 2010-18 replication | Pass |
|---:|---|---|---|---:|---|---|---:|---:|---|---|
| 1 | ensemble + macro L2 logit (44), h=1, 2023-26 | 11 | AUC | +0.571 | AUC 0.5; acc 0.551 vs majority 0.562 | [+0.536, +0.613] | 1.9e-04 | 0.022 | n/a (no pre-2021 data) | **passes Bonferroni, fails repo rule**; macro adds nothing (row 37) |
| 2 | ensemble L2 logit (33 signals), h=1 | 11 | AUC | +0.542 | AUC 0.5; acc 0.543 vs majority 0.544 | [+0.519, +0.569] | 5.3e-04 | 0.061 | +0.527 [+0.505, +0.551] | fails correction (repo rule fails) |
| 3 | POST-HOC 1-day reversal -ret_1, all days, h=1 | 6 | AUC | +0.537 | AUC 0.5; acc 0.528 vs majority 0.544 | [+0.513, +0.564] | 0.002 | 0.233 | +0.540 [+0.513, +0.568] | fails correction (repo rule fails) |
| 4 | POST-HOC 1-day reversal long/short, SAME-CLOSE fill, 0bp | 6 | Sharpe vs 0 | +0.717 | zero (flat); DSR 0.26 | [-0.064, +1.352] | 0.026 | 1.000 | +0.414 [-0.132, +0.917] | fail |
| 5 | ensemble L2 h=1 score vs sign r(t+2) (tradable) | 11 | AUC | +0.519 | AUC 0.5; acc 0.529 vs majority 0.544 | [+0.500, +0.543] | 0.041 | 1.000 | +0.502 [+0.478, +0.527] | fail |
| 6 | sign given large move (abs r >1.5 sigma), h=5, asym logit (DIAGNOSTIC) | 10 | AUC | +0.573 | AUC 0.5; acc 0.595 vs majority 0.598 | [+0.493, +0.690] | 0.080 | 1.000 | +0.481 [+0.374, +0.574] | fail |
| 7 | tail score, realised large-move days only, h=1 (DIAGNOSTIC) | 10 | AUC | +0.568 | AUC 0.5; acc 0.544 vs majority 0.506 | [+0.512, +0.701] | 0.090 | 1.000 | +0.513 [+0.454, +0.584] | fails correction |
| 8 | ensemble L2 h=5 long/flat | 11 | ΔSharpe vs B&H | +0.316 | buy-and-hold Sharpe 0.976; DSR 0.84 | [-0.185, +0.811] | 0.110 | 1.000 | +0.283 [-0.070, +0.764] | fail |
| 9 | reversal ret_5 when VR(5)<1 (ranging), h=5 | 6 | AUC | +0.530 | AUC 0.5; acc 0.519 vs majority 0.562 | [+0.484, +0.578] | 0.114 | 1.000 | +0.481 [+0.433, +0.526] | fail |
| 10 | ensemble L2 logit (33 signals), h=5 | 11 | AUC | +0.526 | AUC 0.5; acc 0.572 vs majority 0.579 | [+0.482, +0.570] | 0.126 | 1.000 | +0.546 [+0.498, +0.593] | fail |
| 11 | momentum 12-1 in low-vol, h=20 | 6 | AUC | +0.555 | AUC 0.5; acc 0.558 vs majority 0.598 | [+0.442, +0.661] | 0.164 | 1.000 | +0.578 [+0.479, +0.669] | fail |
| 12 | regime-split logit, low-vol rows, h=5 | 6 | AUC | +0.529 | AUC 0.5; acc 0.564 vs majority 0.580 | [+0.470, +0.591] | 0.168 | 1.000 | +0.555 [+0.492, +0.621] | fail |
| 13 | calendar US-holiday proximity: mean forecast vs train mean | 8 | R² vs base | +0.002 | training-mean daily return | [-0.002, +0.004] | 0.182 | 1.000 | -0.002 [-0.008, +0.004] | fail |
| 14 | sign given large move (abs r >2.0 sigma), h=1, asym logit (DIAGNOSTIC) | 10 | AUC | +0.547 | AUC 0.5; acc 0.538 vs majority 0.506 | [+0.475, +0.682] | 0.188 | 1.000 | +0.521 [+0.457, +0.591] | fail |
| 15 | momentum 12-1 in high-vol, h=20 | 6 | AUC | +0.543 | AUC 0.5; acc 0.522 vs majority 0.605 | [+0.441, +0.640] | 0.204 | 1.000 | +0.494 [+0.375, +0.604] | fail |
| 16 | momentum ret_20 in high-vol, h=20 | 6 | AUC | +0.528 | AUC 0.5; acc 0.555 vs majority 0.605 | [+0.442, +0.601] | 0.240 | 1.000 | +0.426 [+0.328, +0.519] | fail |
| 17 | momentum ret_20 in low-vol, h=5 | 6 | AUC | +0.524 | AUC 0.5; acc 0.526 vs majority 0.580 | [+0.436, +0.582] | 0.265 | 1.000 | +0.494 [+0.435, +0.551] | fail |
| 18 | momentum ret_20 in low-vol, h=20 | 6 | AUC | +0.535 | AUC 0.5; acc 0.540 vs majority 0.598 | [+0.406, +0.629] | 0.266 | 1.000 | +0.483 [+0.406, +0.562] | fail |
| 19 | DIAGNOSTIC gold_etf_flow (GLD) 1d change dated t, h=1 | 9 | AUC | +0.510 | AUC 0.5; acc 0.510 vs majority 0.552 | [+0.474, +0.541] | 0.282 | 1.000 | n/a (no pre-2021 data) | fail |
| 20 | ensemble L1 logit (33 signals), h=5 | 11 | AUC | +0.512 | AUC 0.5; acc 0.575 vs majority 0.579 | [+0.467, +0.559] | 0.303 | 1.000 | +0.553 [+0.503, +0.601] | fail |
| 21 | regime-split logit, high-vol rows, h=5 | 6 | AUC | +0.510 | AUC 0.5; acc 0.537 vs majority 0.578 | [+0.454, +0.564] | 0.357 | 1.000 | +0.544 [+0.485, +0.611] | fail |
| 22 | skew_60 sign -> sign given large move, h=5 (DIAGNOSTIC) | 10 | AUC | +0.520 | AUC 0.5; acc 0.447 vs majority 0.598 | [+0.386, +0.616] | 0.364 | 1.000 | +0.516 [+0.423, +0.623] | fail |
| 23 | calendar turn-of-month: mean forecast vs train mean | 8 | R² vs base | +0.000 | training-mean daily return | [-0.001, +0.001] | 0.384 | 1.000 | -0.000 [-0.001, +0.000] | fail |
| 24 | reversal after 2-sigma up day (fade the rally), h=5 | 6 | AUC | +0.525 | AUC 0.5; acc 0.321 vs majority 0.679 | [+0.307, +0.657] | 0.389 | 1.000 | +0.558 [+0.494, +0.634] | fail |
| 25 | reversal after 3-sigma day, h=1 | 6 | AUC | +0.521 | AUC 0.5; acc 0.486 vs majority 0.595 | [+0.439, +0.750] | 0.390 | 1.000 | +0.540 [+0.497, +0.654] | fail |
| 26 | macro logit (11 features), h=1 | 9 | AUC | +0.504 | AUC 0.5; acc 0.539 vs majority 0.562 | [+0.457, +0.547] | 0.426 | 1.000 | n/a (no pre-2021 data) | fail |
| 27 | dxy_daily 1d change (lagged 1 extra bar), prior sign -1, h=1 | 9 | AUC | +0.501 | AUC 0.5; acc 0.496 vs majority 0.552 | [+0.473, +0.530] | 0.460 | 1.000 | n/a (no pre-2021 data) | fail |
| 28 | POST-HOC 1-day reversal -ret_1 vs sign r(t+2) (tradable) | 6 | AUC | +0.500 | AUC 0.5; acc 0.502 vs majority 0.544 | [+0.477, +0.527] | 0.494 | 1.000 | +0.493 [+0.468, +0.518] | fail |
| 29 | reversal after 3-sigma day, h=5 | 6 | AUC | +0.500 | AUC 0.5; acc 0.500 vs majority 0.667 | [+0.458, +0.740] | 0.500 | 1.000 | +0.478 [+0.403, +0.667] | fail |
| 30 | POST-HOC 1-day reversal long/short, SAME-CLOSE fill (upper bound) | 6 | Sharpe vs 0 | -0.068 | zero (flat); DSR 0.00 | [-0.882, +0.516] | 0.573 | 1.000 | -0.399 [-0.952, +0.100] | fail |
| 31 | reversal after 2-sigma down day (buy the dip), h=5 | 6 | AUC | +0.489 | AUC 0.5; acc 0.519 vs majority 0.519 | [+0.427, +0.604] | 0.593 | 1.000 | +0.540 [+0.411, +0.579] | fail |
| 32 | calendar US-holiday proximity: long/flat | 8 | ΔSharpe vs B&H | -0.112 | buy-and-hold Sharpe 0.976; DSR 0.41 | [-0.864, +0.468] | 0.628 | 1.000 | -0.111 [-0.888, +0.744] | fail |
| 33 | gold_etf_flow 1d change (lagged 1 extra bar), prior sign +1, h=1 | 9 | AUC | +0.491 | AUC 0.5; acc 0.494 vs majority 0.552 | [+0.455, +0.524] | 0.691 | 1.000 | n/a (no pre-2021 data) | fail |
| 34 | us2y_daily 1d change (lagged 1 extra bar), prior sign -1, h=1 | 9 | AUC | +0.491 | AUC 0.5; acc 0.494 vs majority 0.552 | [+0.455, +0.522] | 0.706 | 1.000 | n/a (no pre-2021 data) | fail |
| 35 | us10y_daily 1d change (lagged 1 extra bar), prior sign -1, h=1 | 9 | AUC | +0.491 | AUC 0.5; acc 0.494 vs majority 0.552 | [+0.457, +0.522] | 0.713 | 1.000 | n/a (no pre-2021 data) | fail |
| 36 | meta-label P(win) pooled gbm | 7 | AUC | +0.474 | AUC 0.5; acc 0.555 vs majority 0.563 | [+0.403, +0.571] | 0.726 | 1.000 | +0.501 [+0.429, +0.586] | fail |
| 37 | ensemble + macro minus ensemble-only (same rows), h=1, 2023-26 | 11 | ΔAUC | -0.007 | ensemble-only AUC 0.5782 | [-0.030, +0.016] | 0.733 | 1.000 | n/a (no pre-2021 data) | fail |
| 38 | VR-gated momentum/reversal long/short | 6 | Sharpe vs 0 | -0.212 | zero (flat); DSR 0.00 | [-0.886, +0.333] | 0.749 | 1.000 | -1.002 [-1.836, -0.289] | fail |
| 39 | meta-filtered (gbm) vs primary | 7 | ΔSharpe vs primary | -0.241 | primary (all entries, same exits) Sharpe 0.432; DSR 0.02 | [-0.859, +0.355] | 0.782 | 1.000 | -0.112 [-0.464, +0.393] | fail |
| 40 | meta-label P(win) pooled logit | 7 | AUC | +0.473 | AUC 0.5; acc 0.542 vs majority 0.563 | [+0.403, +0.529] | 0.791 | 1.000 | +0.490 [+0.422, +0.552] | fail |
| 41 | momentum ret_20 when VR(5)>1 (trending), h=20 | 6 | AUC | +0.449 | AUC 0.5; acc 0.583 vs majority 0.711 | [+0.348, +0.584] | 0.805 | 1.000 | +0.479 [+0.368, +0.582] | fail |
| 42 | 2-sigma reversal, hold 5d, long/short | 6 | Sharpe vs 0 | -0.333 | zero (flat); DSR 0.00 | [-1.251, +0.198] | 0.812 | 1.000 | -0.526 [-1.137, +0.021] | fail |
| 43 | vix_daily 1d change (lagged 1 extra bar), prior sign +1, h=1 | 9 | AUC | +0.485 | AUC 0.5; acc 0.480 vs majority 0.552 | [+0.454, +0.514] | 0.833 | 1.000 | n/a (no pre-2021 data) | fail |
| 44 | reversal after 2-sigma day, h=1 | 6 | AUC | +0.464 | AUC 0.5; acc 0.462 vs majority 0.589 | [+0.395, +0.526] | 0.856 | 1.000 | +0.509 [+0.441, +0.582] | fail |
| 45 | calendar month-of-year: mean forecast vs train mean | 8 | R² vs base | -0.002 | training-mean daily return | [-0.006, +0.001] | 0.869 | 1.000 | -0.007 [-0.013, -0.002] | fail |
| 46 | B&H, momentum sign(ret_20) in low-vol | 6 | ΔSharpe vs B&H | -0.401 | buy-and-hold Sharpe 0.976; DSR 0.15 | [-0.946, +0.081] | 0.936 | 1.000 | -0.352 [-0.752, +0.143] | fail |
| 47 | reversal after 2-sigma day, h=5 | 6 | AUC | +0.419 | AUC 0.5; acc 0.420 vs majority 0.599 | [+0.304, +0.507] | 0.943 | 1.000 | +0.512 [+0.415, +0.580] | fail |
| 48 | meta-filtered (logit) vs primary | 7 | ΔSharpe vs primary | -0.252 | primary (all entries, same exits) Sharpe 0.432; DSR 0.01 | [-0.602, +0.023] | 0.943 | 1.000 | -0.124 [-0.358, +0.193] | fail |
| 49 | B&H with 2x after 2-sigma down / flat after 2-sigma up (5d) | 6 | ΔSharpe vs B&H | -0.334 | buy-and-hold Sharpe 0.976; DSR 0.20 | [-0.812, -0.013] | 0.947 | 1.000 | -0.294 [-0.583, +0.009] | fail |
| 50 | calendar turn-of-month: long/flat | 8 | ΔSharpe vs B&H | -0.554 | buy-and-hold Sharpe 0.976; DSR 0.08 | [-1.207, +0.042] | 0.955 | 1.000 | -0.005 [-0.479, +0.490] | fail |
| 51 | calendar month-of-year: long/flat | 8 | ΔSharpe vs B&H | -0.391 | buy-and-hold Sharpe 0.976; DSR 0.17 | [-0.935, -0.066] | 0.956 | 1.000 | -0.205 [-0.586, +0.266] | fail |
| 52 | macro logit (11 features), h=5 | 9 | AUC | +0.447 | AUC 0.5; acc 0.551 vs majority 0.610 | [+0.383, +0.497] | 0.962 | 1.000 | n/a (no pre-2021 data) | fail |
| 53 | tail score long/flat | 10 | ΔSharpe vs B&H | -0.583 | buy-and-hold Sharpe 0.976; DSR 0.06 | [-1.285, -0.124] | 0.973 | 1.000 | -0.361 [-0.824, +0.178] | fail |
| 54 | calendar day-of-week: mean forecast vs train mean | 8 | R² vs base | -0.003 | training-mean daily return | [-0.005, -0.000] | 0.980 | 1.000 | -0.002 [-0.006, +0.002] | fail |
| 55 | momentum ret_20 in high-vol, h=5 | 6 | AUC | +0.446 | AUC 0.5; acc 0.497 vs majority 0.578 | [+0.392, +0.494] | 0.981 | 1.000 | +0.446 [+0.372, +0.514] | fail |
| 56 | momentum ret_20 when VR(5)>1 (trending), h=5 | 6 | AUC | +0.402 | AUC 0.5; acc 0.512 vs majority 0.635 | [+0.321, +0.482] | 0.988 | 1.000 | +0.450 [+0.372, +0.524] | fail |
| 57 | meta-filtered (gbm) vs buy-and-hold | 7 | ΔSharpe vs B&H | -0.786 | buy-and-hold Sharpe 0.976; DSR 0.02 | [-1.539, -0.226] | 0.989 | 1.000 | +0.004 [-0.431, +0.636] | fail |
| 58 | macro logit h=1 long/flat | 9 | ΔSharpe vs B&H | -0.942 | buy-and-hold Sharpe 1.521; DSR 0.27 | [-1.912, -0.542] | 0.996 | 1.000 | n/a (no pre-2021 data) | fail |
| 59 | tail score P(up-tail)-P(down-tail), all days, h=1 | 10 | AUC | +0.467 | AUC 0.5; acc 0.465 vs majority 0.544 | [+0.443, +0.490] | 0.998 | 1.000 | +0.466 [+0.439, +0.488] | fail |
| 60 | ensemble L2 h=1 long/flat | 11 | ΔSharpe vs B&H | -0.694 | buy-and-hold Sharpe 0.976; DSR 0.03 | [-1.151, -0.198] | 0.998 | 1.000 | -0.623 [-1.008, -0.154] | fail |
| 61 | POST-HOC 1-day reversal long/short (protocol lag) | 6 | Sharpe vs 0 | -0.966 | zero (flat); DSR 0.00 | [-1.621, -0.361] | 0.999 | 1.000 | -0.815 [-1.378, -0.161] | fail |
| 62 | primary 8-strategy triple-barrier portfolio vs buy-and-hold | 7 | ΔSharpe vs B&H | -0.544 | buy-and-hold Sharpe 0.976; DSR 0.07 | [-0.967, -0.284] | 0.999 | 1.000 | +0.116 [-0.212, +0.466] | fail |
| 63 | meta-filtered (logit) vs buy-and-hold | 7 | ΔSharpe vs B&H | -0.796 | buy-and-hold Sharpe 0.976; DSR 0.01 | [-1.391, -0.428] | 0.999 | 1.000 | -0.008 [-0.424, +0.497] | fail |
| 64 | calendar day-of-week: long/flat | 8 | ΔSharpe vs B&H | -1.357 | buy-and-hold Sharpe 0.976; DSR 0.00 | [-1.861, -0.905] | 1.000 | 1.000 | -0.538 [-1.054, -0.060] | fail |

### What the one lead is, and why it is not a pass

The strongest thread runs through four families: short-horizon reversal.
Measured directly with `/tmp/a0-research2/h1_check.py`:

| Measurement | 2018–26 | 2010–18 |
|---|---:|---:|
| Lag-1 autocorrelation of daily log returns | −0.027 | −0.038 |
| The same, excluding pairs that touch a flat (O=H=L=C) bar | −0.031 | −0.040 |
| Walk-forward logit on `ret_1` alone, AUC for sign r(t+1) | 0.540 | 0.525 |
| Ensemble (33 signals) without `ret_1` / `z1`, AUC | 0.523 | 0.513 |
| Ensemble h=1 score against sign r(t+2), the return the protocol trades | 0.519 | 0.502 |
| 1-day reversal long/short, protocol lag, Sharpe | −0.97 | −0.82 |
| The same, same-close fill (upper bound), 5 bp | −0.07 | −0.40 |
| The same, same-close fill, 0 bp | +0.72 [−0.06, 1.35] | +0.41 [−0.13, 0.92] |

Read together:

- **Almost all of the ensemble's h=1 skill is `ret_1`.**
- **The flat bars do not cause it.** Excluding them leaves the
  autocorrelation where it was.
- **It lasts one bar.** A signal from close t says something about the next
  close and nothing about the one after.
- **It is too small to pay its own turnover.** A daily long/short flips about
  every second day. At 5 bp per unit of turnover that costs about 12% a year.

Two readings fit the data:

- **(a) A real microstructure effect.** Overreaction at the daily close that
  reverts overnight.
- **(b) A property of how the daily close in `XAUUSD_40Y.csv` is sampled.**
  A settlement or fix price, or a close stamped at a slightly different time
  from bar to bar, creates exactly this negative autocorrelation. It cannot be
  traded, because the price in the file is not the price the platform fills
  at.

**Daily bars cannot tell (a) from (b).** Intraday bars with a known close
time can. That is item 1 in the data list below.

### Data-quality findings along the way

- **`data/macro/gold_etf_flow.csv` is GLD's price, not an ETF flow.** It
  correlates with same-day gold returns at 0.926, and
  `ml/macro_bootstrap.py` maps it from the `GLD` ticker. `ml/macro_features.py`
  and `ml/signal_scorer.py` consume it as a "flow". Holdings or flows are a
  different series (data item 5).
- **The macro series are clean but short.** They start 2021-03-29, with 0
  duplicates, 0 weekend rows, no gaps over 4 days and no runs of repeated
  values. Unchanged days are 0.08–1.4%, and 0.08–0.56% of rows sit at their
  month's mean, which is noise level. One gold bar (2025-07-04) has no DXY
  row.
- **The close times do not quite match.** Gold's return on day t correlates
  +0.07 with GLD's return on day t−1, and −0.076 with VIX's return on day t−1.
  That small overlap is consistent with the gold bar closing earlier than the
  4 pm New York equity close. Every macro feature was therefore lagged by one
  extra bar. The unlagged GLD diagnostic (row 19) still shows nothing
  tradable: AUC 0.510.

## Recommendation: how to use this in the skill-weighted ensemble

The platform's vote-weighting ensemble is `strategies/strategy_brain.py`.
`_recalculate_weights` scores each member as
`0.7·win_rate + 0.3·min(pnl/1000, 1)`, floored at 0.1.

1. **Give every directional member zero weight until it shows skill over the
   base rate.**
   - A win rate is not skill in a market that rose on 54% of days (and 58% of 5-day windows). Every
     always-long member "wins" more than half the time.
   - The 0.1 floor guarantees weight to a member with none.
   - The change: weight = max(0, lower 95% bound of that member's rolling OOS
     skill over the base rate), measured the way `ml.oos_skill` does. Under
     this rule every strategy tested in either spike gets **0** today.
   - That is a code change for a separate, test-first task. It is not made
     here.
2. **Keep the one positive result from spike 1 as the ensemble's risk input.**
   Calibrated EWMA volatility sets position size (∝ 1/σ̂) and stop distance.
   Nothing in this spike changes that recommendation.
3. **Register short-horizon reversal as a *shadow* member**, logged and never
   traded, with weight fixed at 0. Pre-register exactly two hypotheses, signs
   fixed now:
   - **H1:** `−ret_1` ranks the sign of r(t+1), AUC > 0.5.
   - **H2:** `−ret_20` in the high-vol regime ranks the 5-day direction.

   Test each **once**, on bars after 2026-03-25, when at least two years exist.
   At n ≈ 500 the AUC CI half-width is about 0.05, so four years are better. A single pre-registered test needs no
   multiple-comparison correction.
   - Even if both pass, H1 is worth something only if the platform can act on
     it **before** the close it is measured from. That needs the intraday data
     in data item 1.
   - It also needs a cost below about 1 bp a side. At 5 bp even a perfect
     same-close fill loses money (Sharpe −0.07).
4. **Do not use meta-labelling, calendar effects or the current macro set.**
   Each was tested directly and has nothing to filter or add.

## Data the platform does not have, and why it matters for gold

Ranked by how directly each item would test something this spike could not.

| # | Data | Why (literature and this spike) | Cost / source |
|---:|---|---|---|
| 1 | **Intraday XAUUSD bars or ticks with bid/ask and a known close time** (1-min minimum) | This settles whether the 1-day reversal is real or a sampling artifact (above). It opens intraday momentum, where the first half-hour return predicts the last half-hour (Gao, Han, Li & Zhou 2018, *JFE*). It opens London-fix and session effects: price moves ahead of the London fix (Caminschi & Heaney 2014, *J. Futures Markets*), and Asia, London and New York session returns. It is also the only way to measure real spread and slippage. | OANDA/MT5 history via the owner's credentials (already a §A0 blocker), or Dukascopy/TrueFX exports |
| 2 | **Real yields: 10y TIPS (FRED `DFII10`) and breakevens (`T10YIE`), daily since 2003** | Real rates are the best-documented macro driver of gold (Erb & Harvey 2013, *FAJ*). Only nominal yields are offline, and only from 2021, so a real-rate test could not be run or replicated. | Free (FRED) |
| 3 | **Longer macro history: DXY, UST 2y/10y, VIX from 2000 onward** | Family 9 has 5 years, no replication and wide CIs. With 25 years, the lead-lag tests could be run on both windows. | Free (FRED, yfinance, CBOE) |
| 4 | **CFTC Commitments of Traders, COMEX gold** (managed-money net positioning, weekly, since 2006) | Positioning extremes are the most cited medium-horizon contrarian signal for commodities. A weekly release lag (Tuesday data, Friday publication) must be respected. | Free (CFTC) |
| 5 | **Gold ETF holdings and flows** (GLD/IAU tonnes; WGC regional flows) | This is the real "ETF flow" the repo thinks it has. Flows are persistent and are documented to lead short-horizon price. | GLD holdings file (free); WGC (free with registration) |
| 6 | **Options-implied data: GVZ (gold VIX), 25-delta risk reversals and skew** | Implied volatility usually beats EWMA for volatility forecasts, which would improve the one signal that works. Skew and risk reversals are the market's own view of tail direction, which is exactly what family 10 could not predict from price. | GVZ free (CBOE, since 2008); risk reversals need a CME or vendor feed |
| 7 | **Scheduled-event calendar with timestamps** (FOMC, CPI, NFP, since 2000) | Event-conditioned drift and volatility, such as pre-FOMC drift (Lucca & Moench 2015, *JF*) and gold's response to CPI surprises. `data/news_calendar_feed.py` exists, but no history is committed. Surprises also need consensus figures. | Dates free (Fed, BLS); consensus needs a vendor |
| 8 | **COMEX futures volume, open interest and term structure** (front-month basis, EFP) | Flow and carry signals, and the only volume that is real for gold. Spot "volume" in the CSV is not a traded-volume measure. | CME (vendor) |
| 9 | **Physical demand proxies:** the Shanghai Gold Exchange premium, and India import duty and premium | Regional physical demand has driven price in 2023–26, and central-bank buying is the dominant theme. Quarterly WGC central-bank data is too slow for trading but useful for regime. | SGE (free, patchy); WGC |

## Reproduce

Python 3.11.15, pandas 3.0.5, scikit-learn 1.9.1, scipy 1.17.1, numpy 2.4.6.
Base: `4be177d4` after `git merge claude/add-new-skills-lys862`.
`data/XAUUSD_40Y.csv` sha256 prefix `7ffc2bf583972eef`. The results are
deterministic (seed 42). The first run caches the repo strategies' positions,
which takes about 2 minutes. Each run then takes about 1–2 minutes on 4 shared
cores.

```bash
# main run: 64 new tests, Bonferroni over 52 + 64, DSR pool includes spike 1's 16 strategies
python scripts/research/a0_direction_research2.py --out /tmp/a0-research2 --prior-strategies

# replication on the earlier, disjoint OOS window 2010-03-24 .. 2018-03-23 (family 9 skipped: no data)
python scripts/research/a0_direction_research2.py --out /tmp/a0-research2 --truncate-at 2018-03-26
```

The scratch checks are `macro_check.py`, `lookahead_check.py`, `dow_check.py`
and `h1_check.py` in `/tmp/a0-research2/`, and this document records their
output.

## Limits

- **One instrument, daily bars, close only.** Everything intraday is untested,
  not ruled out (data item 1 below).
- **The macro family has low power and cannot be replicated.** It has 3–5
  years and one regime, and rate hikes dominate 2022–23.
- **Bonferroni is conservative for 116 correlated tests.** The conclusion does
  not rest on it:
  - The rows closest to passing (1–3) also fail the repo rule.
  - They lose their skill against the return that can actually be traded.
  - Row 1 is the same effect as rows 2 and 3.

  Holm or Benjamini–Hochberg would not produce a tradable finding.
- **Meta-labelling used one barrier setting**, 10 bars at ±1σ√10. A wider
  sweep would add trials against a secondary model whose AUC sits at 0.47–0.49
  in both windows.
- **Financing and swap costs are ignored**, as in spike 1.
