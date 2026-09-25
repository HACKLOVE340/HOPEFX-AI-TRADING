# A0: which target has skill? (research spike, 2026-09-25)

> **Status: research only.** No production module changed. Nothing was written
> under `ml/saved_models/` or `ml/rl_models/`, and neither `registry.json` nor
> `model_checksums.json` was touched. `python -m ml.verify_model` still passes
> (`active=xgb_horizon5_v3`). The one kept script is
> `scripts/research/a0_target_research.py`, and it passes ruff. It writes only
> to the `--out` directory. Scratch output went to `/tmp/a0-research/`.
>
> **Context:** `docs/ai/MASTER_OUTSTANDING.md` §A0 and
> `docs/audit/2026-09-24-a0-no-edge-investigation.md`. After fixes 1–8, the
> 5-bar direction classifier on clean 26-year data has no edge: accuracy equals
> always-up (0.5717), AUC is 0.500, and it predicts up on 100% of bars. The
> owner asked where there is signal, if anywhere, before more gets built.

## The answer in one paragraph

**There is no directional signal at any horizon we tested, in any form.** That
covers 5, 10, 20 and 60 bars, a linear and a tree model, a 3-class target, and
direction measured only on large moves. **What survives correction is
volatility.** How big the next move will be is forecastable. Which way it goes
is not. Eight of the 52 tests pass after a Bonferroni correction, and all eight
are measurements of volatility:

- **Two pass outright as volatility forecasts.** A calibrated EWMA forecast of
  realised volatility beats a constant, with OOS R² of +0.24 over 5 days and
  +0.32 over 20 days.
- **Six pass on large-move or 3-class targets.** These look directional, but a
  paired test shows their skill comes from volatility features. Adding the
  directional features does not improve on a model that uses volatility
  features only. That result replicates on a separate earlier window,
  2010–2018.

**No model beats the naive EWMA volatility forecast after correction.** The
best, a ridge on 20-day volatility, scored +0.15 R² over EWMA with an
uncorrected p of 0.002, but that gain **reverses on 2010–2018**, to −0.09.

**No trading rule beats buy-and-hold on Sharpe.** That holds for the textbook
rules and for all eight repo strategies. Four repo strategies do significantly
worse, even before correction.

**Recommendation:** stop building a direction model. Use the EWMA volatility
forecast where the platform needs to know *how much* risk it is taking:
position sizing, stop distance and VaR. Measure it with a VaR backtest, not
with Sharpe.

## Method (what makes it honest)

