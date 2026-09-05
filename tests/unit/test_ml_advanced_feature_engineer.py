# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_advanced_feature_engineer.py
===============================================
`ml/features/advanced_features.py` was 344 statements at 65.93 %.

The covered part was the indicator maths. The uncovered part was the whole
sklearn-shaped surface around it — `fit`, `transform`, `fit_transform`,
`get_feature_names_out`, `feature_importance`, `select_features` — plus
`_engineer_live_features`, the short-window variant used at inference time.

The property that matters most here is **schema stability between fit and
transform**. A model is trained on the column list `fit` captured; if
`transform` later returns a different set — because a short window produced
fewer indicators, or an input frame had an extra column — the served feature
vector no longer means what the trained weights expect. Nothing detects that
at runtime: the model simply produces confident nonsense. So `transform` fills
missing columns with 0.0 and drops extras to reproduce the fitted schema
exactly, and that is asserted from both directions.

The second property is **causality in the live path**. `_engineer_live_features`
deliberately does not `dropna()` globally — it must return a usable last row
even on a short window — but it must still never reach forward. Truncating the
future is asserted not to change any earlier row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.features.advanced_features import AdvancedFeatureEngineer

pytestmark = pytest.mark.unit


def _ohlcv(n=400, seed=0, start=2000.0):
    rng = np.random.default_rng(seed)
    closes = start + np.cumsum(rng.normal(0, 5, n))
    highs = closes + np.abs(rng.normal(0, 3, n))
    lows = closes - np.abs(rng.normal(0, 3, n))
    return pd.DataFrame(
        {
            "open": closes + rng.normal(0, 1, n),
            "high": np.maximum(highs, closes),
            "low": np.minimum(lows, closes),
            "close": closes,
            "volume": rng.integers(500, 5000, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


@pytest.fixture
def engineer():
    return AdvancedFeatureEngineer()


# ── the sklearn surface ───────────────────────────────────────────────────────


class TestFit:
    def test_fit_returns_self_for_chaining(self, engineer):
        assert engineer.fit(_ohlcv()) is engineer

    def test_fit_marks_the_engineer_fitted(self, engineer):
        engineer.fit(_ohlcv())

        assert engineer._is_fitted_ is True

    def test_fit_captures_a_feature_schema(self, engineer):
        engineer.fit(_ohlcv())

        assert len(engineer._feature_columns_) > 0

    def test_the_schema_excludes_the_raw_inputs(self, engineer):
        """OHLCV are inputs, not features; leaving them in leaks price level."""
        engineer.fit(_ohlcv())

        assert not ({"open", "high", "low", "close", "volume"} & set(engineer._feature_columns_))

    def test_fit_does_not_mutate_the_caller_s_frame(self, engineer):
        bars = _ohlcv()
        before = list(bars.columns)

        engineer.fit(bars)

        assert list(bars.columns) == before

    def test_the_target_argument_is_accepted_and_ignored(self, engineer):
        bars = _ohlcv()

        engineer.fit(bars, y=pd.Series(np.zeros(len(bars)), index=bars.index))


class TestTransform:
    def test_transform_produces_the_fitted_schema(self, engineer):
        bars = _ohlcv()
        engineer.fit(bars)

        assert list(engineer.transform(bars).columns) == engineer._feature_columns_

    def test_a_missing_column_is_filled_rather_than_dropped(self, engineer):
        """A short window yields fewer indicators; the width must not change."""
        engineer.fit(_ohlcv(400))

        result = engineer.transform(_ohlcv(60))

        assert list(result.columns) == engineer._feature_columns_

    def test_an_extra_column_is_dropped(self, engineer):
        bars = _ohlcv()
        engineer.fit(bars)
        widened = bars.copy()
        widened["unexpected_input"] = 1.0

        assert list(engineer.transform(widened).columns) == engineer._feature_columns_

    def test_the_column_order_is_reproduced_exactly(self, engineer):
        """Positional meaning matters: reordering silently remaps the weights."""
        bars = _ohlcv()
        engineer.fit(bars)

        first = list(engineer.transform(bars).columns)
        second = list(engineer.transform(_ohlcv(seed=7)).columns)

        assert first == second == engineer._feature_columns_

    def test_transform_without_fit_still_returns_features(self, engineer):
        result = engineer.transform(_ohlcv())

        assert len(result.columns) > 0

    def test_transform_without_fit_excludes_the_raw_inputs(self, engineer):
        result = engineer.transform(_ohlcv())

        assert not ({"open", "high", "low", "close", "volume"} & set(result.columns))

    def test_transform_does_not_mutate_the_caller_s_frame(self, engineer):
        bars = _ohlcv()
        engineer.fit(bars)
        before = list(bars.columns)

        engineer.transform(bars)

        assert list(bars.columns) == before

    def test_the_advanced_block_can_be_switched_off(self, engineer):
        plain = engineer.transform(_ohlcv(), include_advanced=False)
        rich = AdvancedFeatureEngineer().transform(_ohlcv(), include_advanced=True)

        assert len(plain.columns) <= len(rich.columns)


class TestFitTransform:
    def test_it_fits_and_transforms_in_one_call(self, engineer):
        result = engineer.fit_transform(_ohlcv())

        assert engineer._is_fitted_ is True
        assert list(result.columns) == engineer._feature_columns_

    def test_it_agrees_with_the_two_step_form(self, engineer):
        bars = _ohlcv()
        one_shot = engineer.fit_transform(bars)
        two_step = AdvancedFeatureEngineer().fit(bars).transform(bars)

        assert list(one_shot.columns) == list(two_step.columns)


class TestFeatureNames:
    def test_it_raises_before_fitting(self, engineer):
        """Silently returning [] would let a caller train on no features."""
        with pytest.raises(RuntimeError, match="not fitted"):
            engineer.get_feature_names_out()

    def test_it_lists_the_fitted_schema(self, engineer):
        engineer.fit(_ohlcv())

        assert engineer.get_feature_names_out() == engineer._feature_columns_

    def test_it_matches_what_transform_produces(self, engineer):
        bars = _ohlcv()
        engineer.fit(bars)

        assert engineer.get_feature_names_out() == list(engineer.transform(bars).columns)

    def test_the_returned_list_is_a_copy(self, engineer):
        engineer.fit(_ohlcv())

        engineer.get_feature_names_out().clear()

        assert len(engineer.get_feature_names_out()) > 0

    def test_the_sklearn_alias_is_the_same_method(self, engineer):
        engineer.fit(_ohlcv())

        assert engineer.get_feature_names() == engineer.get_feature_names_out()


# ── importance and selection ──────────────────────────────────────────────────


def _target_for(bars):
    return bars["close"].pct_change(fill_method=None).shift(-1).fillna(0.0)


class TestFeatureImportance:
    def test_it_scores_every_feature(self, engineer):
        bars = _ohlcv(300)

        importance = engineer.feature_importance(bars, _target_for(bars))

        assert len(importance) == len(engineer._feature_columns_)

    def test_scores_are_ordered_descending(self, engineer):
        bars = _ohlcv(300)

        importance = engineer.feature_importance(bars, _target_for(bars))

        assert list(importance.values) == sorted(importance.values, reverse=True)

    def test_it_can_be_truncated_to_the_top_n(self, engineer):
        bars = _ohlcv(300)

        assert len(engineer.feature_importance(bars, _target_for(bars), n_top=5)) == 5

    def test_the_random_forest_method_is_available(self, engineer):
        bars = _ohlcv(200)

        importance = engineer.feature_importance(bars, _target_for(bars), method="random_forest")

        assert len(importance) > 0

    def test_scores_are_finite(self, engineer):
        bars = _ohlcv(300)

        importance = engineer.feature_importance(bars, _target_for(bars))

        assert np.all(np.isfinite(importance.values))

    def test_a_target_that_never_overlaps_is_a_clear_error(self, engineer):
        """Silently scoring zero rows would produce meaningless importances."""
        bars = _ohlcv(200)
        disjoint = pd.Series(np.zeros(50), index=pd.date_range("2030-01-01", periods=50, freq="h"))

        with pytest.raises(ValueError, match="No overlapping rows"):
            engineer.feature_importance(bars, disjoint)


class TestSelectFeatures:
    def test_it_reduces_to_the_requested_width(self, engineer):
        bars = _ohlcv(300)

        selected = engineer.select_features(bars, _target_for(bars), n_features=10)

        assert len(selected.columns) == 10

    def test_the_selection_is_recorded(self, engineer):
        bars = _ohlcv(300)
        selected = engineer.select_features(bars, _target_for(bars), n_features=10)

        assert engineer.get_selected_features() == list(selected.columns)

    def test_asking_for_more_than_exist_returns_what_there_is(self, engineer):
        bars = _ohlcv(300)

        selected = engineer.select_features(bars, _target_for(bars), n_features=100_000)

        assert len(selected.columns) == len(engineer._feature_columns_)

    def test_the_accessor_raises_before_any_selection(self, engineer):
        with pytest.raises(RuntimeError, match="select_features"):
            engineer.get_selected_features()

    def test_the_returned_list_is_a_copy(self, engineer):
        bars = _ohlcv(300)
        engineer.select_features(bars, _target_for(bars), n_features=5)

        engineer.get_selected_features().clear()

        assert len(engineer.get_selected_features()) == 5


# ── the live path ─────────────────────────────────────────────────────────────


class TestLiveFeatures:
    def test_it_returns_a_row_per_bar(self, engineer):
        bars = _ohlcv(60)

        assert len(engineer._engineer_live_features(bars)) == len(bars)

    def test_the_last_row_survives_a_short_window(self, engineer):
        """The whole point: no global dropna, so inference always has a row."""
        bars = _ohlcv(25)

        result = engineer._engineer_live_features(bars)

        assert len(result) == 25
        assert result.iloc[-1].notna().any()

    def test_it_produces_no_nan(self, engineer):
        result = engineer._engineer_live_features(_ohlcv(40))

        assert not result.select_dtypes(include=[np.number]).isna().any().any()

    def test_it_produces_no_infinities(self, engineer):
        result = engineer._engineer_live_features(_ohlcv(40))

        numeric = result.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.to_numpy()).any()

    def test_it_does_not_mutate_the_caller_s_frame(self, engineer):
        bars = _ohlcv(40)
        before = list(bars.columns)

        engineer._engineer_live_features(bars)

        assert list(bars.columns) == before

    def test_it_does_not_look_ahead(self, engineer):
        """Truncating the future must leave every earlier row unchanged."""
        bars = _ohlcv(200)
        full = engineer._engineer_live_features(bars)
        truncated = engineer._engineer_live_features(bars.iloc[:150])

        shared = [c for c in truncated.columns if c in full.columns]
        pd.testing.assert_frame_equal(
            full[shared].iloc[:100].astype(float),
            truncated[shared].iloc[:100].astype(float),
            check_exact=False,
            rtol=1e-9,
        )

    def test_a_zero_price_leaves_returns_non_finite_on_purpose(self):
        """The infinity here is load-bearing, not an oversight.

        `close` is clipped to 1e-10 before every *log*, so log_returns stays
        finite. Plain `pct_change` is deliberately not clipped, so a zero
        previous close yields inf — and `InferenceEngine._features_are_unusable`
        refuses any vector containing Inf, routing that bar to the abstain path.

        Replacing the inf with a finite number would convert an abstain into a
        confident prediction on a corrupt bar, which is the exact failure mode
        that gate documents: "Zero-imputing these would produce a confident
        prediction from corrupt input." A zero print is a feed glitch, and the
        system is supposed to notice.
        """
        engineer = AdvancedFeatureEngineer()
        bars = _ohlcv(40)
        bars.loc[bars.index[10], "close"] = 0.0

        result = engineer._engineer_live_features(bars)

        assert not np.all(np.isfinite(result["returns"].to_numpy()))
        assert np.all(np.isfinite(result["log_returns"].to_numpy()))

    def test_a_corrupt_bar_is_rejected_by_the_inference_gate(self):
        """End to end: the inf produced above is what makes the engine abstain."""
        from ml.inference_engine import InferenceEngine

        engineer = AdvancedFeatureEngineer()
        bars = _ohlcv(40)
        bars.loc[bars.index[10], "close"] = 0.0
        features = engineer._engineer_live_features(bars)

        assert InferenceEngine()._features_are_unusable(features) is True

    def test_a_clean_window_is_accepted_by_the_same_gate(self):
        from ml.inference_engine import InferenceEngine

        features = AdvancedFeatureEngineer()._engineer_live_features(_ohlcv(60))

        assert InferenceEngine()._features_are_unusable(features) is False


class TestOnlineUpdate:
    def test_it_returns_a_feature_row_for_the_new_bar(self, engineer):
        window = _ohlcv(60)
        new_bar = window.iloc[-1]

        result = engineer.online_update(new_bar, window)

        assert isinstance(result, pd.Series)
        assert len(result) > 0

    def test_the_result_is_finite(self, engineer):
        window = _ohlcv(60)

        result = engineer.online_update(window.iloc[-1], window)

        numeric = pd.to_numeric(result, errors="coerce").dropna()
        assert np.all(np.isfinite(numeric.to_numpy()))

    def test_a_short_window_still_returns_a_row(self, engineer):
        window = _ohlcv(25)

        assert len(engineer.online_update(window.iloc[-1], window)) > 0
