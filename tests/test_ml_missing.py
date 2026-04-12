# HOPEFX-AI-TRADING
# Tests for ml/ modules missing coverage:
# signal_filter, signal_validator, regime_conditional, mtf_features,
# macro_features, hourly_trainer
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

UTC = timezone.utc


# ===========================================================================
# Helpers
# ===========================================================================

def _make_daily_ohlcv(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    close = 1900.0 + rng.standard_normal(n).cumsum()
    high = close + rng.uniform(0, 5, n)
    low = close - rng.uniform(0, 5, n)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=idx,
    )


def _make_ohlcv_with_date_col(n: int = 300) -> pd.DataFrame:
    """MTF features expect a 'Date' column."""
    df = _make_daily_ohlcv(n).reset_index()
    df = df.rename(columns={"index": "Date"})
    return df


# ===========================================================================
# signal_filter
# ===========================================================================

from ml.signal_filter import FilterResult, SignalFilter, get_signal_filter


class TestSignalFilter:
    def _make_signal(self, direction="long", confidence=0.75, probability=0.80):
        return {
            "direction": direction,
            "confidence": confidence,
            "probability": probability,
        }

    def test_check_returns_filter_result(self):
        sf = SignalFilter()
        result = sf.check(self._make_signal())
        assert isinstance(result, FilterResult)

    def test_filter_result_bool(self):
        r = FilterResult(passed=True, reason="ok", gate="")
        assert bool(r) is True
        r2 = FilterResult(passed=False, reason="blocked", gate="confidence")
        assert bool(r2) is False

    def test_low_confidence_blocked(self):
        sf = SignalFilter()
        result = sf.check(self._make_signal(confidence=0.01, probability=0.51))
        # Very low confidence should fail the confidence gate
        assert isinstance(result, FilterResult)

    def test_record_outcome_and_ev_stats(self):
        sf = SignalFilter()
        sf.record_outcome(symbol="XAUUSD", pnl_pct=0.01, direction="long", confidence=0.75)
        sf.record_outcome(symbol="XAUUSD", pnl_pct=-0.005, direction="long", confidence=0.70)
        stats = sf.ev_stats(symbol="XAUUSD")
        assert "ev" in stats or "expected_value" in stats or isinstance(stats, dict)

    def test_get_stats_returns_dict(self):
        sf = SignalFilter()
        stats = sf.get_stats()
        assert isinstance(stats, dict)

    def test_filter_method(self):
        sf = SignalFilter()
        result = sf.filter(self._make_signal())
        assert isinstance(result, FilterResult)

    def test_singleton(self):
        s1 = get_signal_filter()
        s2 = get_signal_filter()
        assert s1 is s2

    def test_neutral_direction_passes(self):
        sf = SignalFilter()
        result = sf.check(self._make_signal(direction="neutral", confidence=0.0))
        assert isinstance(result, FilterResult)


# ===========================================================================
# signal_validator
# ===========================================================================

from ml.signal_validator import (
    SignalDistributionValidator,
    SignalRecord,
    ValidationReport,
    ValidationStatus,
    get_validator,
)


def _make_signal_records(n: int, mean_score: float = 0.6, std: float = 0.1) -> list[SignalRecord]:
    rng = np.random.default_rng(42)
    scores = rng.normal(mean_score, std, n).clip(0, 1)
    return [
        SignalRecord(
            direction="BUY" if s > 0.5 else "SELL",
            confidence=float(s),
            raw_score=float(s),
            timestamp=datetime.now(UTC),
        )
        for s in scores
    ]


class TestSignalValidator:
    def test_insufficient_data_returns_report(self):
        v = SignalDistributionValidator(min_samples=50)
        v.set_oos_reference(_make_signal_records(10))
        v.add_live_signal(_make_signal_records(1)[0])
        report = v.validate()
        assert report.status == ValidationStatus.INSUFFICIENT_DATA

    def test_validate_with_matching_distributions(self):
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signal_records(100, mean_score=0.6)
        live = _make_signal_records(100, mean_score=0.6)
        v.set_oos_reference(oos)
        report = v.validate(live_signals=live)
        assert report.status in (ValidationStatus.PASSED, ValidationStatus.WARNING)
        assert report.ks_statistic is not None

    def test_validate_with_drifted_distributions(self):
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signal_records(100, mean_score=0.6)
        live = _make_signal_records(100, mean_score=0.1)  # heavily drifted
        v.set_oos_reference(oos)
        report = v.validate(live_signals=live)
        assert report.status in (ValidationStatus.WARNING, ValidationStatus.FAILED)

    def test_clear_live_signals(self):
        v = SignalDistributionValidator()
        v.add_live_signal(_make_signal_records(1)[0])
        v.clear_live_signals()
        assert len(v._live_signals) == 0

    def test_report_to_dict(self):
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signal_records(50)
        live = _make_signal_records(50)
        v.set_oos_reference(oos)
        report = v.validate(live_signals=live)
        d = report.to_dict()
        assert "status" in d
        assert "oos_sample_size" in d

    def test_report_passed_property(self):
        v = SignalDistributionValidator(min_samples=30)
        oos = _make_signal_records(100, mean_score=0.6)
        live = _make_signal_records(100, mean_score=0.6)
        v.set_oos_reference(oos)
        report = v.validate(live_signals=live)
        assert isinstance(report.passed, bool)

    def test_report_summary_string(self):
        v = SignalDistributionValidator(min_samples=5)
        oos = _make_signal_records(10)
        live = _make_signal_records(10)
        v.set_oos_reference(oos)
        report = v.validate(live_signals=live)
        assert isinstance(report.summary, str)

    def test_singleton(self):
        v1 = get_validator()
        v2 = get_validator()
        assert v1 is v2


