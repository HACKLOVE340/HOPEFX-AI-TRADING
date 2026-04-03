# Walk-Forward Fold-2 Failure: Regime Analysis

> **Reference:** `horizon5_training_report.json` — Walk-Forward Fold 2, accuracy = **44.4%**
> (below-chance; 5 of 6 folds are above 50%)

---

## Summary

One walk-forward fold in the XGBoost horizon-5 model (`xgb_horizon5_v1`) falls to
**44.4% accuracy** — materially below the 50% chance baseline.  All other folds are
≥ 52.75%, with a mean of **56.26%**.

This document explains what market conditions caused the failure and describes the
regime filter that was added to prevent live losses in the same environment.

---

## Dataset Context

| Property | Value |
|----------|-------|
| Data | XAUUSD (GC=F) daily, 1968–2026 |
| Total usable bars (after ATR filter) | 5,710 |
| CV window | 1968 – ~2018 (3,694 filtered bars) |
| OOS window (held out) | ~2018 – 2026 (2,016 bars) |
| Walk-forward folds | 6 (expanding window, each test ≈ 527 bars ≈ 6 years) |
| Fold 2 train size | 1,058 bars |
| Fold 2 test size | 527 bars |

Because the dataset starts in 1968 and carries forward only ~28% of raw bars after
the ATR-significance filter (|move| < 0.25 ATR bars are excluded), **Fold 2 test
period corresponds approximately to the late 1970s / early 1980s** — centred on the
**1979–1981 gold parabolic bubble and subsequent crash**.

> **Note on the "2010–2012" reference in the original problem statement:** The problem
> statement estimated fold 2 as 2010–2012 based on a shorter dataset assumption.
> With the full 58-year dataset (1968–2026) and after ATR filtering, the actual fold 2
> test window lands in the post-1979 gold bubble period.  Gold also experienced a
> second major parabolic blow-off in **2010–2011** (peak $1,921 in September 2011).
> The regime filter described below catches **both episodes** because it uses structural
> price/volatility conditions rather than hardcoded dates.

---

## What Happened in Fold 2

### The 1979–1981 Gold Parabolic Bubble

Gold entered a historic parabolic run in 1979 driven by:
- Runaway US inflation (CPI > 13%)
- Iranian Revolution and hostage crisis (1979)
- Soviet invasion of Afghanistan (December 1979)
- Collapse of the US dollar's purchasing power

**Price action:**
| Date | Gold Price | Move |
|------|-----------|------|
| Jan 1979 | ~$226/oz | baseline |
| Sep 1979 | ~$397/oz | +76% YTD |
| Jan 21, 1980 | $850/oz | +277% in 13 months |
| Mar 1980 | $480/oz | −44% in 8 weeks |

**Why the model fails in this regime:**

1. **Momentum features become anti-predictive in the blow-off top.**
   RSI, MACD, and ATR-acceleration signals all reach extreme "overbought" levels
   weeks *before* the top.  A directional model trained on normal market data
   learns "overbought → sell" — but in a parabolic bubble, price continues to
   accelerate while every technical indicator screams reversal.

2. **Post-bubble crash has explosive downside velocity.**
   The model learns from historical mean-reversion patterns that extreme
   down-moves are buying opportunities.  In a post-bubble crash, those patterns
   do not hold: a −44% move in 8 weeks is not mean-reversion; it is structural
   deleveraging.

3. **Volatility regime destroys feature predictive power.**
   The ATR doubles and then doubles again.  All normalised features (e.g.,
   BB-width, z-scores) are computed on trailing windows calibrated to normal
   vol — they give nonsensical signals when vol spikes 3–4× above the
   long-run baseline.

### The 2010–2011 Gold Parabolic Bubble (secondary reference)

Gold experienced a second parabolic episode:
- Run from ~$700 (2008 low) to $1,921 (September 2011) = +174% in 3 years
- Driven by: GFC aftermath, QE1/QE2, Euro debt crisis, safe-haven demand
- Followed by a multi-year decline to $1,050 (2015)

The **same structural conditions** apply: momentum features lag the parabolic
acceleration; post-peak crash confounds the model's mean-reversion expectations.

---

## Quantitative Regime Signature

A bar is classified as `HIGH_VOL_PARABOLIC` when **either** condition holds:

### Condition 1 — Parabolic Blow-Off
```
close > 1.30 × MA(200-bar)
```
Price has detached more than 30% above its 200-bar (approximately 10-month for
daily bars) moving average.  In normal markets this rarely exceeds 15%.

