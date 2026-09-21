# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_regime_conditional.py
========================================
`ml/regime_conditional.py` was 424 statements at 44.15 %.

Despite the name, this is not offline training code. `ml/signal_filter.py`
imports it, and `execution/trade_executor.py` imports *that* — so the regime
classification here runs on the live trade path.

The part worth pinning is the **parabolic-bubble override**. The module's own
docstrings record why it exists: walk-forward Fold-2 scored 44.4 % accuracy
because momentum and trend features become *anti-predictive* once price
discovery breaks down — a parabolic blow-off, or the crash after one. So
`REGIME_HIGH_VOL_PARABOLIC` supersedes every other label, and the two
conditions that trigger it are thresholds a future editor could "tidy" without
realising they encode a measured failure:

* price > 1.30x its 200-bar moving average (blow-off), or
* 14-bar realised vol > 2.5x the 90-bar figure **and** price ≥ 25 % below the
  200-bar peak (post-bubble crash).

Both are asserted at the boundary, and — critically — `_detect_parabolic_mask`
shifts every rolling statistic by one bar. Without that lag the detector reads
the current bar's own close through its own moving average, which is lookahead:
a backtest would "detect" the bubble on the bar that formed it. The no-lookahead
property is asserted directly by truncating the future.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.regime_conditional import (
    REGIME_HIGH_VOL_PARABOLIC,
    REGIME_MEAN_REVERTING,
    REGIME_MIXED,
    REGIME_NAMES,
    REGIME_TRENDING,
    _detect_parabolic_mask,
    add_regime_features,
    detect_regime_labels,
    is_parabolic_bubble_regime,
)

pytestmark = pytest.mark.unit


def _closes(values):
    return pd.DataFrame(
        {"close": [float(v) for v in values]},
        index=pd.date_range("2024-01-01", periods=len(values), freq="h"),
    )


def _calm(n=300, level=2000.0, seed=0):
    rng = np.random.default_rng(seed)
    return _closes(level + rng.normal(0, 2, n))


def _blowoff(n=300, level=2000.0):
    """A flat base, then a near-vertical run well past 1.30x the mean."""
    base = [level] * (n - 30)
    spike = list(np.linspace(level, level * 2.2, 30))
    return _closes(base + spike)


def _post_bubble(n=300, level=4000.0):
    """A series that actually satisfies condition 2.

    Condition 2 needs rv14 > 2.5 x rv90 while price sits >= 25 % below the
    200-bar peak. Because the 14 crash bars are *inside* the 90-bar window,
    that ratio is mathematically capped (see TestConditionTwoIsNearlyUnreachable),
    so the only way to clear 2.5 is for the preceding 76 returns to be nearly
    constant *and* centred on the same mean as the crash: a steady grind down,
    then violent chop at the same average pace.
    """
    rng = np.random.default_rng(7)
    rate = -0.004
    steady = [level]
    for _ in range(n - 15):
        steady.append(steady[-1] * np.exp(rate))
    noise = rng.normal(0, 0.06, 14)
    noise -= noise.mean()
    chop, price = [], steady[-1]
    for e in noise:
        price *= np.exp(rate + e)
        chop.append(price)
    return _closes(steady + chop)


def _regime_frame(hurst=None, adx=None, n=50, closes=None):
    data = {}
    if hurst is not None:
        data["regime_hurst"] = [hurst] * n
    if adx is not None:
        data["regime_trend_str"] = [adx] * n
    if closes is not None:
        data["close"] = closes
    return pd.DataFrame(data, index=pd.date_range("2024-01-01", periods=n, freq="h"))


# ── the parabolic detector, last-bar form ─────────────────────────────────────


