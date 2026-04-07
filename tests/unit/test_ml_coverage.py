# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for ml/signal_features.py and ml/signal_validator.py.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# ml/signal_features.py  (renamed from ml/features.py to resolve package shadow)
# ─────────────────────────────────────────────────────────────────────────────

from ml.signal_features import FeatureVector, SignalEnsemble, TechnicalIndicators


@pytest.mark.unit
class TestFeatureVector:
    def test_to_array(self):
        fv = FeatureVector(symbol="XAUUSD", timestamp=1.0,
                           features={"a": 1.0, "b": 2.0, "c": 3.0})
        arr = fv.to_array()
        assert isinstance(arr, np.ndarray)
        assert arr.shape == (3,)

    def test_to_dict_keys(self):
        fv = FeatureVector(symbol="XAUUSD", timestamp=1.0,
                           features={"x": 0.5}, label=1.0)
        d = fv.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["label"] == pytest.approx(1.0)
        assert "features" in d

    def test_label_defaults_none(self):
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={})
        assert fv.label is None


@pytest.mark.unit
class TestTechnicalIndicators:
    def test_sma_length(self):
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = TechnicalIndicators.sma(prices, period=3)
        assert len(result) == 3  # mode='valid'

    def test_sma_values(self):
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = TechnicalIndicators.sma(prices, period=3)
        assert result[0] == pytest.approx(2.0)
        assert result[-1] == pytest.approx(4.0)

    def test_ema_same_length(self):
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = TechnicalIndicators.ema(prices, period=3)
        assert len(result) == len(prices)

    def test_ema_first_value_equals_first_price(self):
        prices = np.array([10.0, 11.0, 12.0])
        result = TechnicalIndicators.ema(prices, period=2)
        assert result[0] == pytest.approx(10.0)

    def test_ema_trending_up(self):
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = TechnicalIndicators.ema(prices, period=2)
        assert result[-1] > result[0]


