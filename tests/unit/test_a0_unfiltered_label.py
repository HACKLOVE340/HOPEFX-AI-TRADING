# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A0 fix #6 — the unfiltered target labelled its last ``horizon`` bars 0 (D1).

``ml/advanced_features.py`` built the unfiltered label as
``(future_ret > 0).astype(float)`` and then wrote ``y_raw[y_raw.isna()] =
np.nan`` — a no-op, because ``NaN > 0`` is ``False`` before the cast. The last
``horizon`` bars, whose forward return is unknowable, were therefore labelled
"down" and trained on. On real data the last label was dated on the last bar.

The inference callers all passed ``use_filtered_target=False`` and took
``X.iloc[-1]``, so they silently depended on that defect to keep the newest
bar. After the fix they ask for it explicitly with ``drop_unlabelled=False``;
the inference-path tests below fail if any of them is left scoring a bar
``horizon`` bars stale.

Also here: the no-look-ahead property. Appending future bars must not change
any feature or label already computed.
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest


H = 5


def _rising(n: int = 340) -> pd.DataFrame:
    """Strictly rising closes AND opens: every knowable label is 1."""
    rng = np.random.default_rng(11)
    close = 1500.0 * np.exp(np.cumsum(np.full(n, 0.004)))
    open_ = close * 0.999  # open[t+1] < close[t+H] for every t
    high = close * (1.0 + rng.uniform(0.001, 0.004, n))
    low = open_ * (1.0 - rng.uniform(0.001, 0.004, n))
    vol = rng.uniform(1000.0, 5000.0, n)
    idx = pd.bdate_range("2021-01-04", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def _walk(n: int, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1800.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    open_ = close * (1.0 + rng.normal(0.0, 0.002, n))
    high = np.maximum(close, open_) * (1.0 + rng.uniform(0.0, 0.004, n))
    low = np.minimum(close, open_) * (1.0 - rng.uniform(0.0, 0.004, n))
    vol = rng.uniform(1000.0, 5000.0, n)
    idx = pd.bdate_range("2019-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


# ── D1: unknowable labels are excluded, never 0 ───────────────────────────────


@pytest.mark.parametrize("builder", ["advanced", "extended"])
def test_unfiltered_labels_on_a_rising_series_are_all_up(builder):
    from ml.advanced_features import build_advanced_features
    from ml.features_extended import build_extended_features

    fn = build_advanced_features if builder == "advanced" else build_extended_features
    df = _rising()
    X, y = fn(df, horizon=H, use_filtered_target=False, smoke=True)
    counts = y.value_counts().to_dict()
    assert counts.get(0, 0) == 0, (
        f"a strictly rising series produced {counts.get(0)} 'down' labels {counts}: the last {H} bars have no "
        "knowable forward return and were labelled 0 (D1)"
    )
    # The last labelled row is exactly H bars before the end of the data.
    assert y.index[-1] == df.index[-(H + 1)], (y.index[-1], df.index[-(H + 1)])
    assert X.index.equals(y.index)


def test_unknowable_rows_are_kept_for_inference_only_when_asked():
    """drop_unlabelled=False: X keeps every feature-complete bar (the newest
    included); y still covers only rows whose label is knowable."""
    from ml.features_extended import build_extended_features

    df = _rising()
    X, y = build_extended_features(df, horizon=H, use_filtered_target=False, smoke=True, drop_unlabelled=False)
    assert X.index[-1] == df.index[-1], "the newest bar must be available to score"
    assert y.index[-1] == df.index[-(H + 1)]
    assert set(y.index) <= set(X.index)
    assert (y == 1).all()


# ── inference paths score the newest bar ──────────────────────────────────────


def test_inference_engine_builds_features_for_the_newest_bar():
    from ml.inference_engine import InferenceEngine

    df = _walk(320)
    X = InferenceEngine()._build_features(df, None, None, "XAU_USD")
    assert X is not None, "feature build failed"
    assert X.index[-1] == df.index[-1], (
        f"the engine's feature row is dated {X.index[-1]}, not the newest bar {df.index[-1]} — it would score "
        "a stale bar"
    )


def test_live_scorer_builds_features_for_the_newest_bar():
    from ml.live_inference import AdvancedModelPredictor

    class _NoCache:  # a cache hit returns a frame without its date index
        def get(self, symbol, last_ts):
            return None

        def set(self, symbol, last_ts, features):
            return None

    df = _walk(320)
    p = AdvancedModelPredictor(cache=_NoCache())  # type: ignore[arg-type]
    X = p._build_features(df, symbol="TEST_NEWEST_BAR")
    assert X is not None
    assert X.index[-1] == df.index[-1], (X.index[-1], df.index[-1])


def test_advanced_predictor_and_lstm_callers_request_unlabelled_rows():
    """The other two inference callers take the last row(s) of X. They cannot be
    driven without a model artifact, so their call sites are read."""
    import inspect

    import ml.advanced_predictor as ap
    import ml.lstm_signal_layer as lstm

    for mod in (ap, lstm):
        src = inspect.getsource(mod)
        n_calls = src.count("use_filtered_target=False")
        assert n_calls >= 1
        assert src.count("drop_unlabelled=False") >= n_calls, (
            f"{mod.__name__} builds unfiltered features for inference without drop_unlabelled=False — after "
            "the D1 fix it would score a bar `horizon` bars stale"
        )


# ── no look-ahead ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("horizon", [1, H])
def test_appending_future_bars_changes_no_earlier_feature(horizon):
    """Causality of FEATURES, checked on every feature-complete row
    (drop_unlabelled=False). With the default drop, the last ``horizon`` rows
    are removed, and a feature that looks exactly ``horizon`` bars ahead is
    hidden by that coincidence — which is how the 5-bar swing-level leak below
    survived next to a 5-bar label."""
    from ml.features_extended import build_extended_features

    full = _walk(420)
    short = full.iloc[:360]
    kw = {"horizon": horizon, "use_filtered_target": False, "smoke": False, "drop_unlabelled": False}
    X_s, _ = build_extended_features(short, **kw)
    X_f, _ = build_extended_features(full, **kw)

    assert X_s.index[-1] == short.index[-1]
    common = X_s.index.intersection(X_f.index)
    assert len(common) == len(X_s), "a row present in the short frame vanished when bars were appended"
    a, b = X_s.loc[common], X_f.loc[common, X_s.columns]
    diff = (a - b).abs().max()
    changed = diff[diff > 1e-9]
    assert changed.empty, f"appending future bars changed earlier features: {changed.sort_values().tail(10).to_dict()}"


@pytest.mark.parametrize("filtered", [True, False])
def test_appending_future_bars_changes_no_earlier_label(filtered):
    """Rows labelled in the short frame keep their label; rows whose label was
    unknowable are absent, and simply become labelled once the bars exist."""
    from ml.features_extended import build_extended_features

    full = _walk(420)
    short = full.iloc[:360]
    _, y_s = build_extended_features(short, horizon=H, use_filtered_target=filtered, smoke=True)
    _, y_f = build_extended_features(full, horizon=H, use_filtered_target=filtered, smoke=True)
    assert y_s.index[-1] <= short.index[-(H + 1)], "a label was emitted for a bar whose forward return is unknowable"
    pd.testing.assert_series_equal(y_s, y_f.loc[y_s.index], check_names=False)
