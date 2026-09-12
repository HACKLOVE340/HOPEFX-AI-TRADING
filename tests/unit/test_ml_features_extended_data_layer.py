# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/features_extended.py` — the data-layer injection, and what it guarantees.

`add_data_layer_features` was the largest uncovered block in the module (133
lines). It is also the bridge the replay engine names as its causal enforcement
mechanism, so what it actually does is worth stating in tests rather than in
three docstrings that disagree with each other. See MASTER_OUTSTANDING A13.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd
import pytest

from ml.features_extended import add_data_layer_features

pytestmark = pytest.mark.unit


def _ohlcv(n: int = 300, start: str = "2023-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(7)
    close = 1900 + rng.normal(0, 2, n).cumsum()
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "volume": 1000 + rng.normal(0, 50, n),
        },
        index=index,
    )


@pytest.fixture
def orchestrator(monkeypatch: pytest.MonkeyPatch):
    """A stand-in `data_layer.orchestrator` whose feature dict the test sets."""
    module = types.ModuleType("data_layer.orchestrator")
    module.calls: list[dict] = []
    module.payload: dict[str, float] = {}

    def _get_ml_features(as_of=None, **kwargs):
        module.calls.append({"as_of": as_of, **kwargs})
        return dict(module.payload)

    module.orchestrator = types.SimpleNamespace(get_ml_features=_get_ml_features)
    monkeypatch.setitem(sys.modules, "data_layer.orchestrator", module)
    return module


def _dl_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith("dl_")]


class TestInjection:
    def test_the_documented_feature_groups_all_arrive(self, orchestrator) -> None:
        out = add_data_layer_features(_ohlcv())
        for name in (
            "dl_spread",
            "dl_ofi",
            "dl_vwap",
            "dl_depth_imbalance",
            "dl_news_sentiment",
            "dl_macro_impact",
            "dl_is_blackout",
            "dl_tick_confidence",
            "dl_macro_vix",
        ):
            assert name in out.columns, f"{name} was not injected"
        assert len(_dl_columns(out)) >= 26, "the docstring promises at least 26"

    def test_the_original_columns_survive(self, orchestrator) -> None:
        source = _ohlcv()
        out = add_data_layer_features(source)
        for column in source.columns:
            assert column in out.columns
            assert out[column].equals(source[column])

    def test_the_input_frame_is_not_mutated(self, orchestrator) -> None:
        """It copies; a feature builder that edits its argument corrupts every
        other branch of a pipeline that shares the frame."""
        source = _ohlcv()
        before = list(source.columns)
        add_data_layer_features(source)
        assert list(source.columns) == before

    def test_the_row_count_is_unchanged(self, orchestrator) -> None:
        source = _ohlcv(250)
        assert len(add_data_layer_features(source)) == 250

    def test_as_of_is_handed_to_the_orchestrator(self, orchestrator) -> None:
        cutoff = pd.Timestamp("2023-01-05", tz="UTC")
        add_data_layer_features(_ohlcv(), as_of=cutoff)
        assert orchestrator.calls[-1]["as_of"] == cutoff

    def test_live_mode_passes_no_cutoff(self, orchestrator) -> None:
        add_data_layer_features(_ohlcv())
        assert orchestrator.calls[-1]["as_of"] is None


class TestItNeverEmitsNanOrInf:
    """Every dl_ column is fed to a model. One NaN poisons a row; one inf
    poisons a fit."""

    def test_an_unavailable_orchestrator_yields_neutral_values_not_nan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = types.ModuleType("data_layer.orchestrator")

        class _Down:
            def get_ml_features(self, as_of=None, **kwargs):
                raise RuntimeError("data layer is down")

        broken.orchestrator = _Down()
        monkeypatch.setitem(sys.modules, "data_layer.orchestrator", broken)

        out = add_data_layer_features(_ohlcv())

        dl = _dl_columns(out)
        assert len(dl) >= 26
        assert out[dl].notna().all().all()
        assert np.isfinite(out[dl].to_numpy()).all()

    def test_infinities_from_the_orchestrator_are_scrubbed(self, orchestrator) -> None:
        orchestrator.payload = {"micro_spread": float("inf"), "micro_spread_pct": float("-inf")}
        out = add_data_layer_features(_ohlcv())
        assert np.isfinite(out[_dl_columns(out)].to_numpy()).all()

    def test_nan_from_the_orchestrator_is_scrubbed(self, orchestrator) -> None:
        orchestrator.payload = {"micro_spread": float("nan")}
        out = add_data_layer_features(_ohlcv())
        assert out[_dl_columns(out)].notna().all().all()

    def test_an_empty_frame_does_not_raise(self, orchestrator) -> None:
        empty = _ohlcv(0)
        out = add_data_layer_features(empty)
        assert len(out) == 0
        assert len(_dl_columns(out)) >= 26


class TestEveryInjectedFeatureIsConstantAcrossRows:
    """The measured behaviour, recorded rather than blessed.

    `orchestrator.get_ml_features()` returns a dict of **scalars** — one
    moment's reading — and each is assigned with `d["dl_x"] = scalar`, which
    pandas broadcasts to every row. So a 500-bar frame spanning three weeks
    carries one value in each dl_ column for the whole span.

    Measured with a live orchestrator returning non-zero values:

        dl_spread       first=0.35   last=0.35   distinct=1
        dl_macro_vix    first=17.9   last=17.9   distinct=1
        36 of 36 dl_ columns constant, over 2023-01-01 .. 2023-01-21

    Two consequences, both in A13: within one frame these columns have zero
    variance and cannot inform a split; across frames built at different times
    the constant becomes a proxy for *when the frame was built*.
    """

    def test_a_three_week_frame_carries_one_value_per_column(self, orchestrator) -> None:
        orchestrator.payload = {
            "micro_spread": 0.35,
            "micro_ofi": -0.42,
            "news_sentiment_score": 0.81,
            "macro_vix": 17.9,
        }

        out = add_data_layer_features(_ohlcv(500))

        dl = _dl_columns(out)
        constant = [c for c in dl if out[c].nunique(dropna=False) <= 1]
        assert constant == dl, "some dl_ column now varies by row — the injection became per-row; update A13"

    def test_the_supplied_value_is_the_value_every_row_gets(self, orchestrator) -> None:
        orchestrator.payload = {"macro_vix": 17.9}
        out = add_data_layer_features(_ohlcv(400))
        assert out["dl_macro_vix"].iloc[0] == pytest.approx(17.9)
        assert out["dl_macro_vix"].iloc[-1] == pytest.approx(17.9)

    def test_two_calls_at_different_moments_give_two_different_constants(self, orchestrator) -> None:
        """This is the leak: concatenate these two frames for training and
        `dl_macro_vix` tells the model which batch a row came from."""
        frame = _ohlcv(200)

        orchestrator.payload = {"macro_vix": 12.0}
        monday = add_data_layer_features(frame)
        orchestrator.payload = {"macro_vix": 31.0}
        tuesday = add_data_layer_features(frame)

        assert monday["dl_macro_vix"].nunique() == 1
        assert tuesday["dl_macro_vix"].nunique() == 1
        assert monday["dl_macro_vix"].iloc[0] != tuesday["dl_macro_vix"].iloc[0]