@pytest.mark.unit
class TestSignalEnsemble:
    def test_add_model(self):
        ens = SignalEnsemble()
        model = MagicMock()
        ens.add_model("m1", model, weight=1.0)
        assert "m1" in ens.models

    def test_predict_no_models_returns_hold(self):
        ens = SignalEnsemble()
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "hold"
        assert result["confidence"] == 0

    def test_predict_with_predict_proba_model(self):
        ens = SignalEnsemble()
        model = MagicMock()
        model.predict_proba = MagicMock(return_value=np.array([[0.1, 0.9]]))
        ens.add_model("m1", model, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "buy"
        assert result["probability"] == pytest.approx(0.9)

    def test_predict_with_predict_model(self):
        ens = SignalEnsemble()
        model = MagicMock(spec=[])  # no predict_proba
        model.predict = MagicMock(return_value=np.array([0.2]))
        ens.add_model("m1", model, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "sell"

    def test_predict_sell_signal(self):
        ens = SignalEnsemble()
        model = MagicMock()
        model.predict_proba = MagicMock(return_value=np.array([[0.8, 0.2]]))
        ens.add_model("m1", model, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "sell"

    def test_predict_hold_signal(self):
        ens = SignalEnsemble()
        model = MagicMock()
        model.predict_proba = MagicMock(return_value=np.array([[0.5, 0.5]]))
        ens.add_model("m1", model, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "hold"

    def test_predict_model_error_skipped(self):
        ens = SignalEnsemble()
        bad_model = MagicMock()
        bad_model.predict_proba = MagicMock(side_effect=RuntimeError("boom"))
        ens.add_model("bad", bad_model, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        assert result["action"] == "hold"

    def test_get_model_prediction_no_interface_raises(self):
        ens = SignalEnsemble()
        bad_model = object()  # no predict_proba or predict
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        with pytest.raises(TypeError):
            ens._get_model_prediction(bad_model, fv)

    def test_weighted_ensemble(self):
        ens = SignalEnsemble()
        m1 = MagicMock()
        m1.predict_proba = MagicMock(return_value=np.array([[0.1, 0.9]]))
        m2 = MagicMock()
        m2.predict_proba = MagicMock(return_value=np.array([[0.9, 0.1]]))
        ens.add_model("m1", m1, weight=3.0)
        ens.add_model("m2", m2, weight=1.0)
        fv = FeatureVector(symbol="XAUUSD", timestamp=0.0, features={"a": 1.0})
        result = ens.predict(fv)
        # Weighted: (0.9*3 + 0.1*1) / 4 = 0.7 → buy
        assert result["action"] == "buy"


# ─────────────────────────────────────────────────────────────────────────────
# ml/signal_validator.py
# ─────────────────────────────────────────────────────────────────────────────

def _make_signals(n=50, direction="BUY", mean=0.0, std=0.1, conf=0.7):
    from ml.signal_validator import SignalRecord
    rng = np.random.default_rng(42)
    return [
        SignalRecord(
            direction=direction,
            confidence=float(np.clip(rng.normal(conf, 0.05), 0, 1)),
            raw_score=float(rng.normal(mean, std)),
            timestamp=datetime.now(UTC),
        )
        for _ in range(n)
    ]


@pytest.mark.unit
class TestSignalRecord:
    def test_defaults(self):
        from ml.signal_validator import SignalRecord
        s = SignalRecord(direction="BUY", confidence=0.8, raw_score=0.6)
        assert s.timestamp is None

    def test_with_timestamp(self):
        from ml.signal_validator import SignalRecord
        ts = datetime.now(UTC)
        s = SignalRecord(direction="SELL", confidence=0.6, raw_score=-0.3, timestamp=ts)
        assert s.timestamp == ts


@pytest.mark.unit
class TestValidationReport:
    def test_passed_property(self):
        from ml.signal_validator import ValidationReport, ValidationStatus
        r = ValidationReport(
            timestamp=datetime.now(UTC),
            status=ValidationStatus.PASSED,
            oos_sample_size=50,
            live_sample_size=50,
        )
        assert r.passed is True

    def test_failed_property(self):
        from ml.signal_validator import ValidationReport, ValidationStatus
        r = ValidationReport(
            timestamp=datetime.now(UTC),
            status=ValidationStatus.FAILED,
            oos_sample_size=50,
            live_sample_size=50,
        )
        assert r.passed is False

    def test_to_dict_keys(self):
        from ml.signal_validator import ValidationReport, ValidationStatus
        r = ValidationReport(
            timestamp=datetime.now(UTC),
            status=ValidationStatus.PASSED,
            oos_sample_size=50,
            live_sample_size=50,
        )
        d = r.to_dict()
        for key in ("timestamp", "status", "oos_sample_size", "live_sample_size",
                    "psi", "ks_statistic", "ks_p_value", "passed", "checks"):
            assert key in d

    def test_summary_string(self):
        from ml.signal_validator import ValidationReport, ValidationStatus
        r = ValidationReport(
            timestamp=datetime.now(UTC),
            status=ValidationStatus.WARNING,
            oos_sample_size=50,
            live_sample_size=50,
        )
        s = r.summary
        assert "WARNING" in s.upper()


@pytest.mark.unit
class TestSignalDistributionValidator:
    def test_insufficient_data_when_too_few_samples(self):
        from ml.signal_validator import SignalDistributionValidator, ValidationStatus
        v = SignalDistributionValidator(min_samples=30)
        v.set_oos_reference(_make_signals(10))
        report = v.validate(_make_signals(10))
        assert report.status == ValidationStatus.INSUFFICIENT_DATA

    def test_passed_when_distributions_match(self):
        from ml.signal_validator import SignalDistributionValidator, ValidationStatus
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signals(100, mean=0.0, std=0.1, conf=0.7)
        live = _make_signals(100, mean=0.0, std=0.1, conf=0.7)
        v.set_oos_reference(oos)
        report = v.validate(live)
        assert report.status in (ValidationStatus.PASSED, ValidationStatus.WARNING)

    def test_failed_when_distributions_diverge(self):
        from ml.signal_validator import SignalDistributionValidator, ValidationStatus
        v = SignalDistributionValidator(min_samples=30, psi_fail=0.01)
        oos = _make_signals(100, mean=0.0, std=0.05)
        live = _make_signals(100, mean=5.0, std=0.05)  # huge drift
        v.set_oos_reference(oos)
        report = v.validate(live)
        assert report.status in (ValidationStatus.FAILED, ValidationStatus.WARNING)

    def test_add_live_signal_accumulates(self):
        from ml.signal_validator import SignalDistributionValidator
        v = SignalDistributionValidator()
        sig = _make_signals(1)[0]
        v.add_live_signal(sig)
        assert len(v._live_signals) == 1

    def test_clear_live_signals(self):
        from ml.signal_validator import SignalDistributionValidator
        v = SignalDistributionValidator()
        for s in _make_signals(5):
            v.add_live_signal(s)
        v.clear_live_signals()
        assert len(v._live_signals) == 0

    def test_validate_uses_internal_buffer(self):
        from ml.signal_validator import SignalDistributionValidator, ValidationStatus
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signals(50)
        live = _make_signals(50)
        v.set_oos_reference(oos)
        for s in live:
            v.add_live_signal(s)
        report = v.validate()  # no argument → uses buffer
        assert report.live_sample_size == 50

    def test_report_has_psi_and_ks(self):
        from ml.signal_validator import SignalDistributionValidator
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signals(50)
        live = _make_signals(50)
        v.set_oos_reference(oos)
        report = v.validate(live)
        assert report.psi is not None
        assert report.ks_statistic is not None
        assert report.ks_p_value is not None

    def test_get_validator_singleton(self):
        from ml.signal_validator import get_validator, SignalDistributionValidator
        v = get_validator()
        assert isinstance(v, SignalDistributionValidator)

    def test_compute_psi_identical_distributions(self):
        from ml.signal_validator import _compute_psi
        data = np.random.default_rng(0).normal(0, 1, 200)
        psi = _compute_psi(data, data)
        assert psi == pytest.approx(0.0, abs=0.01)

    def test_compute_psi_different_distributions(self):
        from ml.signal_validator import _compute_psi
        ref = np.random.default_rng(0).normal(0, 1, 200)
        cur = np.random.default_rng(1).normal(5, 1, 200)
        psi = _compute_psi(ref, cur)
        assert psi > 0.25  # major shift

    def test_compute_psi_constant_returns_zero(self):
        from ml.signal_validator import _compute_psi
        data = np.ones(100)
        psi = _compute_psi(data, data)
        assert psi == pytest.approx(0.0)
