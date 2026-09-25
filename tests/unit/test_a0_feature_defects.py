# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A0 fix #5 — the feature defects D3 and D4.

docs/audit/2026-09-24-a0-no-edge-investigation.md, Q2 and Q5:

* **D3.** ``ri_regime_mom``, ``ri_vol_adj_mom`` and ``ri_trend_vol_confirm``
  were constant 0.0 by construction. ``build_extended_features`` ran
  ``add_regime_interactions`` on a fresh copy of raw OHLCV, so the base-builder
  columns they read (``mom_20``, ``rvol_20``, ``regime_trend``, ``adx_14``)
  never existed there and the ``else: 0.0`` branch always ran.
  ``ri_signal_alignment`` read ``mom_20`` the same way through ``d.get`` and
  silently scored momentum's sign as 0 on every bar.
* **D4.** ``inst_poc``, ``inst_vah`` and ``inst_val`` were raw price levels
  (|corr(close)| > 0.9) although both builders promise "all stationary". Out of
  sample 94-96% of their values lay outside the training range, and they were
  the #1 driver of the dry run's "predict down" bias.

Each assertion here names the production change that makes it fail: reverting
the interaction inputs makes the ``nunique`` checks fail; putting a raw level
back makes the correlation check fail.
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest


def _trending(n: int = 420, seed: int = 0, drift: float = 0.0015) -> pd.DataFrame:
    """Daily OHLCV with a strong trend — the case where a price level and the
    close move together, so a non-stationary feature cannot hide."""
    rng = np.random.default_rng(seed)
    close = 1500.0 * np.exp(np.cumsum(drift + rng.normal(0.0, 0.01, n)))
    open_ = close * (1.0 + rng.normal(0.0, 0.002, n))
    high = np.maximum(close, open_) * (1.0 + rng.uniform(0.0, 0.005, n))
    low = np.minimum(close, open_) * (1.0 - rng.uniform(0.0, 0.005, n))
    volume = rng.uniform(1000.0, 5000.0, n)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


@pytest.fixture(scope="module")
def frame():
    from ml.features_extended import build_extended_features

    df = _trending()
    X, y = build_extended_features(df, horizon=5, smoke=True)
    return df, X, y


# ── D3: the regime interactions compute what they are named for ──────────────

INTERACTIONS = ("ri_regime_mom", "ri_vol_adj_mom", "ri_trend_vol_confirm", "ri_signal_alignment")


@pytest.mark.parametrize("col", INTERACTIONS)
def test_interaction_feature_is_not_constant(frame, col):
    _, X, _ = frame
    assert col in X.columns, f"{col} is missing from the extended feature frame"
    assert X[col].nunique() > 2, (
        f"{col} takes {X[col].nunique()} distinct value(s) on a {len(X)}-row trending series — it is "
        "constant by construction, which is D3: its inputs never reach add_regime_interactions"
    )


def test_vol_adjusted_momentum_is_momentum_over_volatility(frame):
    """Not merely 'varies': it is the quantity its name says, built from the
    same mom_20 / rvol_20 the base builder puts in the frame."""
    _, X, _ = frame
    expected = (X["mom_20"] / X["rvol_20"].replace(0, np.nan)).fillna(0.0).clip(-5, 5)
    np.testing.assert_allclose(X["ri_vol_adj_mom"].to_numpy(), expected.to_numpy(), rtol=1e-9, atol=1e-12)


def test_regime_momentum_is_regime_times_momentum(frame):
    _, X, _ = frame
    expected = X["regime_trend"] * X["mom_20"]
    np.testing.assert_allclose(X["ri_regime_mom"].to_numpy(), expected.to_numpy(), rtol=1e-9, atol=1e-12)


def test_trend_volume_confirmation_uses_adx(frame):
    _, X, _ = frame
    expected = (X["adx_14"] / 100.0) * X["of_vol_surge"].clip(0, 3)
    np.testing.assert_allclose(X["ri_trend_vol_confirm"].to_numpy(), expected.to_numpy(), rtol=1e-9, atol=1e-12)


def test_interactions_are_computed_even_when_called_on_raw_ohlcv():
    """add_regime_interactions must never silently fall back to a constant.
    Called on bare OHLCV it derives its inputs rather than emitting 0.0."""
    from ml.features_extended import add_orderflow_features, add_regime_interactions

    out = add_regime_interactions(add_orderflow_features(_trending()))
    for col in INTERACTIONS:
        assert out[col].iloc[200:].nunique() > 2, f"{col} is constant when computed from raw OHLCV"


# ── D4: no raw price level reaches the model ──────────────────────────────────


def test_no_feature_tracks_the_price_level(frame):
    df, X, _ = frame
    close = df["close"].reindex(X.index)
    levels = {}
    for col in X.columns:
        s = X[col]
        if s.std() == 0:
            continue
        r = abs(np.corrcoef(s.to_numpy(dtype=float), close.to_numpy(dtype=float))[0, 1])
        if r > 0.9:
            levels[col] = round(float(r), 3)
    assert not levels, (
        f"features with |corr(close)| > 0.9 on a trending series: {levels}. A raw price level is not "
        "stationary; out of sample it extrapolates (D4)."
    )


@pytest.mark.parametrize("raw", ["inst_poc", "inst_vah", "inst_val"])
def test_raw_volume_profile_levels_are_not_features(frame, raw):
    _, X, _ = frame
    assert raw not in X.columns, f"{raw} is a raw price level and must not be a model feature (D4)"


@pytest.mark.parametrize("level", ["poc", "vah", "val"])
def test_volume_profile_levels_are_expressed_as_atr_distances(frame, level):
    """The information is kept, normalised the way dist_ma_* is: (close - level) / ATR14."""
    _, X, _ = frame
    col = f"inst_{level}_dist_atr"
    assert col in X.columns, f"{col} is missing — the volume-profile level must survive as a stationary distance"
    assert X[col].nunique() > 2
    # Same sign as the percentage distance that already existed.
    pct = X[f"inst_dist_{level}"]
    both = (X[col] != 0) & (pct != 0)
    assert (np.sign(X.loc[both, col]) == np.sign(pct[both])).all()