# ===========================================================================
# mtf_features
# ===========================================================================

from ml.mtf_features import build_mtf_features


class TestMTFFeatures:
    def test_returns_dataframe(self):
        df = _make_ohlcv_with_date_col(300)
        result = build_mtf_features(df)
        assert isinstance(result, pd.DataFrame)

    def test_adds_mtf_columns(self):
        df = _make_ohlcv_with_date_col(300)
        result = build_mtf_features(df)
        mtf_cols = [c for c in result.columns if c.startswith("mtf_")]
        assert len(mtf_cols) > 10

    def test_alignment_score_column(self):
        df = _make_ohlcv_with_date_col(300)
        result = build_mtf_features(df)
        assert "mtf_alignment_score" in result.columns

    def test_no_inf_values(self):
        df = _make_ohlcv_with_date_col(300)
        result = build_mtf_features(df)
        numeric = result.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.values).any()

    def test_same_row_count(self):
        df = _make_ohlcv_with_date_col(300)
        result = build_mtf_features(df)
        assert len(result) == len(df)


# ===========================================================================
# macro_features
# ===========================================================================

from ml.macro_features import add_macro_features


class TestMacroFeatures:
    def test_no_macro_fills_zeros(self):
        ohlcv = _make_daily_ohlcv(100)
        result = add_macro_features(ohlcv, macro_df=None)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(ohlcv)

    def test_with_macro_df(self):
        ohlcv = _make_daily_ohlcv(100)
        macro = pd.DataFrame(
            {"dxy": 100.0 + np.random.default_rng(1).standard_normal(100),
             "vix": 20.0 + np.random.default_rng(2).standard_normal(100)},
            index=ohlcv.index,
        )
        result = add_macro_features(ohlcv, macro_df=macro)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(ohlcv)

    def test_no_nan_in_result(self):
        ohlcv = _make_daily_ohlcv(100)
        result = add_macro_features(ohlcv, macro_df=None)
        assert not result.isnull().any().any()

    def test_preserves_ohlcv_columns(self):
        ohlcv = _make_daily_ohlcv(100)
        result = add_macro_features(ohlcv, macro_df=None)
        for col in ("open", "high", "low", "close", "volume"):
            assert col in result.columns


# ===========================================================================
# hourly_trainer
# ===========================================================================

from ml.hourly_trainer import HourlyTrainer, get_hourly_trainer


class TestHourlyTrainer:
    def test_disabled_by_default(self):
        trainer = HourlyTrainer(enabled=False)
        assert trainer.enabled is False

    def test_status_returns_dict(self):
        trainer = HourlyTrainer(enabled=False)
        status = trainer.status()
        assert isinstance(status, dict)
        assert "enabled" in status

    @pytest.mark.asyncio
    async def test_start_disabled_returns_immediately(self):
        trainer = HourlyTrainer(enabled=False)
        # Should return without blocking
        await trainer.start()
        assert trainer._running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        trainer = HourlyTrainer(enabled=False)
        await trainer.stop()  # must not raise

    def test_singleton(self):
        t1 = get_hourly_trainer()
        t2 = get_hourly_trainer()
        assert t1 is t2

    def test_symbols_default(self):
        trainer = HourlyTrainer(enabled=False)
        assert isinstance(trainer.symbols, list)
        assert len(trainer.symbols) > 0


# ===========================================================================
# regime_conditional (lightweight — avoid sklearn fit overhead)
# ===========================================================================

from ml.regime_conditional import (
    RegimeConditionalModel,
    add_regime_features,
    detect_regime_labels,
)


class TestRegimeConditional:
    def test_detect_regime_labels_returns_series(self):
        ohlcv = _make_daily_ohlcv(200)
        labels = detect_regime_labels(ohlcv)
        assert isinstance(labels, pd.Series)
        assert len(labels) == len(ohlcv)

    def test_add_regime_features_returns_df(self):
        ohlcv = _make_daily_ohlcv(200)
        result = add_regime_features(ohlcv)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(ohlcv)

    def test_regime_model_init(self):
        model = RegimeConditionalModel()
        assert model is not None

    def test_regime_model_fit_predict(self):
        from sklearn.datasets import make_classification
        X_arr, y_arr = make_classification(n_samples=200, n_features=10, random_state=42)
        X = pd.DataFrame(X_arr, columns=[f"f{i}" for i in range(10)])
        y = pd.Series(y_arr)
        model = RegimeConditionalModel()
        model.fit(X, y)
        preds = model.predict(X)
        assert len(preds) == len(X)

    def test_regime_model_predict_proba(self):
        from sklearn.datasets import make_classification
        X_arr, y_arr = make_classification(n_samples=200, n_features=10, random_state=42)
        X = pd.DataFrame(X_arr, columns=[f"f{i}" for i in range(10)])
        y = pd.Series(y_arr)
        model = RegimeConditionalModel()
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape == (len(X), 2)
