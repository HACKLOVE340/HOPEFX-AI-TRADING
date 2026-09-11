# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/train_with_macro.py` — walk-forward training with macro features.

It measured 24%, and what was uncovered included every number the module
reports: the fold Sharpe, the walk-forward t-test, the held-out binomial test,
and the pipeline that decides which rows are allowed to be trained on.

Those numbers are the evidence a model is promoted on, so the tests here are
mostly about whether each one can be wrong — `backtesting-frameworks`' question,
not a line-coverage one. One of them can, badly: see
`TestTheFoldSharpeCannotTellASkilfulModelFromAWrongOne`.

Nothing here touches the network. `yfinance` and `ml.macro_features` are
stubbed at their import sites; everything else — xgboost, scikit-learn, scipy,
and `ml/training.py`'s FeatureEngineer — is the real thing, run on small
synthetic series.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "ml" / "train_with_macro.py"


def _load() -> Any:
    """Load the trainer under a private name.

    It is a script — `python ml/train_with_macro.py` — with no package import
    anywhere in the repository, so there is no canonical module object to
    reuse. Coverage keys on the file either way.
    """
    spec = importlib.util.spec_from_file_location("_train_with_macro_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def twm() -> Any:
    return _load()


@pytest.fixture
def sandbox(twm: Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """`MODEL_DIR` is absolute and points at the real `ml/saved_models/`."""
    target = tmp_path / "saved_models"
    target.mkdir()
    monkeypatch.setattr(twm, "MODEL_DIR", target)
    return target


def _ohlcv(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """A synthetic daily gold series with the columns yfinance returns."""
    rng = np.random.default_rng(seed)
    close = 1800.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    index = pd.date_range("2015-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.001, n)),
            "high": close * (1 + abs(rng.normal(0, 0.003, n))),
            "low": close * (1 - abs(rng.normal(0, 0.003, n))),
            "close": close,
            "volume": rng.integers(10_000, 100_000, n).astype(float),
        },
        index=index,
    )


def _matrix(n: int = 400, seed: int = 0, signal: bool = False) -> tuple[pd.DataFrame, pd.Series]:
    """A feature matrix with the return column the fold Sharpe looks for."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.01, n)
    frame = pd.DataFrame(
        {"log_returns": returns, **{f"f{i}": rng.normal(0, 1, n) for i in range(6)}},
        index=pd.date_range("2018-01-01", periods=n, freq="B"),
    )
    if signal:
        labels = (frame["f0"] > 0).astype(int)
        frame["f1"] = frame["f0"] + rng.normal(0, 0.1, n)
    else:
        labels = pd.Series(rng.integers(0, 2, n), index=frame.index)
    return frame, pd.Series(np.asarray(labels), index=frame.index)


# ---------------------------------------------------------------------------
# The finding
# ---------------------------------------------------------------------------


class TestTheFoldSharpeCannotTellASkilfulModelFromAWrongOne:
    """`_compute_fold_sharpe` never reads the outcome it is scoring.

    Its signature takes `y_test`, and its body does not use it. What it
    multiplies the prediction by is `X_test["log_returns"]` — the return of the
    bar the row describes, which is one of the model's own input features.

    The label is a *forward* return. `ml/training.py:243` builds it as
    `(close[t+horizon] - open[t+1]) / open[t+1] > 0`, deliberately entering at
    the next bar's open to avoid exactly this kind of optimism. So the
    prediction at row t is about bar t+1, and the return it is scored against
    is bar t's — a quantity already known, and already given to the model.

    The docstring says the column "is the 1-bar lagged return, so it represents
    the return that was realised on the bar being predicted". It is not lagged:
    `ml/training.py:133` defines `returns` as `close.pct_change()` and
    `log_returns` from it, while the lagged versions are the separate
    `returns_lag_1` / `log_ret_lag_1` columns — which this function only reaches
    for third and fourth, after preferring the unlagged ones.

    Consequence: the figure reported as "annualised Sharpe" in every fold, in
    `mean_sharpe`, and in `training_report.json` is not the strategy's
    performance. It measures how well the prediction agrees with a number the
    model was handed.

    Not fixed here. Scoring it properly needs the forward return — `y_reg` from
    `create_features`, which this module currently discards — so it is a
    signature change and a new data path through `walk_forward_eval`, and it
    changes a reported performance figure on a money-moving system. Raised for
    the owner. The module's own header already says "The credible performance
    number is OOS accuracy (p-value from binomial test), not Sharpe ratio",
    which is the right instinct; these tests say why it is right.
    """

    def test_the_outcome_argument_is_never_read(self, twm: Any) -> None:
        assert "y_test" not in twm._compute_fold_sharpe.__code__.co_names

    def test_a_perfect_forecast_and_a_perfectly_wrong_one_score_identically(self, twm: Any) -> None:
        """The clearest statement of the defect. Same features, same
        predictions, opposite ground truth — same Sharpe."""
        frame, _ = _matrix(300, seed=1)
        predictions = (frame["log_returns"].to_numpy() > 0).astype(int)
        perfect = pd.Series(predictions, index=frame.index)
        inverted = pd.Series(1 - predictions, index=frame.index)

        assert twm._compute_fold_sharpe(frame, perfect, predictions) == twm._compute_fold_sharpe(
            frame, inverted, predictions
        )

    def test_agreeing_with_a_known_feature_scores_the_maximum(self, twm: Any) -> None:
        """Predicting the sign of `log_returns` — an input column, not the
        target — pins the metric at its ceiling."""
        frame, labels = _matrix(300, seed=2)
        predictions = (frame["log_returns"].to_numpy() > 0).astype(int)
        assert twm._compute_fold_sharpe(frame, labels, predictions) == 10.0

    def test_disagreeing_with_it_scores_the_minimum(self, twm: Any) -> None:
        frame, labels = _matrix(300, seed=2)
        predictions = (frame["log_returns"].to_numpy() <= 0).astype(int)
        assert twm._compute_fold_sharpe(frame, labels, predictions) == -10.0

    def test_a_walk_forward_over_pure_noise_still_reports_a_sharpe(self, twm: Any, caplog) -> None:
        """End to end, on labels that are independent of every feature. The
        accuracy lands near 0.5 and says so; the Sharpe does not."""
        frame, labels = _matrix(400, seed=3)
        with caplog.at_level(logging.INFO):
            result = twm.walk_forward_eval(frame, labels, n_splits=3, model_type="xgb")

        assert 0.35 < result["mean_accuracy"] < 0.65, "the accuracy should show there is no signal"
        assert abs(result["mean_sharpe"]) > 0.5, (
            "a Sharpe this far from zero on noise is the point: it is not measuring the strategy"
        )

    def test_the_column_it_prefers_is_the_unlagged_one(self, twm: Any) -> None:
        """Preference order is log_returns, returns, returns_lag_1,
        log_ret_lag_1 — the two current-bar columns first. If the docstring's
        intent were the implementation, the lagged pair would lead."""
        rising = np.linspace(0.001, 0.02, 40)
        both = pd.DataFrame({"log_returns": rising, "returns_lag_1": -rising})
        predictions = np.ones(40, dtype=int)
        labels = pd.Series(predictions)

        assert twm._compute_fold_sharpe(both, labels, predictions) > 0, (
            "the unlagged column, which is positive here, was not the one used"
        )
        assert twm._compute_fold_sharpe(both[["returns_lag_1"]], labels, predictions) < 0

    def test_what_it_computes_today_is_pinned_exactly(self, twm: Any) -> None:
        """So that correcting it is a visible change rather than a silent one."""
        frame = pd.DataFrame({"log_returns": [0.01, 0.02, -0.01, 0.03, -0.02]})
        predictions = np.array([1, 1, 0, 1, 0])
        signal = np.where(predictions == 1, 1.0, -1.0)
        strategy = signal * frame["log_returns"].to_numpy()
        expected = float(np.mean(strategy)) / max(float(np.std(strategy, ddof=1)), 1e-9) * np.sqrt(252)

        assert twm._compute_fold_sharpe(frame, pd.Series(predictions), predictions) == pytest.approx(
            float(np.clip(expected, -10.0, 10.0))
        )


class TestTheFoldSharpeMechanics:
    """The parts that behave as intended, pinned so a fix keeps them."""

    def test_no_return_column_scores_zero_rather_than_guessing(self, twm: Any) -> None:
        frame = pd.DataFrame({"rsi": [50.0] * 20, "atr": [1.0] * 20})
        assert twm._compute_fold_sharpe(frame, pd.Series([1] * 20), np.ones(20, dtype=int)) == 0.0

    @pytest.mark.parametrize("column", ["log_returns", "returns", "returns_lag_1", "log_ret_lag_1"])
    def test_each_accepted_column_name_is_found(self, twm: Any, column: str) -> None:
        frame = pd.DataFrame({column: np.linspace(-0.02, 0.02, 30)})
        assert twm._compute_fold_sharpe(frame, pd.Series([1] * 30), np.ones(30, dtype=int)) != 0.0

    def test_a_single_observation_scores_zero(self, twm: Any) -> None:
        """One point has no dispersion, so a Sharpe would be a division by an
        undefined quantity."""
        frame = pd.DataFrame({"log_returns": [0.01]})
        assert twm._compute_fold_sharpe(frame, pd.Series([1]), np.ones(1, dtype=int)) == 0.0

    @pytest.mark.parametrize("value", [0.01, 0.1, 0.25, 1.0, 0.0, -0.01, 0.002])
    def test_a_constant_return_series_scores_zero(self, twm: Any, value: float) -> None:
        """A series with no variation has no Sharpe, and the function says so —
        "Returns 0.0 if the return series cannot be reconstructed".

        The guard used to be `if std == 0.0`, an exact comparison against a
        computed float. `np.std([0.01] * 30, ddof=1)` is 1.76e-18, not 0.0, so
        the guard fell through and `max(std, 1e-9)` divided by 1e-9 — turning a
        flat series into the clip ceiling of 10.0. It held for 0.25, 1.0 and
        0.0, which are exactly representable, and failed for 0.01 and 0.1,
        which are the magnitudes daily returns actually take. Parametrised over
        both kinds so the fix is checked where it matters.
        """
        frame = pd.DataFrame({"log_returns": [value] * 30})
        assert twm._compute_fold_sharpe(frame, pd.Series([1] * 30), np.ones(30, dtype=int)) == 0.0

    def test_a_nearly_constant_series_is_not_inflated_either(self, twm: Any) -> None:
        """Float noise a few orders of magnitude above zero must be treated as
        the flat series it is, not as a signal with a vanishing denominator."""
        frame = pd.DataFrame({"log_returns": [0.01 + i * 1e-15 for i in range(30)]})
        assert twm._compute_fold_sharpe(frame, pd.Series([1] * 30), np.ones(30, dtype=int)) == 0.0

    def test_a_genuinely_varying_series_is_still_scored(self, twm: Any) -> None:
        """The other side of the guard: it must not swallow real dispersion."""
        frame = pd.DataFrame({"log_returns": np.linspace(-0.02, 0.02, 30)})
        assert twm._compute_fold_sharpe(frame, pd.Series([1] * 30), np.ones(30, dtype=int)) != 0.0

    def test_the_result_is_clipped_to_plus_or_minus_ten(self, twm: Any) -> None:
        """An unclipped Sharpe of 60 in a report reads as a data error to a
        reader and as a triumph to a script."""
        frame = pd.DataFrame({"log_returns": [0.01, 0.0100001] * 15})
        assert abs(twm._compute_fold_sharpe(frame, pd.Series([1] * 30), np.ones(30, dtype=int))) <= 10.0

    def test_annualising_scales_by_the_root_of_the_trading_year(self, twm: Any) -> None:
        frame = pd.DataFrame({"log_returns": np.linspace(-0.02, 0.022, 60)})
        predictions = np.ones(60, dtype=int)
        labels = pd.Series(predictions)
        daily = twm._compute_fold_sharpe(frame, labels, predictions, annualise=False)
        annual = twm._compute_fold_sharpe(frame, labels, predictions, annualise=True)
        assert annual == pytest.approx(daily * np.sqrt(252), rel=1e-6)

    def test_a_short_signal_flips_the_sign(self, twm: Any) -> None:
        """pred=0 is a short, worth -1 × the bar return. If it were treated as
        flat, half the strategy would score zero."""
        frame = pd.DataFrame({"log_returns": np.linspace(0.001, 0.02, 40)})
        labels = pd.Series([1] * 40)
        longs = twm._compute_fold_sharpe(frame, labels, np.ones(40, dtype=int))
        shorts = twm._compute_fold_sharpe(frame, labels, np.zeros(40, dtype=int))
        assert longs == pytest.approx(-shorts)

    def test_it_returns_a_plain_float(self, twm: Any) -> None:
        """It is rounded and written to JSON; a numpy scalar is not
        serialisable by the stdlib encoder."""
        frame, labels = _matrix(50, seed=9)
        value = twm._compute_fold_sharpe(frame, labels, np.ones(50, dtype=int))
        assert type(value) is float
        json.dumps({"sharpe": round(value, 4)})


# ---------------------------------------------------------------------------
# Data in
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_yfinance(monkeypatch: pytest.MonkeyPatch):
    """Stand in for yfinance at its import site. No test here goes online."""
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"frame": None}

    def _download(symbol: str, **kwargs: Any) -> pd.DataFrame:
        calls.append({"symbol": symbol, **kwargs})
        frame = state["frame"]
        return frame if frame is not None else pd.DataFrame()

    module = types.ModuleType("yfinance")
    module.download = _download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return types.SimpleNamespace(calls=calls, state=state)


def _yahoo_frame(n: int = 100, tz: str | None = "UTC", multiindex: bool = False) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=n, freq="B", tz=tz)
    frame = pd.DataFrame(
        {"Open": 1800.0, "High": 1810.0, "Low": 1790.0, "Close": 1805.0, "Volume": 1000.0},
        index=index,
    )
    if multiindex:
        frame.columns = pd.MultiIndex.from_product([frame.columns, ["GC=F"]])
    return frame


class TestFetchingTheGoldSeries:
    def test_an_empty_response_is_refused_rather_than_trained_on(self, twm: Any, fake_yfinance) -> None:
        """A delisted ticker, a typo or an outage all return an empty frame.
        Continuing would train on nothing and report metrics for it."""
        with pytest.raises(ValueError, match="No data returned for GC=F"):
            twm.fetch_gold_ohlcv("GC=F", 50)

    def test_it_asks_for_the_requested_span_of_daily_bars(self, twm: Any, fake_yfinance) -> None:
        fake_yfinance.state["frame"] = _yahoo_frame()
        twm.fetch_gold_ohlcv("GC=F", 10)
        call = fake_yfinance.calls[0]
        assert call["symbol"] == "GC=F"
        assert call["interval"] == "1d"
        span = (pd.Timestamp(call["end"]) - pd.Timestamp(call["start"])).days
        assert span == pytest.approx(10 * 365, abs=2)

    def test_prices_are_adjusted_for_splits_and_dividends(self, twm: Any, fake_yfinance) -> None:
        """`auto_adjust=True`. Across fifty years of an unadjusted series the
        artificial jumps look like returns, and the model learns them."""
        fake_yfinance.state["frame"] = _yahoo_frame()
        twm.fetch_gold_ohlcv("GC=F", 50)
        assert fake_yfinance.calls[0]["auto_adjust"] is True

    def test_columns_come_back_lower_cased(self, twm: Any, fake_yfinance) -> None:
        """Everything downstream indexes `close` and `open` in lower case."""
        fake_yfinance.state["frame"] = _yahoo_frame()
        frame = twm.fetch_gold_ohlcv("GC=F", 5)
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]

    def test_a_multiindex_response_is_flattened_to_the_field_name(self, twm: Any, fake_yfinance) -> None:
        """yfinance returns `(field, ticker)` tuples for some requests. Left
        as tuples, every downstream lookup raises KeyError."""
        fake_yfinance.state["frame"] = _yahoo_frame(multiindex=True)
        frame = twm.fetch_gold_ohlcv("GC=F", 5)
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]

    def test_the_index_is_made_timezone_naive(self, twm: Any, fake_yfinance) -> None:
        """The macro series are naive. Joining a tz-aware index to a naive one
        raises, and aligning them wrongly would shift features against prices."""
        fake_yfinance.state["frame"] = _yahoo_frame(tz="America/New_York")
        frame = twm.fetch_gold_ohlcv("GC=F", 5)
        assert frame.index.tz is None

    def test_an_already_naive_index_is_left_alone(self, twm: Any, fake_yfinance) -> None:
        fake_yfinance.state["frame"] = _yahoo_frame(tz=None)
        frame = twm.fetch_gold_ohlcv("GC=F", 5)
        assert frame.index.tz is None
        assert len(frame) == 100

    def test_it_reports_the_span_it_actually_got(self, twm: Any, fake_yfinance, caplog) -> None:
        """The docstring warns that yfinance "silently clips to the earliest
        available date". The log line is the only place that silence is broken."""
        fake_yfinance.state["frame"] = _yahoo_frame(n=500)
        with caplog.at_level(logging.INFO):
            twm.fetch_gold_ohlcv("GC=F", 50)
        assert "Downloaded 500 bars" in caplog.text


class TestFetchingMacroSeries:
    def _install(self, monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
        module = types.ModuleType("ml.macro_features")

        def _history(start: Any, end: Any, interval: str = "1d") -> Any:
            if isinstance(result, Exception):
                raise result
            return result

        module.fetch_macro_history = _history  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "ml.macro_features", module)

    def test_a_good_fetch_is_returned(self, twm: Any, monkeypatch) -> None:
        frame = pd.DataFrame({"dxy": [100.0, 101.0], "vix": [15.0, 16.0]})
        self._install(monkeypatch, frame)
        result = twm.fetch_macro(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01"))
        assert result is not None
        assert list(result.columns) == ["dxy", "vix"]

    def test_an_empty_frame_becomes_none(self, twm: Any, monkeypatch, caplog) -> None:
        """None is what `build_features` reads as "train without macro". An
        empty frame passed through would produce all-NaN macro columns."""
        self._install(monkeypatch, pd.DataFrame())
        with caplog.at_level(logging.WARNING):
            assert twm.fetch_macro(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")) is None
        assert "empty DataFrame" in caplog.text

    @pytest.mark.parametrize(
        "failure",
        [ConnectionError("FRED unreachable"), ValueError("bad series id"), KeyError("DGS10"), RuntimeError("boom")],
    )
    def test_any_failure_degrades_to_no_macro_rather_than_stopping_training(
        self, twm: Any, monkeypatch, failure: Exception, caplog
    ) -> None:
        """A macro outage must cost the macro features, not the training run.
        The `except Exception` here is deliberate breadth, so the test says so
        by driving four unrelated failure types through it."""
        self._install(monkeypatch, failure)
        with caplog.at_level(logging.WARNING):
            assert twm.fetch_macro(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")) is None
        assert "Macro fetch failed" in caplog.text

    def test_a_missing_module_is_also_survivable(self, twm: Any, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "ml.macro_features", None)
        assert twm.fetch_macro(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")) is None


class TestBuildingTheFeatureMatrix:
    """Run against the real FeatureEngineer in `ml/training.py`."""

    def test_features_and_labels_come_back_aligned(self, twm: Any) -> None:
        X, y = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        assert len(X) == len(y)
        assert X.index.equals(y.index)

    def test_the_price_columns_are_not_features(self, twm: Any) -> None:
        """close is what the label is built from. Leaving it in the matrix
        hands the model the answer."""
        X, _ = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        assert not {"close", "open", "high", "low", "volume"} & set(X.columns)
        assert "target_class" not in X.columns
        assert "target_reg" not in X.columns

    def test_the_label_is_binary(self, twm: Any) -> None:
        _, y = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        assert set(y.unique()) <= {0, 1}

    def test_nothing_arrives_as_nan(self, twm: Any) -> None:
        """Rolling indicators leave NaNs at both ends. xgboost tolerates them
        and sklearn does not, so the drop has to happen here."""
        X, y = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        assert not X.isna().to_numpy().any()
        assert not y.isna().any()

    def test_supplying_macro_changes_the_values_not_the_column_count(self, twm: Any) -> None:
        """`ml/macro_features.py:263` fills every macro column with 0.0 when
        no frame is supplied, rather than leaving the columns out. So the width
        is the same either way and the difference is in the numbers — which is
        why `report["macro_features"]` records whether a frame was used rather
        than inferring it from the feature count."""
        ohlcv = _ohlcv(400)
        macro = pd.DataFrame(
            {"dxy": np.linspace(95, 105, len(ohlcv)), "vix": np.linspace(12, 30, len(ohlcv))},
            index=ohlcv.index,
        )
        with_macro, _ = twm.build_features(ohlcv, macro, prediction_horizon=1)
        without, _ = twm.build_features(ohlcv, None, prediction_horizon=1)

        assert with_macro.shape[1] == without.shape[1]
        assert not with_macro.equals(without), "the supplied macro frame changed nothing"

    def test_without_macro_those_columns_carry_no_information(self, twm: Any) -> None:
        """Constant-zero columns are inert to a tree model — it finds no split
        on them — so `--no-macro` degrades rather than corrupting. Pinned
        because a non-zero fill value would be a fabricated macro reading."""
        X, _ = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        constant = [column for column in X.columns if X[column].nunique() == 1]
        assert constant, "expected the unsupplied macro columns to be constant"
        for column in constant:
            assert X[column].iloc[0] == 0.0

    def test_a_longer_horizon_is_passed_through(self, twm: Any) -> None:
        """A five-bar horizon drops more tail rows than a one-bar horizon,
        because the label needs bars that do not exist yet."""
        short, _ = twm.build_features(_ohlcv(400), None, prediction_horizon=1)
        long, _ = twm.build_features(_ohlcv(400), None, prediction_horizon=5)
        assert len(long) < len(short)


# ---------------------------------------------------------------------------
# Walk-forward evaluation
# ---------------------------------------------------------------------------


class TestWalkForwardEvaluation:
    @pytest.fixture(scope="class")
    def result(self, twm: Any) -> dict:
        frame, labels = _matrix(400, seed=11)
        return twm.walk_forward_eval(frame, labels, n_splits=4, model_type="xgb")

    def test_it_reports_one_entry_per_fold(self, result: dict) -> None:
        assert [fold["fold"] for fold in result["folds"]] == [1, 2, 3, 4]

    def test_the_training_window_only_ever_grows(self, result: dict) -> None:
        """`TimeSeriesSplit` — each fold trains on everything before its test
        window. A shuffled split would train on the future and report an
        accuracy that cannot be reproduced live."""
        sizes = [fold["train_size"] for fold in result["folds"]]
        assert sizes == sorted(sizes)
        assert len(set(sizes)) == len(sizes)

    def test_no_fold_tests_on_what_it_trained_on(self, twm: Any) -> None:
        """Asserted against the splitter itself rather than inferred from the
        sizes: every test index must come after every training index."""
        from sklearn.model_selection import TimeSeriesSplit

        frame, _ = _matrix(200, seed=12)
        for train_idx, test_idx in TimeSeriesSplit(n_splits=4).split(frame):
            assert max(train_idx) < min(test_idx)

    def test_each_fold_reports_the_three_metrics(self, result: dict) -> None:
        for fold in result["folds"]:
            assert set(fold) == {"fold", "train_size", "test_size", "accuracy", "f1", "sharpe"}

    def test_the_aggregate_accuracy_is_the_mean_of_the_folds(self, result: dict) -> None:
        folds = [fold["accuracy"] for fold in result["folds"]]
        assert result["mean_accuracy"] == pytest.approx(float(np.mean(folds)), abs=5e-5)

    def test_the_significance_test_is_against_a_coin_flip(self, twm: Any) -> None:
        """H0 is accuracy == 0.5. Testing against 0 instead would call any
        model with a positive accuracy "significant"."""
        source = MODULE_PATH.read_text()
        assert "stats.ttest_1samp(accs, 0.5)" in source

    def test_noise_is_not_reported_as_significant(self, result: dict) -> None:
        """The property that matters: labels independent of every feature must
        not clear the bar."""
        assert result["significant"] is False
        assert result["p_value"] > 0.05

    def test_a_learnable_signal_is_reported_as_significant(self, twm: Any) -> None:
        """The other side. Without this, a test suite passes against a
        significance test that always says no."""
        frame, labels = _matrix(400, seed=13, signal=True)
        learned = twm.walk_forward_eval(frame, labels, n_splits=4, model_type="xgb")
        assert learned["mean_accuracy"] > 0.9
        assert learned["significant"] is True
        assert learned["p_value"] < 0.05

    def test_the_significance_flag_is_a_plain_bool(self, result: dict) -> None:
        """`np.bool_` is not JSON-serialisable and this dict is written to
        `training_report.json`."""
        assert type(result["significant"]) is bool
        json.dumps(result)

    @pytest.mark.parametrize("model_type", ["xgb", "rf"])
    def test_both_model_families_run(self, twm: Any, model_type: str) -> None:
        frame, labels = _matrix(200, seed=14)
        assert twm.walk_forward_eval(frame, labels, n_splits=3, model_type=model_type)["model"] == model_type

    def test_an_unknown_model_type_falls_back_to_the_forest(self, twm: Any) -> None:
        """The branch is `if model_type == "xgb"` with a bare `else`, so a typo
        silently trains a RandomForest and reports it under the typo's name."""
        frame, labels = _matrix(150, seed=15)
        result = twm.walk_forward_eval(frame, labels, n_splits=3, model_type="lightgbm")
        assert result["model"] == "lightgbm"

    def test_a_skewed_class_balance_does_not_stop_it(self, twm: Any) -> None:
        """`scale_pos_weight` is derived per fold as negatives over positives.
        A fold with no positives at all must not divide by zero."""
        frame, _ = _matrix(200, seed=16)
        labels = pd.Series(np.zeros(len(frame), dtype=int), index=frame.index)
        result = twm.walk_forward_eval(frame, labels, n_splits=3, model_type="xgb")
        assert result["mean_accuracy"] == 1.0

    def test_the_number_of_splits_is_the_callers_choice(self, twm: Any) -> None:
        frame, labels = _matrix(200, seed=17)
        assert len(twm.walk_forward_eval(frame, labels, n_splits=2, model_type="xgb")["folds"]) == 2


class TestTrainingTheFinalModel:
    def test_the_split_keeps_time_order(self, twm: Any, sandbox: pathlib.Path) -> None:
        """`X.iloc[:split]` / `X.iloc[split:]` — positional, not shuffled. A
        shuffled holdout on a time series is a leak, not a holdout."""
        frame, labels = _matrix(300, seed=21)
        _, metrics = twm.train_final_model(frame, labels, model_type="xgb", train_pct=0.8)
        assert metrics["train_size"] == 240
        assert metrics["test_size"] == 60

    def test_the_train_fraction_is_honoured(self, twm: Any, sandbox: pathlib.Path) -> None:
        frame, labels = _matrix(300, seed=22)
        _, metrics = twm.train_final_model(frame, labels, model_type="xgb", train_pct=0.5)
        assert metrics["train_size"] == 150

    def test_the_model_is_written_where_the_report_says(self, twm: Any, sandbox: pathlib.Path) -> None:
        frame, labels = _matrix(200, seed=23)
        twm.train_final_model(frame, labels, model_type="xgb")
        assert (sandbox / "xgb_macro.pkl").exists()

    def test_each_family_gets_its_own_file(self, twm: Any, sandbox: pathlib.Path) -> None:
        """Sharing a filename would leave whichever trained second pretending
        to be both."""
        frame, labels = _matrix(200, seed=24)
        twm.train_final_model(frame, labels, model_type="xgb")
        twm.train_final_model(frame, labels, model_type="rf")
        assert (sandbox / "xgb_macro.pkl").exists()
        assert (sandbox / "rf_macro.pkl").exists()

    def test_the_saved_model_can_be_loaded_and_predicts(self, twm: Any, sandbox: pathlib.Path) -> None:
        """A pickle that does not round-trip is a training run with nothing to
        show for it."""
        import joblib

        frame, labels = _matrix(200, seed=25)
        twm.train_final_model(frame, labels, model_type="xgb")
        restored = joblib.load(sandbox / "xgb_macro.pkl")
        assert len(restored.predict(frame)) == len(frame)

    def test_it_reports_the_features_it_used(self, twm: Any, sandbox: pathlib.Path) -> None:
        """The names, not only the count — a model restored against a
        differently ordered matrix predicts nonsense silently."""
        frame, labels = _matrix(200, seed=26)
        _, metrics = twm.train_final_model(frame, labels, model_type="xgb")
        assert metrics["features"] == list(frame.columns)
        assert metrics["feature_count"] == frame.shape[1]

    def test_the_metrics_are_json_serialisable(self, twm: Any, sandbox: pathlib.Path) -> None:
        frame, labels = _matrix(200, seed=27)
        _, metrics = twm.train_final_model(frame, labels, model_type="rf")
        json.dumps(metrics)


class TestTheHeldOutEvaluation:
    @pytest.fixture
    def split(self) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        frame, labels = _matrix(400, seed=31, signal=True)
        return frame.iloc[:300], labels.iloc[:300], frame.iloc[300:], labels.iloc[300:]

    def test_it_reports_the_count_it_tested_on(self, twm: Any, sandbox, split) -> None:
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert result["oos_size"] == 100
        assert result["train_size"] == 300

    def test_correct_predictions_and_accuracy_agree(self, twm: Any, sandbox, split) -> None:
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert result["correct_predictions"] == round(result["accuracy"] * result["oos_size"])

    def test_the_test_is_one_sided_against_a_coin_flip(self, twm: Any, sandbox, split) -> None:
        """One-sided: the question is whether the model beats chance, not
        whether it differs from chance. A two-sided test would award
        significance to a model that is reliably wrong."""
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert result["test"] == "one-sided binomial (H0: accuracy <= 0.5)"
        assert 'alternative="greater"' in MODULE_PATH.read_text()

    def test_a_model_that_learned_the_signal_is_significant(self, twm: Any, sandbox, split) -> None:
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert result["accuracy"] > 0.9
        assert result["significant"] is True

    def test_a_model_with_nothing_to_learn_is_not(self, twm: Any, sandbox) -> None:
        frame, labels = _matrix(400, seed=32)
        result = twm.oos_eval(frame.iloc[:300], labels.iloc[:300], frame.iloc[300:], labels.iloc[300:])
        assert result["significant"] is False

    def test_the_standard_error_is_reported_next_to_the_accuracy(self, twm: Any, sandbox, split) -> None:
        """The module's header is explicit that a bare accuracy is not enough.
        SE = sqrt(p(1-p)/n)."""
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        accuracy, n = result["accuracy"], result["oos_size"]
        assert result["accuracy_se"] == pytest.approx(float(np.sqrt(accuracy * (1 - accuracy) / n)), abs=1e-4)

    def test_a_single_class_oos_period_reports_a_neutral_auc(self, twm: Any, sandbox) -> None:
        """AUC is undefined when the held-out labels are all one class, and
        0.5 — no discrimination — is the honest answer.

        The code caught `(ValueError, TypeError)` for this. scikit-learn 1.9
        does not raise: it warns `UndefinedMetricWarning` and returns NaN. So
        the stated fallback was unreachable and NaN reached the report.
        """
        frame, labels = _matrix(300, seed=33)
        y_oos = pd.Series(np.ones(100, dtype=int), index=frame.index[200:])
        result = twm.oos_eval(frame.iloc[:200], labels.iloc[:200], frame.iloc[200:], y_oos)
        assert result["auc"] == 0.5

    def test_an_undefined_auc_never_reaches_the_report_as_nan(self, twm: Any, sandbox) -> None:
        """The consequence that made it worth fixing rather than noting.

        `json.dumps` writes a bare `NaN` for a float NaN, which is not valid
        JSON — RFC 8259 has no such literal — so `training_report.json` became
        unreadable to every strict parser downstream of it.
        """
        frame, labels = _matrix(300, seed=36)
        y_oos = pd.Series(np.zeros(100, dtype=int), index=frame.index[200:])
        result = twm.oos_eval(frame.iloc[:200], labels.iloc[:200], frame.iloc[200:], y_oos)

        def _refuse(literal: str) -> Any:
            raise ValueError(f"training_report.json would contain the invalid JSON literal {literal}")

        json.loads(json.dumps(result), parse_constant=_refuse)

    def test_a_well_formed_oos_period_still_gets_a_real_auc(self, twm: Any, sandbox) -> None:
        """The other side of the guard — it must not flatten every AUC to 0.5."""
        frame, labels = _matrix(400, seed=37, signal=True)
        result = twm.oos_eval(frame.iloc[:300], labels.iloc[:300], frame.iloc[300:], labels.iloc[300:])
        assert result["auc"] > 0.9

    def test_the_oos_window_is_named_in_the_report(self, twm: Any, sandbox, split) -> None:
        """So a reader can tell which years the number came from."""
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert str(X_oos.index[0].date()) in result["oos_period"]
        assert str(X_oos.index[-1].date()) in result["oos_period"]

    def test_a_non_date_index_is_still_reported(self, twm: Any, sandbox) -> None:
        frame, labels = _matrix(300, seed=34)
        plain = frame.reset_index(drop=True)
        result = twm.oos_eval(
            plain.iloc[:200],
            labels.iloc[:200].reset_index(drop=True),
            plain.iloc[200:],
            labels.iloc[200:].reset_index(drop=True),
        )
        assert "→" in result["oos_period"]

    def test_the_oos_model_is_saved_separately_from_the_final_one(self, twm: Any, sandbox, split) -> None:
        """Different training sets, so they are different models. One filename
        would make the OOS metrics describe a file that no longer exists."""
        X_train, y_train, X_oos, y_oos = split
        twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert (sandbox / "xgb_macro_oos.pkl").exists()
        assert not (sandbox / "xgb_macro.pkl").exists()

    def test_ci_mode_trains_a_smaller_forest(self, twm: Any, sandbox, split, monkeypatch) -> None:
        """`HOPEFX_CI` drops n_estimators from 500 to 20 so the suite is not a
        training run. Pinned because it silently changes what is measured — a
        CI number is not a production number."""
        X_train, y_train, X_oos, y_oos = split
        monkeypatch.setenv("HOPEFX_CI", "1")
        twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="rf")
        import joblib

        assert joblib.load(sandbox / "rf_macro_oos.pkl").n_estimators == 20

    def test_without_ci_mode_it_trains_the_full_forest(self, twm: Any, sandbox, monkeypatch) -> None:
        import joblib

        monkeypatch.delenv("HOPEFX_CI", raising=False)
        frame, labels = _matrix(150, seed=35)
        twm.oos_eval(frame.iloc[:100], labels.iloc[:100], frame.iloc[100:], labels.iloc[100:], model_type="rf")
        assert joblib.load(sandbox / "rf_macro_oos.pkl").n_estimators == 500

    def test_the_report_carries_the_sharpe_caveat(self, twm: Any, sandbox, split) -> None:
        """The module refuses to let the Sharpe be read as the headline number,
        and says so inside the report rather than only in its own docstring."""
        X_train, y_train, X_oos, y_oos = split
        result = twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb")
        assert "OOS accuracy" in result["sharpe_note"]

    def test_the_whole_result_is_json_serialisable(self, twm: Any, sandbox, split) -> None:
        X_train, y_train, X_oos, y_oos = split
        json.dumps(twm.oos_eval(X_train, y_train, X_oos, y_oos, model_type="xgb"))


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline(twm: Any, sandbox: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """`main()` with the network stubbed and the three model steps recorded.

    The estimators have their own tests above; what is under test here is which
    rows reach each step, which is the part that decides whether the reported
    numbers mean anything.
    """
    seen: dict[str, list[Any]] = {"walk_forward": [], "final": [], "oos": []}

    monkeypatch.setattr(twm, "fetch_gold_ohlcv", lambda symbol, years: _ohlcv(1200))
    monkeypatch.setattr(twm, "fetch_macro", lambda start, end: None)

    def _walk_forward(X, y, n_splits=5, model_type="xgb"):
        seen["walk_forward"].append({"X": X, "y": y, "n_splits": n_splits, "model_type": model_type})
        return {
            "model": model_type,
            "folds": [],
            "mean_accuracy": 0.52,
            "std_accuracy": 0.01,
            "mean_f1": 0.5,
            "mean_sharpe": 0.3,
            "t_stat": 1.0,
            "p_value": 0.2,
            "significant": False,
        }

    def _final(X, y, model_type="xgb", train_pct=0.8):
        seen["final"].append({"X": X, "y": y, "model_type": model_type})
        return None, {
            "model": model_type,
            "train_size": len(X),
            "test_size": 0,
            "accuracy": 0.51,
            "f1": 0.5,
            "feature_count": X.shape[1],
            "features": list(X.columns),
        }

    def _oos(X_train, y_train, X_oos, y_oos, model_type="xgb"):
        seen["oos"].append({"X_train": X_train, "X_oos": X_oos, "model_type": model_type})
        return {
            "model": model_type,
            "train_size": len(X_train),
            "oos_size": len(X_oos),
            "correct_predictions": 1,
            "accuracy": 0.53,
            "accuracy_se": 0.02,
            "f1": 0.5,
            "auc": 0.55,
            "p_value_binomial": 0.04,
            "significant": True,
            "oos_period": "a → b",
            "test": "one-sided binomial (H0: accuracy <= 0.5)",
            "top_features": {},
            "sharpe_note": "note",
        }

    monkeypatch.setattr(twm, "walk_forward_eval", _walk_forward)
    monkeypatch.setattr(twm, "train_final_model", _final)
    monkeypatch.setattr(twm, "oos_eval", _oos)
    return types.SimpleNamespace(seen=seen, model_dir=sandbox)


def _run(twm: Any, monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["train_with_macro.py", *argv])
    return twm.main()


class TestTheHeldOutWindowIsNeverTrainedOn:
    """The claim in `main()`: the OOS period "is never seen during training or
    hyperparameter selection — this is the only valid way to estimate live
    performance". It is the difference between an honest number and a fitted
    one, so it is asserted on the rows each step actually received.
    """

    def test_cross_validation_stops_before_the_held_out_window_begins(self, twm: Any, pipeline, monkeypatch) -> None:
        _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        cv_rows = pipeline.seen["walk_forward"][0]["X"]
        oos_rows = pipeline.seen["oos"][0]["X_oos"]
        assert cv_rows.index.max() < oos_rows.index.min()

    def test_the_final_model_is_trained_on_the_same_restricted_rows(self, twm: Any, pipeline, monkeypatch) -> None:
        _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        final_rows = pipeline.seen["final"][0]["X"]
        oos_rows = pipeline.seen["oos"][0]["X_oos"]
        assert final_rows.index.max() < oos_rows.index.min()

    def test_the_held_out_window_is_the_tail_of_the_series(self, twm: Any, pipeline, monkeypatch) -> None:
        """Carved off the end, not sampled from the middle — a mid-series
        holdout leaks the future into the training set on both sides."""
        report = _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        oos_rows = pipeline.seen["oos"][0]["X_oos"]
        assert len(oos_rows) == report["oos_sample_count"]
        assert report["cv_sample_count"] + report["oos_sample_count"] == report["sample_count"]

    def test_no_row_is_in_both_halves(self, twm: Any, pipeline, monkeypatch) -> None:
        _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        cv_rows = pipeline.seen["walk_forward"][0]["X"]
        oos_rows = pipeline.seen["oos"][0]["X_oos"]
        assert cv_rows.index.intersection(oos_rows.index).empty


class TestSizingTheHeldOutWindow:
    def test_a_year_is_about_two_hundred_and_fifty_two_bars(self, twm: Any, pipeline, monkeypatch) -> None:
        report = _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        assert report["oos_sample_count"] == 252

    def test_it_is_capped_at_a_quarter_of_the_data(self, twm: Any, pipeline, monkeypatch) -> None:
        """Asking for a ten-year holdout out of five years of data would leave
        nothing to train on. The cap keeps the request survivable."""
        report = _run(twm, monkeypatch, "--years", "5", "--oos-years", "20", "--splits", "3")
        assert report["oos_sample_count"] <= report["sample_count"] // 4

    def test_too_small_a_window_is_refused_rather_than_reported(self, twm: Any, pipeline, monkeypatch, caplog) -> None:
        """Under 100 bars the accuracy SE exceeds ±0.05, so the number would
        not distinguish a good model from a coin. It is dropped, with a reason."""
        with caplog.at_level(logging.WARNING):
            report = _run(twm, monkeypatch, "--years", "5", "--oos-years", "0.2", "--splits", "3")
        assert report["oos_sample_count"] == 0
        assert "need >= 100" in caplog.text
        assert pipeline.seen["oos"] == [], "a window judged too small was evaluated anyway"

    def test_no_request_means_no_held_out_evaluation(self, twm: Any, pipeline, monkeypatch) -> None:
        report = _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert report["oos_sample_count"] == 0
        assert "oos_xgb" not in report
        assert pipeline.seen["oos"] == []

    def test_without_a_holdout_cross_validation_sees_everything(self, twm: Any, pipeline, monkeypatch) -> None:
        report = _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert report["cv_sample_count"] == report["sample_count"]


class TestWhatTheReportRecords:
    def test_both_model_families_are_evaluated_and_trained(self, twm: Any, pipeline, monkeypatch) -> None:
        report = _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert [call["model_type"] for call in pipeline.seen["walk_forward"]] == ["xgb", "rf"]
        assert [call["model_type"] for call in pipeline.seen["final"]] == ["xgb", "rf"]
        assert {"walkforward_xgb", "walkforward_rf", "final_xgb", "final_rf"} <= set(report)

    def test_it_records_whether_macro_was_actually_used(self, twm: Any, pipeline, monkeypatch) -> None:
        """The feature count does not distinguish the two — the macro columns
        are present and zero-filled either way — so this flag is the only
        record of it."""
        report = _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert report["macro_features"] is False

    def test_macro_is_skipped_on_request(self, twm: Any, sandbox, monkeypatch) -> None:
        monkeypatch.setattr(twm, "fetch_gold_ohlcv", lambda symbol, years: _ohlcv(600))
        called: list[Any] = []
        monkeypatch.setattr(twm, "fetch_macro", lambda start, end: called.append(1))
        monkeypatch.setattr(
            twm,
            "walk_forward_eval",
            lambda X, y, **kw: {
                "model": kw.get("model_type", "xgb"),
                "folds": [],
                "mean_accuracy": 0.5,
                "std_accuracy": 0.0,
                "mean_f1": 0.5,
                "mean_sharpe": 0.0,
                "t_stat": 0.0,
                "p_value": 1.0,
                "significant": False,
            },
        )
        monkeypatch.setattr(
            twm,
            "train_final_model",
            lambda X, y, **kw: (
                None,
                {
                    "model": kw.get("model_type", "xgb"),
                    "train_size": len(X),
                    "test_size": 0,
                    "accuracy": 0.5,
                    "f1": 0.5,
                    "feature_count": X.shape[1],
                    "features": list(X.columns),
                },
            ),
        )
        _run(twm, monkeypatch, "--years", "5", "--no-macro", "--splits", "3")
        assert called == [], "--no-macro still went out for macro data"

    def test_macro_is_fetched_by_default(self, twm: Any, pipeline, monkeypatch) -> None:
        called: list[Any] = []
        monkeypatch.setattr(twm, "fetch_macro", lambda start, end: called.append(1))
        _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert called == [1]

    def test_the_report_is_written_where_the_log_says(self, twm: Any, pipeline, monkeypatch, caplog) -> None:
        with caplog.at_level(logging.INFO):
            _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        written = pipeline.model_dir / "training_report.json"
        assert written.exists()
        assert str(written) in caplog.text

    def test_the_written_report_is_valid_json(self, twm: Any, pipeline, monkeypatch) -> None:
        """Strictly — no NaN or Infinity literals, which `json.dumps` would
        emit happily and no conforming reader would accept."""
        _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")

        def _refuse(literal: str) -> Any:
            raise ValueError(f"invalid JSON literal in training_report.json: {literal}")

        text = (pipeline.model_dir / "training_report.json").read_text()
        assert json.loads(text, parse_constant=_refuse)

    def test_the_report_says_what_was_trained_and_when(self, twm: Any, pipeline, monkeypatch) -> None:
        report = _run(twm, monkeypatch, "--years", "7", "--symbol", "XAUUSD=X", "--splits", "3")
        assert report["symbol"] == "XAUUSD=X"
        assert report["years"] == 7
        assert report["trained_at"].endswith("+00:00")

    def test_the_split_count_reaches_the_evaluator(self, twm: Any, pipeline, monkeypatch) -> None:
        _run(twm, monkeypatch, "--years", "5", "--splits", "2")
        assert {call["n_splits"] for call in pipeline.seen["walk_forward"]} == {2}

    def test_the_horizon_reaches_the_feature_builder(self, twm: Any, sandbox, pipeline, monkeypatch) -> None:
        """A five-bar horizon drops more tail rows than a one-bar one, so the
        sample count is the observable difference."""
        one = _run(twm, monkeypatch, "--years", "5", "--horizon", "1", "--splits", "3")
        five = _run(twm, monkeypatch, "--years", "5", "--horizon", "5", "--splits", "3")
        assert five["sample_count"] < one["sample_count"]

    def test_the_summary_names_the_numbers_a_reader_needs(self, twm: Any, pipeline, monkeypatch, caplog) -> None:
        with caplog.at_level(logging.INFO):
            _run(twm, monkeypatch, "--years", "5", "--oos-years", "1", "--splits", "3")
        assert "Walk-forward accuracy" in caplog.text
        assert "OOS p-value (binomial)" in caplog.text

    def test_the_summary_repeats_the_sharpe_caveat(self, twm: Any, pipeline, monkeypatch, caplog) -> None:
        """Printed at the end of every run, where the operator is looking."""
        with caplog.at_level(logging.INFO):
            _run(twm, monkeypatch, "--years", "5", "--splits", "3")
        assert "Credible performance number: OOS accuracy" in caplog.text
        assert "Do NOT commit live capital until 30+ days paper trading done." in caplog.text
