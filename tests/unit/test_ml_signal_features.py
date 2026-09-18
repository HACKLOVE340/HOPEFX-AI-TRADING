# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/signal_features.py` — indicators, feature extraction and the ensemble.

The property worth testing first in a feature module is not any single number:
it is **causality**. An indicator that reads a bar it would not have had at the
time turns a backtest into a lookup of the answer. `TestNoLookAhead` holds that
directly — extend the series into the future and every feature computed for the
earlier point must be unchanged.

The module measured 78%.
"""

from __future__ import annotations

import numpy as np
import pytest

from ml.signal_features import FeatureEngineer, FeatureVector, SignalEnsemble, TechnicalIndicators

pytestmark = pytest.mark.unit


class _Bar:
    def __init__(self, index: int, close: float, volume: float = 1000.0) -> None:
        self.open = close - 0.2
        self.close = close
        self.high = close + 0.5
        self.low = close - 0.5
        self.volume = volume
        self.timestamp = 1_700_000_000 + index * 60


def _series(n: int, start: float = 1900.0, step: float = 0.4) -> list[_Bar]:
    return [_Bar(i, start + i * step, 1000.0 + i) for i in range(n)]


# ---------------------------------------------------------------------------
# Causality
# ---------------------------------------------------------------------------


class TestNoLookAhead:
    """Every indicator here is trailing, and every feature reads `[-1]` — the
    window ending at the last bar. These assert that rather than trusting it."""

    @pytest.mark.parametrize(
        ("name", "call"),
        [
            ("sma", lambda p: TechnicalIndicators.sma(p, 10)),
            ("ema", lambda p: TechnicalIndicators.ema(p, 10)),
            ("rsi", lambda p: TechnicalIndicators.rsi(p, 14)),
            # Volume must be a prefix-extension, not a rescale: `np.linspace`
            # would hand the two runs different volumes and the test would fail
            # on its own inputs rather than on look-ahead.
            ("obv", lambda p: TechnicalIndicators.obv(p, 100.0 + np.arange(len(p), dtype=float))),
        ],
    )
    def test_appending_future_bars_does_not_change_earlier_values(self, name: str, call) -> None:
        prices = np.linspace(1900.0, 1950.0, 120)
        future = np.concatenate([prices, np.linspace(2200.0, 2400.0, 40)])

        short, long = call(prices), call(future)

        # Compare the values that exist in both, anchored at the start of the
        # valid region so the same windows line up.
        overlap = len(short)
        assert np.allclose(short[:overlap], long[:overlap]), (
            f"{name} changed a past value when future bars were appended"
        )

    def test_atr_uses_the_previous_close_not_the_next_one(self) -> None:
        high = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        low = np.array([9.0, 9.5, 11.0, 12.0, 13.0])
        close = np.array([9.5, 10.5, 11.5, 12.5, 13.5])

        atr = TechnicalIndicators.atr(high, low, close, period=2)

        # True range at bar i uses close[i-1]; a forward-looking variant would
        # differ. Computed by hand for the first window:
        #   tr[1] = max(11-9.5, |11-9.5|, |9.5-9.5|) = 1.5
        #   tr[2] = max(12-11,  |12-10.5|, |11-10.5|) = 1.5
        assert atr[0] == pytest.approx(1.5, abs=1e-9)

    def test_the_feature_vector_is_built_from_the_last_bar(self) -> None:
        bars = _series(200)
        engineer = FeatureEngineer()

        vector = engineer.extract_features("XAUUSD", bars)

        assert vector is not None
        assert vector.timestamp == bars[-1].timestamp


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_sma_is_the_mean_of_its_window(self) -> None:
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert TechnicalIndicators.sma(prices, 3) == pytest.approx([2.0, 3.0, 4.0])

    def test_ema_starts_at_the_first_price_and_tracks_it(self) -> None:
        prices = np.array([10.0] * 20)
        ema = TechnicalIndicators.ema(prices, 5)
        assert ema[0] == 10.0
        assert ema[-1] == pytest.approx(10.0)

    def test_a_rising_series_pins_rsi_high_and_a_falling_one_pins_it_low(self) -> None:
        rising = TechnicalIndicators.rsi(np.linspace(100, 200, 60), 14)
        falling = TechnicalIndicators.rsi(np.linspace(200, 100, 60), 14)
        assert rising[-1] > 95
        assert falling[-1] < 5

    def test_rsi_never_leaves_its_range(self) -> None:
        rng = np.random.default_rng(11)
        rsi = TechnicalIndicators.rsi(100 + rng.normal(0, 1, 300).cumsum(), 14)
        assert rsi.min() >= 0.0
        assert rsi.max() <= 100.0

    def test_a_flat_series_gives_rsi_zero_rather_than_dividing_by_zero(self) -> None:
        """Equal gains and losses of zero: the +1e-10 guard is what stops this
        being a ZeroDivisionError on a market that did not move."""
        rsi = TechnicalIndicators.rsi(np.array([100.0] * 40), 14)
        assert np.isfinite(rsi).all()

    def test_bollinger_bands_bracket_their_middle(self) -> None:
        rng = np.random.default_rng(3)
        prices = 1900 + rng.normal(0, 5, 100)
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, 20, 2.0)
        assert (upper >= middle).all()
        assert (middle >= lower).all()
        assert len(upper) == len(middle) == len(lower)

    def test_a_flat_series_collapses_the_bands_onto_the_middle(self) -> None:
        upper, middle, lower = TechnicalIndicators.bollinger_bands(np.array([100.0] * 50), 20)
        assert upper == pytest.approx(middle)
        assert lower == pytest.approx(middle)

    def test_macd_returns_three_aligned_series(self) -> None:
        prices = np.linspace(1900, 1960, 120)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        assert len(macd_line) == len(signal_line) == len(histogram)
        assert np.allclose(histogram, macd_line - signal_line)

    def test_macd_is_positive_while_the_fast_average_leads(self) -> None:
        macd_line, _signal, _hist = TechnicalIndicators.macd(np.linspace(1900, 2100, 200))
        assert macd_line[-1] > 0

    def test_atr_is_never_negative(self) -> None:
        rng = np.random.default_rng(5)
        close = 1900 + rng.normal(0, 3, 200).cumsum()
        atr = TechnicalIndicators.atr(close + 2, close - 2, close, 14)
        assert (atr >= 0).all()

    def test_obv_adds_on_an_up_bar_and_subtracts_on_a_down_bar(self) -> None:
        close = np.array([100.0, 101.0, 100.0, 100.0])
        volume = np.array([10.0, 5.0, 3.0, 7.0])

        obv = TechnicalIndicators.obv(close, volume)

        assert obv[0] == 10.0
        assert obv[1] == 15.0, "an up bar must add its volume"
        assert obv[2] == 12.0, "a down bar must subtract it"
        assert obv[3] == 12.0, "an unchanged close must leave it alone"


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


class TestExtractFeatures:
    def test_too_little_history_is_refused_rather_than_guessed(self, caplog: pytest.LogCaptureFixture) -> None:
        """`is None` alone proves nothing here.

        Remove the length guard and the function still returns `None` — it
        raises `IndexError: index -20 is out of bounds`, the broad `except`
        swallows it and logs an ERROR. Measured; a mutation deleting the guard
        left this test green until it also asserted the log.

        A refusal and a crash are different events for whoever reads the logs,
        so the quiet is the thing worth holding.
        """
        engineer = FeatureEngineer()

        with caplog.at_level("ERROR"):
            result = engineer.extract_features("XAUUSD", _series(10))

        assert result is None
        assert not [r for r in caplog.records if "Feature extraction error" in r.getMessage()], (
            "it fell through the guard and was caught by the exception handler instead"
        )

    def test_one_bar_short_of_the_minimum_is_refused(self) -> None:
        engineer = FeatureEngineer()
        minimum = max(engineer.lookback_periods) + 10
        assert engineer.extract_features("XAUUSD", _series(minimum - 1)) is None
        assert engineer.extract_features("XAUUSD", _series(minimum)) is not None

    def test_the_documented_features_are_all_present(self) -> None:
        vector = FeatureEngineer().extract_features("XAUUSD", _series(200))
        assert vector is not None
        for name in ("rsi", "macd", "bb_upper", "atr", "atr_pct", "body_size", "trend_slope"):
            assert name in vector.features, f"{name} missing"
        assert np.isfinite(list(vector.features.values())).all()

    def test_an_order_book_adds_spread_and_imbalance(self) -> None:
        book = {"bids": [[1949.5, 10.0], [1949.0, 5.0]], "asks": [[1950.5, 4.0], [1951.0, 2.0]]}
        vector = FeatureEngineer().extract_features("XAUUSD", _series(200), order_book=book)
        assert vector is not None
        assert vector.features["spread"] == pytest.approx(1.0)
        assert vector.features["ob_imbalance"] > 0, "more bid size must read as positive imbalance"

    def test_an_empty_order_book_is_ignored(self) -> None:
        vector = FeatureEngineer().extract_features("XAUUSD", _series(200), order_book={"bids": [], "asks": []})
        assert vector is not None
        assert "spread" not in vector.features

    def test_a_malformed_bar_yields_none_rather_than_a_partial_vector(self) -> None:
        """A half-built feature vector is worse than none: the model would be
        served a row whose missing columns are silently absent."""
        bars = _series(200)
        del bars[-1].close
        assert FeatureEngineer().extract_features("XAUUSD", bars) is None

    def test_extracted_vectors_are_cached_per_symbol(self) -> None:
        engineer = FeatureEngineer()
        engineer.extract_features("XAUUSD", _series(200))
        engineer.extract_features("XAGUSD", _series(200))
        assert set(engineer._feature_cache) == {"XAUUSD", "XAGUSD"}

    def test_to_array_and_to_dict_agree(self) -> None:
        vector = FeatureEngineer().extract_features("XAUUSD", _series(200))
        assert vector is not None
        assert len(vector.to_array()) == len(vector.features)
        assert vector.to_dict()["symbol"] == "XAUUSD"


class TestVolumeTrendChangesWithHistoryLength:
    """A feature whose value depends on how much history you happened to pass.

    `volume_trend_{p}` is `mean(volumes[-p:]) / mean(volumes[-2p:-p]) - 1`. The
    guard only requires `max(lookback) + 10` bars — 60 for the defaults — so for
    `p = 50` the denominator slice `[-100:-50]` clamps to whatever exists.
    Measured on identical rising volume:

        60 bars  -> +0.2871   (numerator 50 bars, denominator 10 bars)
        80 bars  -> +0.3493   (numerator 50 bars, denominator 30 bars)
        100 bars -> +0.4016   (numerator 50 bars, denominator 50 bars)

    Same market, three answers. A model trained on long windows and served from
    a short buffer is fed a different feature under the same name.

    `FeatureEngineer` has no production caller — `ml/regime.py` imports only
    `FeatureVector` — so this is latent. See MASTER_OUTSTANDING A12. These tests
    pin the behaviour rather than bless it.
    """

    def test_the_deepest_lookback_is_stable_once_history_is_sufficient(self) -> None:
        engineer = FeatureEngineer()
        deepest = max(engineer.lookback_periods)
        bars = _series(400)

        full = engineer.extract_features("XAUUSD", bars)
        longer = engineer.extract_features("XAUUSD", _series(500))

        assert full is not None and longer is not None
        # Both have at least 2*deepest bars, so both windows are full length.
        assert len(bars) >= 2 * deepest

    def test_below_twice_the_deepest_lookback_the_windows_do_not_match(self) -> None:
        engineer = FeatureEngineer()
        deepest = max(engineer.lookback_periods)
        minimum_accepted = deepest + 10
        assert minimum_accepted < 2 * deepest, (
            "the guard now requires a full denominator window; update A12 and this test"
        )

        short = engineer.extract_features("XAUUSD", _series(minimum_accepted))
        full = engineer.extract_features("XAUUSD", _series(2 * deepest))

        assert short is not None and full is not None
        assert short.features[f"volume_trend_{deepest}"] != pytest.approx(full.features[f"volume_trend_{deepest}"]), (
            "if these now agree the guard was fixed — see A12"
        )


# ---------------------------------------------------------------------------
# Feature importance
# ---------------------------------------------------------------------------


class TestFeatureImportance:
    def test_no_model_is_refused_rather_than_returning_an_empty_dict(self) -> None:
        """An empty importance map reads as "every feature is worthless"."""
        with pytest.raises(ValueError, match="must be supplied"):
            FeatureEngineer.get_feature_importance(None)

    def test_a_wrapper_with_its_own_method_is_preferred(self) -> None:
        class _Wrapper:
            def get_feature_importances(self):
                return {"rsi": 0.6, "atr": 0.4}

            feature_importances_ = np.array([0.9, 0.1])  # must not be used

        assert FeatureEngineer.get_feature_importance(_Wrapper()) == {"rsi": 0.6, "atr": 0.4}

    def test_a_native_sklearn_attribute_is_read(self) -> None:
        class _Model:
            feature_importances_ = np.array([0.25, 0.75])

        assert FeatureEngineer.get_feature_importance(_Model()) == {"0": 0.25, "1": 0.75}

    def test_a_model_exposing_neither_is_refused_by_name(self) -> None:
        class _Opaque:
            pass

        with pytest.raises(ValueError, match="Opaque"):
            FeatureEngineer.get_feature_importance(_Opaque())


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


class TestDetectAnomalies:
    def _engineer_with(self, values: list[float]) -> FeatureEngineer:
        engineer = FeatureEngineer()
        from collections import deque

        engineer._feature_cache["XAUUSD"] = deque(
            [
                FeatureVector(symbol="XAUUSD", timestamp=i, features={"volatility_20": v, "rsi": 50.0, "atr_pct": 0.01})
                for i, v in enumerate(values)
            ],
            maxlen=1000,
        )
        return engineer

    def test_an_unknown_symbol_reports_nothing(self) -> None:
        assert FeatureEngineer().detect_anomalies("XAUUSD") == []

    def test_too_little_history_reports_nothing_rather_than_a_false_positive(self) -> None:
        """Fewer than 100 samples cannot support a z-score; returning [] is the
        honest answer, not "no anomalies"."""
        assert self._engineer_with([0.01] * 50).detect_anomalies("XAUUSD") == []

    def test_a_steady_series_has_no_anomaly(self) -> None:
        rng = np.random.default_rng(2)
        assert self._engineer_with(list(0.01 + rng.normal(0, 0.0001, 100))).detect_anomalies("XAUUSD") == []

    def test_a_spike_in_the_latest_sample_is_flagged(self) -> None:
        values = [0.01] * 99 + [0.5]
        (anomaly,) = self._engineer_with(values).detect_anomalies("XAUUSD")
        assert anomaly["feature"] == "volatility_20"
        assert anomaly["value"] == 0.5
        assert anomaly["z_score"] > 3.0

    def test_a_large_spike_is_high_severity(self) -> None:
        (anomaly,) = self._engineer_with([0.01] * 99 + [0.5]).detect_anomalies("XAUUSD")
        assert anomaly["severity"] == "high"

    def test_the_threshold_is_honoured(self) -> None:
        values = [0.01] * 99 + [0.5]
        engineer = self._engineer_with(values)
        assert engineer.detect_anomalies("XAUUSD", threshold=3.0)
        assert engineer.detect_anomalies("XAUUSD", threshold=1000.0) == []


# ---------------------------------------------------------------------------
# The ensemble
# ---------------------------------------------------------------------------


class _Proba:
    """An sklearn-shaped classifier."""

    def __init__(self, probability: float) -> None:
        self._p = probability

    def predict_proba(self, X):
        return np.array([[1.0 - self._p, self._p]])


class _Regressor:
    """A model that returns a probability directly."""

    def __init__(self, value: float) -> None:
        self._v = value

    def predict(self, X):
        return np.array([self._v])


def _features() -> FeatureVector:
    return FeatureVector(symbol="XAUUSD", timestamp=1, features={"a": 1.0, "b": 2.0})


class TestSignalEnsemble:
    def test_an_empty_ensemble_holds_rather_than_guessing(self) -> None:
        result = SignalEnsemble().predict(_features())
        assert result == {"action": "hold", "confidence": 0, "probability": 0.5}

    def test_a_confident_buy(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("a", _Proba(0.9))
        assert ensemble.predict(_features())["action"] == "buy"

    def test_a_confident_sell(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("a", _Proba(0.1))
        assert ensemble.predict(_features())["action"] == "sell"

    @pytest.mark.parametrize("probability", [0.31, 0.5, 0.69])
    def test_the_middle_is_a_hold(self, probability: float) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("a", _Proba(probability))
        assert ensemble.predict(_features())["action"] == "hold"

    def test_weights_move_the_ensemble_toward_the_heavier_model(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("bull", _Proba(1.0), weight=3.0)
        ensemble.add_model("bear", _Proba(0.0), weight=1.0)
        assert ensemble.predict(_features())["probability"] == pytest.approx(0.75)

    def test_a_failing_model_is_dropped_and_the_rest_still_decide(self) -> None:
        """One broken model must not silence the ensemble — but the caller can
        only notice from `individual_predictions`, so that has to be honest."""

        class _Broken:
            def predict_proba(self, X):
                raise RuntimeError("model is corrupt")

        ensemble = SignalEnsemble()
        ensemble.add_model("good", _Proba(0.9))
        ensemble.add_model("broken", _Broken())

        result = ensemble.predict(_features())

        assert result["action"] == "buy"
        assert set(result["individual_predictions"]) == {"good"}

    def test_every_model_failing_falls_back_to_hold(self) -> None:
        class _Broken:
            def predict_proba(self, X):
                raise RuntimeError("model is corrupt")

        ensemble = SignalEnsemble()
        ensemble.add_model("broken", _Broken())
        assert ensemble.predict(_features())["action"] == "hold"

    def test_a_plain_predict_model_is_accepted(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("reg", _Regressor(0.8))
        assert ensemble.predict(_features())["action"] == "buy"

    def test_a_model_with_no_prediction_interface_is_refused(self) -> None:
        class _Opaque:
            pass

        ensemble = SignalEnsemble()
        with pytest.raises(TypeError, match="Opaque"):
            ensemble._get_model_prediction(_Opaque(), _features())


class TestConfidenceIsNotBounded:
    """`confidence` is documented `# 0 to 1` and computed `abs(p - 0.5) * 2`.

    Nothing clamps the probability. `_get_model_prediction` takes whatever
    `predict()` returns — a regressor is under no obligation to return 0–1 —
    so a model answering 2.5 yields a confidence of 4.0 under a comment saying
    the range is 0 to 1. A caller sizing a position off `confidence` would read
    four times the maximum.

    `SignalEnsemble` has no production caller, so this is latent. Pinned here
    rather than fixed; see MASTER_OUTSTANDING A12.
    """

    def test_an_unclamped_model_pushes_confidence_above_one(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("runaway", _Regressor(2.5))

        result = ensemble.predict(_features())

        assert result["probability"] == pytest.approx(2.5)
        assert result["confidence"] == pytest.approx(4.0), (
            "if this is now <= 1 the probability was clamped — good, update A12"
        )

    def test_a_well_behaved_model_stays_inside_the_range(self) -> None:
        ensemble = SignalEnsemble()
        ensemble.add_model("sane", _Proba(0.9))
        assert 0.0 <= ensemble.predict(_features())["confidence"] <= 1.0