class TestIsParabolicBubbleRegime:
    def test_a_calm_market_is_not_parabolic(self):
        assert is_parabolic_bubble_regime(_calm()) is False

    def test_a_blow_off_is_parabolic(self):
        assert is_parabolic_bubble_regime(_blowoff()) is True

    def test_a_post_bubble_crash_is_parabolic(self):
        assert is_parabolic_bubble_regime(_post_bubble()) is True

    def test_a_missing_close_column_is_not_parabolic(self):
        """Absence of data is not evidence of a bubble."""
        assert is_parabolic_bubble_regime(pd.DataFrame({"open": [1.0] * 100})) is False

    def test_too_few_bars_is_not_parabolic(self):
        assert is_parabolic_bubble_regime(_calm(n=5)) is False

    def test_a_non_positive_last_price_is_not_parabolic(self):
        frame = _calm(100)
        frame.loc[frame.index[-1], "close"] = 0.0

        assert is_parabolic_bubble_regime(frame) is False

    def test_the_ma_ratio_threshold_is_honoured(self):
        """1.30x is a measured threshold, not a round number to nudge."""
        n = 250
        below = _closes([100.0] * (n - 1) + [128.0])  # ~1.28x
        above = _closes([100.0] * (n - 1) + [140.0])  # ~1.40x

        assert is_parabolic_bubble_regime(below) is False
        assert is_parabolic_bubble_regime(above) is True

    def test_a_custom_close_column_is_honoured(self):
        frame = _blowoff().rename(columns={"close": "px"})

        assert is_parabolic_bubble_regime(frame, close_col="px") is True

    def test_a_corrupt_frame_is_not_parabolic_rather_than_raising(self):
        frame = pd.DataFrame({"close": ["a", "b", "c"] * 40})

        assert is_parabolic_bubble_regime(frame) is False

    def test_the_result_is_a_python_bool(self):
        assert type(is_parabolic_bubble_regime(_calm())) is bool


class TestConditionTwoIsNearlyUnreachable:
    """The post-bubble-crash arm of the detector has almost no room to fire.

    `rv14` is the standard deviation of the last 14 log returns; `rv90` is the
    standard deviation of the last 90 — a set that *contains* those same 14.
    Adding 76 further points can only be minimised, never removed, so

        rv14 / rv90  <=  sqrt(90 / 14)  =  2.5355...

    is a hard mathematical ceiling. The configured threshold is 2.5, which
    leaves a window 1.4 % wide at the very top of the achievable range, and
    reaching it requires the preceding 76 returns to be almost perfectly
    constant *and* centred on the crash's own mean.

    In practice condition 1 (price > 1.30x its 200-bar MA) does essentially all
    the work, and this arm fires only in a near-degenerate configuration. That
    is recorded here rather than silently retuned: the threshold sits on a
    money-moving path and changing it is a trading decision, not a cleanup.
    """

    def test_the_ratio_has_a_mathematical_ceiling(self):
        """No series can exceed sqrt(90/14), whatever its shape."""
        rng = np.random.default_rng(0)
        ceiling = np.sqrt(90 / 14)

        worst = 0.0
        for scale in (0.001, 0.01, 0.1, 1.0):
            for _ in range(40):
                returns = np.concatenate([np.zeros(76), rng.normal(0, scale, 14)])
                rv14 = np.std(returns[-14:])
                rv90 = np.std(returns)
                if rv90 > 0:
                    worst = max(worst, rv14 / rv90)

        assert worst <= ceiling + 1e-9

    def test_the_configured_threshold_sits_just_under_that_ceiling(self):
        from ml.regime_conditional import _PARABOLIC_RV_RATIO

        ceiling = np.sqrt(90 / 14)

        assert ceiling > _PARABOLIC_RV_RATIO
        assert (ceiling - _PARABOLIC_RV_RATIO) / ceiling < 0.02

    def test_an_ordinary_crash_does_not_clear_it(self):
        """A bubble followed by a normal violent crash is NOT flagged by arm 2."""
        rng = np.random.default_rng(1)
        base = list(2000 + rng.normal(0, 1, 240))
        up = list(np.linspace(2000, 3800, 30))
        crash = list(np.linspace(3800, 1800, 30) + rng.normal(0, 40, 30))
        closes = np.array(base + up + crash)

        returns = np.diff(np.log(closes))
        ratio = np.std(returns[-14:]) / np.std(returns[-90:])

        assert ratio < 2.5

    def test_condition_one_is_what_actually_fires_in_practice(self):
        """The blow-off arm catches the bubble; the crash arm needs the edge case."""
        assert is_parabolic_bubble_regime(_blowoff()) is True