| Choice | What was done | Why |
|---|---|---|
| Data | `ml.train_advanced.fetch_gold_ohlcv(..., cached_csv="data/XAUUSD_40Y.csv", allow_download=False)`: 6,415 daily bars from 2000-08-30 to 2026-03-25. The spike gate passes. The flat-bar gate passes at 12.7% flat (threshold 20%), and only 1.2% of bars sit at the month mean. Within the OOS window the flat rate is 6.0%. | This is the repo's loader with both A0 gates. There is no network access, and the 50Y file is never read. |
| Price columns | **Close only**, for every feature, label and threshold. Thresholds are scaled by close-to-close σ₂₀, never by ATR. | 441 bars before 2020 have inconsistent high/low values (`ml/cached_series.py`), and 1 in 8 bars is O=H=L=C. The repo strategies (family 5) still read high and low, because that is what they do live. |
| Features | 18 stationary features, each computed from closes up to t only. They are returns over 1/5/20/60/120/250 days, 12-1 momentum, log volatility over 5/20/60 days and EWMA, the 20/60 volatility ratio, distance to the 50/200-day MAs, distance to the 250-day high and low, the 20-day z-score and RSI-14. | No price levels (D4), and no zero-filled macro features (D8). |
| Look-ahead proof | `/tmp/a0-research/lookahead_check.py` rescales every close after row k, for k = 1,000, 4,000 and 6,000. Features at rows up to k change by **0.0**, and every label ending at or before k is unchanged. A one-day position placed on bar k earns exactly r(k+2). | Features at t use only data at or before t. |
| OOS window | Every row dated after `last − 8y`, which is **2018-03-26 → 2026-03-25**. This is about 2,000 rows, the window of the post-fix retrain. | Defined by date (A0 #7). |
| Walk-forward | The model is refit at the start of each OOS year, on all earlier rows, with the last `h` rows before the fold **purged**. That gives 8 refits. | A purge gap of at least the label horizon. |
| Models | Logit (C=0.1) or ridge (α=10) on standardised features, and a HistGradientBoosting model (depth 2, 150 iterations, learning rate 0.05, min_leaf 100). **No tuning.** | These are small models, so there are no hyper-parameter degrees of freedom to spend. |
| Classification baseline | `ml.oos_skill.oos_skill_metrics` gives accuracy against always-majority, balanced accuracy and the block-bootstrap AUC CI. Direction also has to pass `skill_over_base_rate_check`, the promotion rule. | The repo's own rule. |
| Volatility baselines | Calibrated EWMA (λ=0.94), with the log-vol target regressed on log EWMA walk-forward. Persistence (trailing N-day realised volatility) and a constant (the training mean) are also reported. | "Naive persistence/EWMA baseline". The calibrated EWMA gets the same chance to correct its bias as the models do. |
| Strategy evaluation | A position decided at close t executes at close t+1 and earns r(t+2), a full bar of lag. Costs are **5 bp per unit of turnover**. Metric: Sharpe of the strategy minus Sharpe of buy-and-hold, on paired daily returns. | Transaction costs, and a comparison against the honest alternative. |
| Uncertainty | Moving-block bootstrap with 1,000 draws and seed 42. The block is max(h, 20) rows for labels and 63 days for strategies. The one-sided p comes from the bootstrap SE. | The block is at least the label horizon. |
| Multiple comparisons | **52 tests** in the main run, with every variant counted, including diagnostics. Bonferroni gives α = 0.05/52 = 0.00096. Families 4 and 5 also get a deflated Sharpe ratio over their 16 trials. | Guards against optimism from trying many variants. |

## Results

### Summary by family

| Family | Variants | Pass after Bonferroni | Best result | Verdict |
|---|---:|---:|---|---|
| 1. Direction, h = 5/10/20/60 | 8 | **0** | h=5 logit AUC 0.530 [0.488, 0.572]; accuracy 0.583 against always-up 0.579 | No skill. At h ≥ 10 every AUC is **below** 0.5 (0.40–0.48), but not significantly. Relationships learned in 2001–2017 point the wrong way in the 2018–26 rally. |
| 2. Magnitude: 3-class, large-move events, decomposition, diagnostic | 20 | 6 | large-up h=20 logit AUC 0.654 [0.576, 0.724] | Skill is present, **but it is volatility**. All features minus volatility-only: large-up +0.039 (p 0.033, fails correction), large-down −0.014, either-side +0.028. On 2010–18 all six increments are ≤ 0. |
| 3. Volatility | 8 | 2 | EWMA against constant: RV20 R² +0.318 [0.165, 0.419] | **Volatility is forecastable, and the naive EWMA is the forecaster.** Ridge against EWMA, RV20: +0.153 [0.041, 0.253], p 0.002, **p Bonferroni 0.115**, and **−0.087 on 2010–18**. GBM does not help. Neither model beats persistence on regime. |
| 4. Textbook rules | 8 | **0** | vol-targeted buy-and-hold: ΔSharpe +0.045 [−0.205, +0.196] | Nothing beats buy-and-hold (Sharpe 0.98). Trend filters give up 0.17–0.53 of Sharpe. The macro proxies cut drawdown to 11–13% but give up return. |
| 5. Repo strategies (8) | 8 | **0** | pullback: Sharpe 0.82 against 0.98 | Every strategy is below buy-and-hold. For macd, breakout, emacrossover and meanreversion the CI lies **entirely below 0** before any correction. |

### Full ranked table (main run, OOS 2018-03-26 → 2026-03-25, m = 52)

"Fails correction" means the 95% CI clears the null, but the Bonferroni p is
0.05 or higher. For direction rows, "pass" also requires
`skill_over_base_rate_check`.

| Rank | Candidate | Family | Metric | Value | Baseline | 95% CI | p (1-sided) | p Bonferroni (m=52) | Pass |
|---:|---|---|---|---:|---|---|---:|---:|---|
| 1 | RV5 EWMA(cal) vs constant | 3 | R² vs baseline | +0.236 | constant (train mean) | [+0.145, +0.307] | 7.9e-09 | 4.1e-07 | **PASS** |
| 2 | RV20 EWMA(cal) vs constant | 3 | R² vs baseline | +0.318 | constant (train mean) | [+0.165, +0.419] | 6.3e-07 | 3.3e-05 | **PASS** |
| 3 | large-up event h=5 logit | 2 | AUC | +0.624 | AUC 0.5 (event rate 0.184) | [+0.569, +0.673] | 3.2e-06 | 1.7e-04 | **PASS** |
| 4 | 3-class h=5 k=0.5 logit | 2 | macro AUC | +0.576 | AUC 0.5; acc 0.444 vs majority 0.417 | [+0.540, +0.607] | 7.1e-06 | 3.7e-04 | **PASS** |
| 5 | large-up event h=5 gbm | 2 | AUC | +0.619 | AUC 0.5 (event rate 0.184) | [+0.556, +0.670] | 1.6e-05 | 8.4e-04 | **PASS** |
| 6 | large-up event h=20 logit | 2 | AUC | +0.654 | AUC 0.5 (event rate 0.244) | [+0.576, +0.724] | 2.2e-05 | 0.001 | **PASS** |
| 7 | 3-class h=20 k=0.5 logit | 2 | macro AUC | +0.595 | AUC 0.5; acc 0.501 vs majority 0.405 | [+0.545, +0.641] | 4.3e-05 | 0.002 | **PASS** |
| 8 | large-up event h=20 gbm | 2 | AUC | +0.623 | AUC 0.5 (event rate 0.244) | [+0.549, +0.694] | 4.8e-04 | 0.025 | **PASS** |
| 9 | RV20 ridge vs EWMA(cal) | 3 | R² vs baseline | +0.153 | calibrated EWMA | [+0.041, +0.253] | 0.002 | 0.115 | fails correction |
| 10 | 3-class h=5 k=0.5 gbm | 2 | macro AUC | +0.547 | AUC 0.5; acc 0.404 vs majority 0.417 | [+0.512, +0.577] | 0.003 | 0.148 | fails correction |
| 11 | large-down event h=5 logit | 2 | AUC | +0.583 | AUC 0.5 (event rate 0.131) | [+0.516, +0.642] | 0.005 | 0.252 | fails correction |
| 12 | large-down event h=20 logit | 2 | AUC | +0.621 | AUC 0.5 (event rate 0.098) | [+0.528, +0.718] | 0.007 | 0.370 | fails correction |
| 13 | large-up h=5: all features - vol-only (logit) | 2 | ΔAUC | +0.039 | vol-only AUC 0.5843 | [+0.001, +0.085] | 0.033 | 1.000 | fails correction |
| 14 | RV5 ridge vs EWMA(cal) | 3 | R² vs baseline | +0.039 | calibrated EWMA | [-0.008, +0.085] | 0.053 | 1.000 | fail |
| 15 | large-either h=5: all features - vol-only (logit) | 2 | ΔAUC | +0.028 | vol-only AUC 0.6174 | [-0.008, +0.062] | 0.059 | 1.000 | fail |
| 16 | direction h=5 logit | 1 | AUC | +0.530 | AUC 0.5; acc 0.583 vs always-majority 0.579 | [+0.488, +0.572] | 0.080 | 1.000 | fail |
| 17 | large-either h=20: all features - vol-only (logit) | 2 | ΔAUC | +0.032 | vol-only AUC 0.6764 | [-0.015, +0.081] | 0.091 | 1.000 | fail |
| 18 | 3-class h=20 k=0.5 gbm | 2 | macro AUC | +0.530 | AUC 0.5; acc 0.396 vs majority 0.405 | [+0.478, +0.583] | 0.132 | 1.000 | fail |
| 19 | large-down event h=5 gbm | 2 | AUC | +0.537 | AUC 0.5 (event rate 0.131) | [+0.469, +0.601] | 0.133 | 1.000 | fail |
| 20 | large-up h=20: all features - vol-only (logit) | 2 | ΔAUC | +0.032 | vol-only AUC 0.6218 | [-0.027, +0.088] | 0.138 | 1.000 | fail |
| 21 | large-down event h=20 gbm | 2 | AUC | +0.547 | AUC 0.5 (event rate 0.098) | [+0.465, +0.637] | 0.155 | 1.000 | fail |
| 22 | vol regime h=20 logit vs persistence | 3 | ΔAUC | +0.031 | persistence AUC 0.6522 | [-0.034, +0.094] | 0.165 | 1.000 | fail |
| 23 | direction h=5 gbm | 1 | AUC | +0.516 | AUC 0.5; acc 0.550 vs always-majority 0.579 | [+0.472, +0.555] | 0.221 | 1.000 | fail |
| 24 | vol regime h=20 gbm vs persistence | 3 | ΔAUC | +0.022 | persistence AUC 0.6522 | [-0.053, +0.103] | 0.290 | 1.000 | fail |
| 25 | vol-targeted buy-and-hold (18.0%, cap 2x) | 4 | ΔSharpe | +0.045 | B&H Sharpe 0.98 (strategy 1.02) | [-0.205, +0.196] | 0.335 | 1.000 | fail |
| 26 | RV20 gbm vs EWMA(cal) | 3 | R² vs baseline | +0.008 | calibrated EWMA | [-0.194, +0.177] | 0.466 | 1.000 | fail |
| 27 | direction given large move h=5 logit (DIAGNOSTIC) | 2 | AUC | +0.501 | AUC 0.5; acc 0.569 vs majority 0.585 | [+0.430, +0.584] | 0.488 | 1.000 | fail |
| 28 | RV5 gbm vs EWMA(cal) | 3 | R² vs baseline | -0.010 | calibrated EWMA | [-0.080, +0.048] | 0.622 | 1.000 | fail |
| 29 | large-down h=20: all features - vol-only (logit) | 2 | ΔAUC | -0.018 | vol-only AUC 0.6383 | [-0.105, +0.063] | 0.662 | 1.000 | fail |
| 30 | large-down h=5: all features - vol-only (logit) | 2 | ΔAUC | -0.014 | vol-only AUC 0.5969 | [-0.078, +0.022] | 0.710 | 1.000 | fail |
| 31 | direction h=60 logit | 1 | AUC | +0.446 | AUC 0.5; acc 0.656 vs always-majority 0.688 | [+0.335, +0.595] | 0.787 | 1.000 | fail |
| 32 | 10y yield falling (20d) long/flat [2021+ only] | 4 | ΔSharpe | -0.290 | B&H Sharpe 1.16 (strategy 0.87) | [-1.118, +0.267] | 0.800 | 1.000 | fail |
| 33 | direction h=10 logit | 1 | AUC | +0.476 | AUC 0.5; acc 0.575 vs always-majority 0.571 | [+0.416, +0.525] | 0.803 | 1.000 | fail |
| 34 | DXY falling (20d) long/flat [2021+ only] | 4 | ΔSharpe | -0.248 | B&H Sharpe 1.16 (strategy 0.91) | [-0.958, +0.177] | 0.811 | 1.000 | fail |
| 35 | repo rsi (long/flat) | 5 | ΔSharpe | -0.336 | B&H Sharpe 0.98 (strategy 0.64) | [-1.177, +0.300] | 0.812 | 1.000 | fail |
| 36 | repo pullback (long/flat) | 5 | ΔSharpe | -0.156 | B&H Sharpe 0.98 (strategy 0.82) | [-0.540, +0.136] | 0.821 | 1.000 | fail |
| 37 | repo stochastic (long/flat) | 5 | ΔSharpe | -0.259 | B&H Sharpe 0.98 (strategy 0.72) | [-0.757, +0.266] | 0.837 | 1.000 | fail |
| 38 | SMA50>SMA200 long/flat | 4 | ΔSharpe | -0.172 | B&H Sharpe 0.98 (strategy 0.80) | [-0.466, +0.102] | 0.885 | 1.000 | fail |
| 39 | SMA200 long/flat | 4 | ΔSharpe | -0.194 | B&H Sharpe 0.98 (strategy 0.78) | [-0.494, +0.118] | 0.893 | 1.000 | fail |
| 40 | TSMOM 12-1 long/flat | 4 | ΔSharpe | -0.201 | B&H Sharpe 0.98 (strategy 0.77) | [-0.521, +0.091] | 0.898 | 1.000 | fail |
| 41 | direction h=10 gbm | 1 | AUC | +0.463 | AUC 0.5; acc 0.500 vs always-majority 0.571 | [+0.401, +0.517] | 0.899 | 1.000 | fail |
| 42 | repo bollingerbands (long/flat) | 5 | ΔSharpe | -0.333 | B&H Sharpe 0.98 (strategy 0.64) | [-0.890, +0.061] | 0.918 | 1.000 | fail |
| 43 | direction h=20 gbm | 1 | AUC | +0.448 | AUC 0.5; acc 0.487 vs always-majority 0.602 | [+0.378, +0.514] | 0.929 | 1.000 | fail |
| 44 | direction h=20 logit | 1 | AUC | +0.442 | AUC 0.5; acc 0.568 vs always-majority 0.602 | [+0.369, +0.520] | 0.929 | 1.000 | fail |
| 45 | direction given large move h=20 logit (DIAGNOSTIC) | 2 | AUC | +0.393 | AUC 0.5; acc 0.708 vs majority 0.713 | [+0.290, +0.563] | 0.933 | 1.000 | fail |
| 46 | direction h=60 gbm | 1 | AUC | +0.403 | AUC 0.5; acc 0.550 vs always-majority 0.688 | [+0.298, +0.527] | 0.947 | 1.000 | fail |
| 47 | TSMOM 12-1 long/short | 4 | ΔSharpe | -0.531 | B&H Sharpe 0.98 (strategy 0.45) | [-1.210, +0.036] | 0.950 | 1.000 | fail |
| 48 | SMA200 long/short | 4 | ΔSharpe | -0.532 | B&H Sharpe 0.98 (strategy 0.44) | [-1.153, -0.003] | 0.962 | 1.000 | fail |
| 49 | repo meanreversion (long/flat) | 5 | ΔSharpe | -0.621 | B&H Sharpe 0.98 (strategy 0.35) | [-1.390, -0.088] | 0.968 | 1.000 | fail |
| 50 | repo macd (long/flat) | 5 | ΔSharpe | -0.489 | B&H Sharpe 0.98 (strategy 0.49) | [-0.980, -0.067] | 0.979 | 1.000 | fail |
| 51 | repo breakout (long/flat) | 5 | ΔSharpe | -0.403 | B&H Sharpe 0.98 (strategy 0.57) | [-0.775, -0.101] | 0.988 | 1.000 | fail |
| 52 | repo emacrossover (long/flat) | 5 | ΔSharpe | -0.513 | B&H Sharpe 0.98 (strategy 0.46) | [-0.962, -0.212] | 0.996 | 1.000 | fail |

### Why the passing magnitude targets are volatility, not direction

The large-move threshold is `1.0 · σ₂₀ · √h`, which is scaled by *trailing*
volatility. A model that forecasts only that volatility will *expand* beats
AUC 0.5 on **both** sides. Four measurements say that is what these models are
doing:

1. **Both sides score.** Large-up has AUC 0.62–0.65 and large-down 0.58–0.62.
   A directional signal would lift one side and lower the other.
2. **Volatility features alone do as well.** A logit on the five volatility
   features alone scores AUC 0.58–0.68. Adding the 13 directional features
   changes AUC by −0.018 to +0.039 (rows 13, 15, 17, 20, 29, 30). No change
   survives correction, and on large-down the change is negative.
3. **The 3-class skill is the "flat" class.** Per-class OvR AUC for the h=20
   logit is flat 0.696, up 0.602 and down 0.488. For h=5 it is flat 0.618, up
   0.568 and down 0.542. Knowing when *no large move* is coming is volatility
   forecasting. The 3-class log-loss beats the train-prior climatology by only
   1.3% (h=5) and 3.6% (h=20).
4. **It replicates as volatility on a separate window.** On 2010-03-24 →
   2018-03-23, with data truncated before 2018-03-26 and the same code, all six
   "all features − vol-only" increments are **≤ 0**, from −0.047 to −0.007.
   Large-up h=5 logit (0.628) and 3-class h=5 logit (0.565) pass again.

Direction restricted to large moves, a diagnostic that selects rows on the
future and so cannot be traded, scores AUC 0.501 at h=5 and 0.393 at h=20.
**Even when a big move comes, its sign is not predictable from these
features.**

### Volatility: EWMA is the forecaster, and the models add nothing that replicates

| Test | 2018–2026 (main) | 2010–2018 (replication, same code) |
|---|---|---|
| RV5, EWMA(cal) against constant | R² **+0.236** [0.145, 0.307] | R² **+0.204** [0.123, 0.273] |
| RV20, EWMA(cal) against constant | R² **+0.318** [0.165, 0.419] | R² **+0.322** [0.151, 0.472] |
| RV5, ridge against EWMA(cal) | +0.039 [−0.008, 0.085] | −0.024 [−0.085, 0.034] |
| RV20, ridge against EWMA(cal) | +0.153 [0.041, 0.253], IC 0.605 against 0.505 | **−0.087** [−0.245, 0.049], IC 0.536 against 0.552 |
| RV20, GBM against EWMA(cal) | +0.008 [−0.194, 0.177] | −0.201 [−0.487, 0.002] |
| Vol regime, logit against persistence (ΔAUC) | +0.031 [−0.034, 0.094] | −0.149 [−0.259, −0.047] |

Out of sample, calibrated EWMA also beats raw persistence, with R² +0.41 at
RV5 and +0.25 at RV20. The ridge's gain on RV20 in 2018–26 was the most
promising non-naive result. It does not survive the correction, and **it
reverses on the earlier window**, so it is not a finding.

### Strategies: buy-and-hold is the bar, and nothing clears it

- **Buy-and-hold, OOS:** Sharpe 0.976, CAGR 16.4%. The probabilistic Sharpe
  against 0 is 0.996.
- **Deflated Sharpe** is measured against 16 trials, which sets the expected
  maximum null Sharpe (SR₀) at 0.35 per year. Only vol-targeted buy-and-hold
  reaches a DSR above 0.95 (0.968), and that is buy-and-hold rescaled.
- **Everything else has a DSR between 0.50 and 0.90.**
- **Costs are not the reason:** at 0 bp, every ΔSharpe is still ≤ +0.071, and
  nothing passes (`--cost-bps 0`).
- **Before OOS, 2001–2018** (context only, not a test), the trend rules roughly
  matched buy-and-hold: TSMOM long/flat 0.61 against 0.61, and SMA200
  long/flat 0.53. Vol targeting scored 0.71. **Trend-timing gold has not
  added Sharpe in either period.**
- **Repo strategies:**
  - `pullback` holds for the whole window after entering (0.13 turns a year),
    so it is buy-and-hold with a delayed entry.
  - `meanreversion` and `rsi` are invested 20% of the time.
  - `macd` and `emacrossover` trade 46–67 times a year, and their Sharpe is
    0.46–0.49.
  - No strategy raised an error on any bar (`strategy_errors = 0` for all 8).

## Recommendation

1. **Stop spending effort on direction.** Across 8 horizon×model variants, 2
   regimes, a 3-class target and a large-move conditional, no directional
   target has skill that survives an honest test. The 5-bar direction model the
   platform ships has the same null result. More data, features or model
   capacity are unlikely to change this. The AUCs at h ≥ 10 sit *below* 0.5 out
   of sample, which is the signature of relationships that are unstable across
   regimes.
2. **Build on volatility, and keep it naive.** Calibrated EWMA (λ=0.94) is the
   forecaster. It is skilful (R² +0.20 to +0.32 against a constant, replicated
   in both windows) and nothing tested beats it robustly. Its value is in
   **risk**, not in return prediction. Scaling buy-and-hold by it did not
   significantly improve Sharpe (+0.045).
3. **Return and alpha:** the evidence says gold's return over 2018–26 came from
   holding it. A strategy has to beat buy-and-hold net of costs under this
   protocol, or it is noise that loses 0.2–0.6 of Sharpe. That includes the
   eight in `strategies/`.

## Next step for each passing candidate

| Passing candidate | What to build | The test that proves it (write it first) |
|---|---|---|
| **EWMA realised-vol forecast, RV5 and RV20** (rows 1–2) | `risk/vol_forecast.py`, a calibrated EWMA σ̂ₜ₊₁..ₜ₊ₙ (λ=0.94, with a+b calibration refit walk-forward), used by `risk/manager.py` for position size (∝ 1/σ̂) and stop distance in place of ATR. It must read closes only, because the high/low columns before 2020 are unreliable. | (a) `tests/unit/test_vol_forecast_beats_constant.py`: on `XAUUSD_40Y.csv`, the walk-forward OOS R² against the training-mean constant has a moving-block (20) bootstrap 95% lower bound above 0, in **both** 2010–18 and 2018–26. (b) A VaR backtest: 1-day 99% VaR from σ̂ has a Kupiec exception rate within [0.5%, 1.5%], and the Christoffersen independence test gives p > 0.05 on 2018–26. It must calibrate better than a fixed 250-day historical σ, which is the test that shows it *does* something. (c) A property test: σ̂ at row t is unchanged when every close after t is perturbed (the same method as `lookahead_check.py`). |
| **Large-move / 3-class targets** (rows 3–8) | **Nothing new.** These are the same volatility signal under another name. If a "no large move expected" flag is wanted, for example to widen or skip entries, derive it from σ̂ above. | Before anyone builds a directional product on them: a paired test that AUC(all features) − AUC(vol-only) has a lower bound above 0 after correction, in both windows. It fails today in both. |
| **Ridge against EWMA, RV20** (row 9, not passing) | Nothing yet. At most, one **pre-registered** confirmatory test on bars after 2026-03-25 once the owner's feed exists. It must be a single test, so no correction applies, and it needs at least 2 years of new bars, since the CI half-width is about 0.1. | The same R²-against-EWMA test, run once, with the rule written down before the data is seen. |

## Reproduce

Python 3.11.15, pandas 3.0.5, scikit-learn 1.9.1, scipy 1.17.1, numpy 2.4.6.
Base: `f514a125` (after `git merge claude/add-new-skills-lys862`).
`data/XAUUSD_40Y.csv` sha256 prefix `7ffc2bf583972eef`. The results are
deterministic (seed 42), and the main run takes about 2 minutes on 4 shared
cores.

```bash
# main run: all 52 tests, one Bonferroni family (writes results_1_3_4_5.json)
python scripts/research/a0_target_research.py --out /tmp/a0-research --families 1,3,4,5

# cost sensitivity for strategies (families 4-5 at 0 bp)
python scripts/research/a0_target_research.py --out /tmp/a0-research/cost0 --families 4,5 --cost-bps 0

# replication on the earlier, disjoint OOS window 2010-03-24 .. 2018-03-23
python scripts/research/a0_target_research.py --out /tmp/a0-research --families 3 --truncate-at 2018-03-26
python scripts/research/a0_target_research.py --out /tmp/a0-research --families 1 --truncate-at 2018-03-26
```

The look-ahead check (`/tmp/a0-research/lookahead_check.py`) is scratch, and
this document records its output above. It imports `build_features`,
`fwd_log_return` and `strategy_returns` from the script.

## Limits of this spike

- **One instrument and daily bars only.** There is no intraday source offline.
  Intraday microstructure signal is **not** ruled out here. It is simply
  unmeasurable without the feed.
- **Macro:** the offline CSVs start on 2021-03-29, with DXY, US2Y, US10Y, VIX
  and the gold ETF flow. There is no TIPS or breakeven series, so there is no
  true real-rate proxy. The nominal 10y rule was tested on 2021–26 only
  (~5 years), which has low power: its ΔSharpe CI is [−1.12, +0.27].
- **Financing and swap costs are ignored** on both sides. They would count
  against the higher-exposure arms, including buy-and-hold and vol targeting,
  on a CFD.
- **Bonferroni is conservative** because the 52 tests are correlated. The
  conclusions do not depend on this: every test that passes has p ≤ 0.025
  after correction, and the nearest failure (row 9) reverses on the
  replication window, so a milder correction such as Holm or BH would not
  produce a new finding that holds up.