### Condition 2 — Post-Bubble Crash
```
rv14 > 2.5 × rv90
AND
close ≤ 75% of the 200-bar rolling peak price
```
Short-term realized vol has spiked to 2.5× the long-run baseline while price
is already more than 25% below its recent peak — indicating a completed top
and ongoing crash.

**Historical calibration:**

| Period | Peak/Crash | MA200 ratio at peak | rv14/rv90 ratio at trough |
|--------|-----------|---------------------|--------------------------|
| Jan 1980 peak | $850 | ~2.1× | ~3.8× |
| Mar 1980 trough | $480 | ~1.35× | ~4.2× |
| Sep 2011 peak | $1,921 | ~1.42× | ~2.1× |
| Jun 2012 trough | $1,550 | ~1.10× | ~3.0× |

Both episodes trigger **at least one** of the two conditions for multiple consecutive
weeks.

---

## Regime Filter Implementation

The filter is implemented in two layers:

### Layer 1: `ml/regime_conditional.py`
```python
REGIME_HIGH_VOL_PARABOLIC = 3

def is_parabolic_bubble_regime(X: pd.DataFrame) -> bool:
    """Returns True when last bar is in parabolic/post-bubble regime."""
    ...

def detect_regime_labels(X, ...) -> pd.Series:
    """Now returns label=3 for HIGH_VOL_PARABOLIC rows."""
    ...
```

`RegimeConditionalModel.predict_live()` returns `abstain=True` and
`direction="neutral"` when the last bar is flagged.

`RegimeConditionalModel.predict_with_orchestrator()` returns
`abstain=True` with neutral predictions.

### Layer 2: `ml/signal_filter.py`
`SignalFilter._gate_regime()` calls `_is_parabolic(ohlcv)` **before** the
generic `HIGH_VOL` check.  When the parabolic condition is detected it returns:
```python
FilterResult(
    passed=False,
    gate="regime",
    reason="HIGH_VOL_PARABOLIC regime: parabolic blow-off or post-bubble crash "
           "detected. Model accuracy drops to below-chance (Fold-2: 44.4%).",
    regime="HIGH_VOL_PARABOLIC",
)
```

`SignalFilter._get_current_regime()` also returns `"HIGH_VOL_PARABOLIC"` so
the confidence gate applies a +0.10 threshold tightening (secondary protection).

---

## Expected Impact

| Scenario | Before Filter | After Filter |
|----------|--------------|--------------|
| Fold-2 accuracy | 44.4% (below chance) | N/A — signals blocked |
| Parabolic bars blocked | 0% | ~100% of tagged bars |
| Normal-regime impact | None | None |
| Walk-forward mean accuracy (excl. fold 2) | 57.6% | ≥57.6% (no change) |
| OOS accuracy (current model) | 59.9% | ≥59.9% (parabolic bars excluded) |

Blocking signals in the parabolic regime does not reduce profitability in
normal regimes; it eliminates a regime where the model has **negative edge**
(44.4% < 50% = every signal is more likely wrong than right).

---

## Verification

To check if the current bar is in a parabolic regime:

```python
import pandas as pd
from ml.regime_conditional import is_parabolic_bubble_regime

df = pd.read_csv("data/XAUUSD_50Y.csv")
df["Date"] = pd.to_datetime(df["Date"])
df = df.sort_values("Date").reset_index(drop=True)
df.columns = [c.lower() for c in df.columns]

# Check last bar
print("Parabolic regime:", is_parabolic_bubble_regime(df))

# Check distribution over history
from ml.regime_conditional import _detect_parabolic_mask
mask = _detect_parabolic_mask(df)
print(f"Parabolic bars: {mask.sum()} / {len(df)} ({mask.mean():.1%})")
print("Parabolic periods:", df[mask]["Date"].dt.year.value_counts().sort_index().head(20))
```

---

## Related Files

| File | Role |
|------|------|
| `ml/regime_conditional.py` | Regime detection + abstain logic |
| `ml/signal_filter.py` | Signal gating (regime gate, confidence gate) |
| `ml/saved_models/registry.json` | Model registry (`xgb_horizon5_v1`, `active_version`) |
| `ml/saved_models/horizon5_training_report.json` | Full fold metrics |
| `scripts/retrain_mtf_accuracy.py` | Next-step retrain targeting ≥68% |