# ── the parabolic detector, vectorised form ───────────────────────────────────


class TestDetectParabolicMask:
    def test_it_returns_one_flag_per_bar(self):
        frame = _calm(200)

        assert len(_detect_parabolic_mask(frame)) == len(frame)

    def test_a_calm_market_flags_nothing(self):
        assert not _detect_parabolic_mask(_calm(300)).any()

    def test_a_blow_off_flags_its_tail(self):
        mask = _detect_parabolic_mask(_blowoff(300))

        assert mask.any()
        assert bool(mask.iloc[-1]) is True

    def test_the_warmup_period_is_never_flagged(self):
        """Rolling stats need min_periods; before that there is nothing to judge."""
        mask = _detect_parabolic_mask(_blowoff(300))

        assert not mask.iloc[:10].any()

    def test_the_mask_is_boolean(self):
        assert _detect_parabolic_mask(_calm(200)).dtype == bool

    def test_it_carries_no_nan(self):
        assert not _detect_parabolic_mask(_calm(200)).isna().any()

    def test_it_does_not_look_ahead(self):
        """Every rolling statistic is shifted by one bar.

        Without the lag the detector reads the current bar's own close through
        its own moving average, and a backtest would flag the bubble on the bar
        that formed it. Truncating the future must leave earlier flags alone.
        """
        frame = _blowoff(300)
        full = _detect_parabolic_mask(frame)
        truncated = _detect_parabolic_mask(frame.iloc[:250])

        pd.testing.assert_series_equal(full.iloc[:250], truncated, check_names=False)

    def test_a_zero_close_does_not_produce_nan_flags(self):
        frame = _calm(200)
        frame.loc[frame.index[50], "close"] = 0.0

        mask = _detect_parabolic_mask(frame)

        assert not mask.isna().any()


# ── regime labelling ──────────────────────────────────────────────────────────


class TestDetectRegimeLabels:
    def test_low_hurst_and_low_adx_is_mean_reverting(self):
        labels = detect_regime_labels(_regime_frame(hurst=0.30, adx=0.10))

        assert (labels == REGIME_MEAN_REVERTING).all()

    def test_high_hurst_and_high_adx_is_trending(self):
        labels = detect_regime_labels(_regime_frame(hurst=0.70, adx=0.40))

        assert (labels == REGIME_TRENDING).all()

    def test_the_middle_ground_is_mixed(self):
        labels = detect_regime_labels(_regime_frame(hurst=0.50, adx=0.22))

        assert (labels == REGIME_MIXED).all()

    def test_hurst_alone_still_classifies(self):
        assert (detect_regime_labels(_regime_frame(hurst=0.30)) == REGIME_MEAN_REVERTING).all()
        assert (detect_regime_labels(_regime_frame(hurst=0.70)) == REGIME_TRENDING).all()

    def test_adx_alone_still_classifies(self):
        assert (detect_regime_labels(_regime_frame(adx=0.10)) == REGIME_MEAN_REVERTING).all()
        assert (detect_regime_labels(_regime_frame(adx=0.40)) == REGIME_TRENDING).all()

    def test_neither_column_falls_back_to_mixed(self):
        """Everything-mixed is the honest answer, and it warns."""
        frame = pd.DataFrame({"other": [1.0] * 50})

        assert (detect_regime_labels(frame) == REGIME_MIXED).all()

    def test_one_label_per_row(self):
        frame = _regime_frame(hurst=0.5, adx=0.2, n=37)

        assert len(detect_regime_labels(frame)) == 37

    def test_labels_are_integers(self):
        labels = detect_regime_labels(_regime_frame(hurst=0.5, adx=0.2))

        assert labels.dtype == int

    def test_only_known_labels_are_emitted(self):
        labels = detect_regime_labels(_regime_frame(hurst=0.5, adx=0.2))

        assert set(labels.unique()) <= set(REGIME_NAMES)

    def test_the_parabolic_override_supersedes_trending(self):
        """The whole point: a blow-off must not be scored as a healthy trend."""
        closes = _blowoff(300)["close"].tolist()
        frame = _regime_frame(hurst=0.70, adx=0.40, n=300, closes=closes)

        labels = detect_regime_labels(frame)

        assert labels.iloc[-1] == REGIME_HIGH_VOL_PARABOLIC

    def test_the_parabolic_override_supersedes_mean_reverting(self):
        closes = _blowoff(300)["close"].tolist()
        frame = _regime_frame(hurst=0.30, adx=0.10, n=300, closes=closes)

        assert detect_regime_labels(frame).iloc[-1] == REGIME_HIGH_VOL_PARABOLIC

    def test_a_calm_market_is_never_overridden(self):
        closes = _calm(300)["close"].tolist()
        frame = _regime_frame(hurst=0.70, adx=0.40, n=300, closes=closes)

        assert (detect_regime_labels(frame) == REGIME_TRENDING).all()

    def test_without_a_close_column_no_override_is_attempted(self):
        frame = _regime_frame(hurst=0.70, adx=0.40)

        assert (detect_regime_labels(frame) == REGIME_TRENDING).all()

    def test_custom_column_names_are_honoured(self):
        frame = pd.DataFrame({"h": [0.30] * 50, "a": [0.10] * 50})

        labels = detect_regime_labels(frame, hurst_col="h", adx_col="a")

        assert (labels == REGIME_MEAN_REVERTING).all()


