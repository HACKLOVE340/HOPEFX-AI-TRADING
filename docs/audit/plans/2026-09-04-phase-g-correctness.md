# Phase G — Correctness bugs · Implementation Plan

> **For agentic workers:** steps use checkbox (`- [ ]`) syntax. Each task ends
> with a red-green test cycle and a commit.

**Goal:** fix six defects that produce a wrong number or a wrong action, each
isolated enough to prove individually.

**Spec:** `docs/audit/CODE_READING_FINDINGS.md` (F80, F81, F119, F120, F125, F145)
**Ordering:** `docs/audit/FIX_PHASES.md`

## Global constraints

- Branch `claude/add-new-skills-lys862`. Never `--no-verify`.
- `ruff check .` clean; `pre-commit run --all-files` before every commit.
- **Never weaken a risk gate, kill switch, or staleness/drift check.**
- Every fix gets a test that is **red on the current tree** and green after.
- Money math: read `hopefx-money-precision` before touching a price, size or
  P&L path. Metrics: `risk-metrics-calculation`.

## Ordering rationale

Two of these move money on a live path and are done first. F145 changes what
the model sees on every prediction, so it comes before the reported-metric
work. The three metric bugs are last: they are wrong numbers on a screen, not
wrong actions.

| # | Finding | Sev | One line |
|---|---------|-----|----------|
| 1 | F81 | CRITICAL | Hedge marked active before the order; never rolled back |
| 2 | F80 | CRITICAL | A headline containing "coupon" opens a real short on gold |
| 3 | F145 | CRITICAL | Missing features zero-filled **before** scaling → −15σ |
| 4 | F119 | HIGH | Annualised return treats hourly bars as days; ~34× low |
| 5 | F120 | MEDIUM | Sortino denominator is the wrong statistic, both engines |
| 6 | F125 | MEDIUM | Regime EMA folded newest→oldest; oldest bar weighs 7.4× |

---

### Task 1 — F81: a hedge that was not placed must not be reported as placed

**Files:** `risk/orchestrator.py:306-365`, `api/nuclear.py:258-270`,
`brain/nuclear_supervisor.py:647-670`
**Test:** `tests/unit/test_hedge_state_matches_reality.py`

`_hedge_active = True` is set at :318, *before* the broker call at :325. A
raise is caught and logged (:334), and the `HedgePosition` is appended anyway
with `order_id=None`. The retry guard at :314 then returns early forever. The
account is unhedged during the event the hedge exists for, and every dashboard
says "hedged".

- [ ] Test: a broker that raises leaves `_hedge_active` False and appends no position.
- [ ] Test: a second call after a failure actually retries (the guard must not latch).
- [ ] Test: with no broker, no `HedgePosition` is recorded.
- [ ] Test: a successful placement still sets the flag, the position and the gauge.
- [ ] Test: the endpoint does not return `status: "ok"` for a hedge that failed.
- [ ] Implement: `activate_hedge_mode() -> bool`; state mutated only after a
      confirmed order id; failure logged at ERROR and alerted; distinct
      `activate_hedge_failed` event recorded.
- [ ] Commit.

### Task 2 — F80: word-boundary matching in the wordmap scorer

**Files:** `news/nuclear_wordmap_scorer.py:275-290`
**Test:** `tests/unit/test_wordmap_matches_words_not_substrings.py`

`if term in text_lower:` matches "coup" inside "coupon" (severity 7 → hedge
mode → a real short), "nuclear war" inside "nuclear warning", "depression"
inside "tropical depression". The trigger text arrives from public news, so
this is attacker-influenceable, not merely accident-prone.

- [ ] Test: each of the five verified false positives scores 0 / `normal`.
- [ ] Test: the true positives still match ("a coup in", "nuclear war", …),
      including multi-word terms and terms adjacent to punctuation.
- [ ] Test: matching stays case-insensitive.
- [ ] Implement: compile each term to `\b<escaped>\b` once at load; keep the
      existing normalisation. Do not change any weight.
- [ ] Commit.

### Task 3 — F145: fill missing features after scaling, and refuse on low coverage

**Files:** `ml/__init__.py:311-350`
**Test:** `tests/unit/test_missing_features_are_neutral_not_extreme.py`

Missing columns are set to `0.0` in **raw** space and the scaler runs
afterwards, so the model receives `z = (0 - mean)/std` — −15σ for a price
column, −3.3σ for RSI. With 48.2% of the vector missing (F24) the model is
handed a confident description of a market that has never existed.

- [ ] Test: a missing feature reaches the model at the training mean (z≈0), not
      at `-mean/std`.
- [ ] Test: a present feature is scaled exactly as before (no regression).
- [ ] Test: `scaler.transform` raising no longer passes the **unscaled** frame
      to the learners.
- [ ] Implement: mark which columns were absent, scale, then set those columns
      to 0.0 in scaled space; on scaler failure, refuse rather than fall back.
- [ ] Commit.

### Task 4 — F119: annualised return and Calmar

**Files:** `backtesting/engine_config.py:1026-1027`
**Test:** `tests/unit/test_annualised_return_uses_days_not_bars.py`

`(1 + total_return) ** (252.0 / len(equity_values)) - 1` uses a **bar** count
where a **day** count belongs. The same function divides by `bars_per_day`
correctly at :990, :1008 and :1009 — line 1026 is the one place it was omitted.
A strategy that doubled capital in a year reports 2.93%.

- [ ] Test: one year of hourly bars at +100% reports ≈100%, not 2.93%.
- [ ] Test: Calmar equals the corrected annual return over max drawdown.
- [ ] Test: a daily-bar config (`bars_per_day=1`) is unchanged.
- [ ] Implement: divide the bar count by `self.config.bars_per_day`.
- [ ] Commit.

### Task 5 — F120: the Sortino denominator

**Files:** `backtesting/metrics.py:135-142`, `backtesting/engine_config.py:1018-1023`
**Test:** `tests/unit/test_sortino_uses_downside_deviation.py`

Both engines use `returns[returns < 0].std()` — the dispersion *among the
losses*, about the mean loss, over only the losing periods. Downside deviation
is `sqrt(mean(min(r - target, 0)**2))`: about the **target**, over **all**
periods. The bias flips sign with the shape of the distribution, so the number
is not Sortino at all rather than wrong in one direction.

- [ ] Test: against a hand-computed downside deviation on a fixed series.
- [ ] Test: a series with no losing period does not divide by zero.
- [ ] Test: both engines return the same Sortino for the same returns.
- [ ] Implement: `sqrt(mean(minimum(r - target, 0) ** 2))` in both, target 0.
- [ ] Commit.

### Task 6 — F125: the regime EMA is folded backwards

**Files:** `api/trading.py:3788-3794`
**Test:** `tests/unit/test_regime_ema_weights_recent_bars.py`

`for c in reversed(closes[-20:])` folds newest first, so the value entering
last carries the full 0.1 coefficient: the oldest bar in the window weighs
7.4× the newest. Classification is not reversed — the badge still says "up" in
an uptrend — but the indicator lags badly and the displayed `confidence` is
derived from a spread that is not a 20/50 EMA spread.

- [ ] Test: on a rising series the EMA is nearer the newest close than the
      oldest (this is what fails today).
- [ ] Test: against a hand-computed EMA on a fixed series.
- [ ] Implement: drop `reversed()`; seed from the first bar of the window.
- [ ] Commit.

### Task 7 — Verify

- [ ] Fresh worktree with `static/` copied in; full fast suite; failure set
      diffed against the 17294-pass baseline.
- [ ] Update `CODE_READING_FINDINGS.md` and `FIX_PHASES.md`; push.