class TestRegimeConstants:
    def test_the_four_regimes_are_distinct(self):
        assert len({REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED, REGIME_HIGH_VOL_PARABOLIC}) == 4

    def test_every_regime_has_a_name(self):
        for value in (REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED, REGIME_HIGH_VOL_PARABOLIC):
            assert value in REGIME_NAMES

    def test_the_parabolic_regime_is_named_for_what_it_is(self):
        assert "parabolic" in REGIME_NAMES[REGIME_HIGH_VOL_PARABOLIC].lower()


# ── regime feature construction ───────────────────────────────────────────────


def _ohlcv(n=300, seed=0):
    rng = np.random.default_rng(seed)
    closes = 2000 + np.cumsum(rng.normal(0, 5, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + np.abs(rng.normal(0, 3, n)),
            "low": closes - np.abs(rng.normal(0, 3, n)),
            "close": closes,
            "volume": rng.integers(100, 1000, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


class TestAddRegimeFeatures:
    def test_it_adds_both_regime_columns(self):
        result = add_regime_features(_ohlcv())

        assert "regime_hurst" in result.columns
        assert "regime_trend_str" in result.columns

    def test_it_preserves_the_row_count(self):
        bars = _ohlcv()

        assert len(add_regime_features(bars)) == len(bars)

    def test_the_hurst_column_is_a_unit_interval(self):
        hurst = add_regime_features(_ohlcv())["regime_hurst"]

        assert hurst.min() >= 0.0
        assert hurst.max() <= 1.0

    def test_the_trend_strength_is_a_unit_interval(self):
        strength = add_regime_features(_ohlcv())["regime_trend_str"]

        assert strength.min() >= 0.0
        assert strength.max() <= 1.0

    def test_the_output_is_finite(self):
        result = add_regime_features(_ohlcv())

        for col in ("regime_hurst", "regime_trend_str"):
            assert np.all(np.isfinite(result[col].to_numpy()))

    def test_the_caller_s_frame_is_not_mutated(self):
        bars = _ohlcv()
        before = list(bars.columns)

        add_regime_features(bars)

        assert list(bars.columns) == before

    def test_the_result_feeds_the_labeller(self):
        """The two halves have to agree on column names to work together."""
        labels = detect_regime_labels(add_regime_features(_ohlcv()))

        assert set(labels.unique()) <= set(REGIME_NAMES)

    def test_a_short_frame_is_tolerated(self):
        assert len(add_regime_features(_ohlcv(30))) == 30
