# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_risk_lookahead_guard.py
=======================================
Full coverage tests for risk/lookahead_guard.py.

Covers:
- FeatureTimestampGuard: strict/non-strict, violations log, reset
- BacktestBarGuard: iteration, get(), get_slice(), non-strict mode
- no_lookahead_context: DataFrame.shift(-N) and Series.shift(-N) raise
- LiveTradingGuard: future timestamp, stale data, NaN price, non-positive price,
  non-strict mode, bid/ask midpoint extraction, missing timestamp
- Helper functions: _to_epoch, _fmt, _extract_tick_ts, _extract_price
- Module-level singletons: feature_guard, live_guard
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from risk.lookahead_guard import (
    BacktestBarGuard,
    FeatureTimestampGuard,
    FutureTimestampError,
    LookAheadBiasError,
    LiveTradingGuard,
    StaleDataError,
    _extract_price,
    _extract_tick_ts,
    _fmt,
    _to_epoch,
    feature_guard,
    live_guard,
    no_lookahead_context,
)

UTC = timezone.utc
RNG = np.random.default_rng(42)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_df(n: int = 10) -> pd.DataFrame:
    close = 2000.0 + np.arange(n, dtype=float)
    return pd.DataFrame({"close": close, "volume": np.ones(n) * 1000})


def _now_epoch() -> float:
    return time.time()


# ── _to_epoch ─────────────────────────────────────────────────────────────────


class TestToEpoch:
    def test_datetime_input(self):
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        result = _to_epoch(dt)
        assert isinstance(result, float)
        assert result == dt.timestamp()

    def test_float_input(self):
        epoch = 1_700_000_000.0
        assert _to_epoch(epoch) == epoch

    def test_int_input(self):
        epoch = 1_700_000_000
        assert _to_epoch(epoch) == float(epoch)


# ── _fmt ──────────────────────────────────────────────────────────────────────


class TestFmt:
    def test_valid_epoch(self):
        epoch = datetime(2024, 6, 1, tzinfo=UTC).timestamp()
        result = _fmt(epoch)
        assert "2024" in result

    def test_overflow_epoch(self):
        # Should not raise; returns str representation
        result = _fmt(1e20)
        assert isinstance(result, str)


# ── _extract_tick_ts ──────────────────────────────────────────────────────────


class TestExtractTickTs:
    def test_dict_with_timestamp(self):
        tick = {"timestamp": _now_epoch()}
        result = _extract_tick_ts(tick)
        assert result is not None
        assert abs(result - _now_epoch()) < 2.0

    def test_dict_with_ts(self):
        epoch = _now_epoch()
        tick = {"ts": epoch}
        assert abs(_extract_tick_ts(tick) - epoch) < 0.01

    def test_dict_with_datetime(self):
        dt = datetime.now(UTC)
        tick = {"datetime": dt}
        result = _extract_tick_ts(tick)
        assert result is not None
        assert abs(result - dt.timestamp()) < 0.01

    def test_dict_millisecond_timestamp(self):
        # Timestamps > 4_102_444_800 are treated as milliseconds
        epoch_ms = _now_epoch() * 1000
        tick = {"timestamp": epoch_ms}
        result = _extract_tick_ts(tick)
        assert result is not None
        assert abs(result - _now_epoch()) < 2.0

    def test_object_with_timestamp_attr(self):
        class Tick:
            timestamp = _now_epoch()

        result = _extract_tick_ts(Tick())
        assert result is not None

    def test_no_timestamp_returns_none(self):
        tick = {"price": 2000.0}
        assert _extract_tick_ts(tick) is None

    def test_invalid_timestamp_value(self):
        tick = {"timestamp": "not-a-number"}
        assert _extract_tick_ts(tick) is None


# ── _extract_price ────────────────────────────────────────────────────────────


class TestExtractPrice:
    def test_dict_price(self):
        tick = {"price": 2000.5}
        assert _extract_price(tick) == 2000.5

    def test_dict_close(self):
        tick = {"close": 1999.0}
        assert _extract_price(tick) == 1999.0

    def test_dict_last(self):
        tick = {"last": 2001.0}
        assert _extract_price(tick) == 2001.0

    def test_dict_mid(self):
        tick = {"mid": 2002.0}
        assert _extract_price(tick) == 2002.0

    def test_bid_ask_midpoint(self):
        tick = {"bid": 1999.0, "ask": 2001.0}
        result = _extract_price(tick)
        assert result == pytest.approx(2000.0)

    def test_object_price_attr(self):
        class Tick:
            price = 1950.0

        assert _extract_price(Tick()) == 1950.0

    def test_no_price_returns_none(self):
        tick = {"volume": 1000}
        assert _extract_price(tick) is None

    def test_invalid_price_value(self):
        tick = {"price": "bad"}
        assert _extract_price(tick) is None


# ── FeatureTimestampGuard ─────────────────────────────────────────────────────


class TestFeatureTimestampGuard:
    def test_valid_no_violation(self):
        guard = FeatureTimestampGuard(strict=True)
        now = _now_epoch()
        guard.validate(features_ts=now - 10, decision_ts=now)
        assert len(guard.get_violations()) == 0

    def test_equal_timestamps_ok(self):
        guard = FeatureTimestampGuard(strict=True)
        now = _now_epoch()
        guard.validate(features_ts=now, decision_ts=now)
        assert len(guard.get_violations()) == 0

    def test_strict_raises_on_future_features(self):
        guard = FeatureTimestampGuard(strict=True)
        now = _now_epoch()
        with pytest.raises(LookAheadBiasError, match="Look-ahead bias"):
            guard.validate(features_ts=now + 100, decision_ts=now)

    def test_strict_records_violation(self):
        guard = FeatureTimestampGuard(strict=True)
        now = _now_epoch()
        with pytest.raises(LookAheadBiasError):
            guard.validate(features_ts=now + 100, decision_ts=now, context="test_ctx")
        violations = guard.get_violations()
        assert len(violations) == 1
        assert violations[0]["context"] == "test_ctx"

    def test_non_strict_logs_not_raises(self):
        guard = FeatureTimestampGuard(strict=False)
        now = _now_epoch()
        guard.validate(features_ts=now + 100, decision_ts=now)
        assert len(guard.get_violations()) == 1

    def test_reset_clears_violations(self):
        guard = FeatureTimestampGuard(strict=False)
        now = _now_epoch()
        guard.validate(features_ts=now + 100, decision_ts=now)
        guard.reset()
        assert len(guard.get_violations()) == 0

    def test_datetime_inputs(self):
        guard = FeatureTimestampGuard(strict=True)
        past = datetime(2024, 1, 1, tzinfo=UTC)
        now = datetime(2024, 6, 1, tzinfo=UTC)
        guard.validate(features_ts=past, decision_ts=now)
        assert len(guard.get_violations()) == 0

    def test_violations_capped_at_1000(self):
        guard = FeatureTimestampGuard(strict=False)
        now = _now_epoch()
        for _ in range(1100):
            guard.validate(features_ts=now + 100, decision_ts=now)
        assert len(guard.get_violations()) <= 1000

    def test_within_tolerance_no_violation(self):
        guard = FeatureTimestampGuard(strict=True)
        now = _now_epoch()
        # 0.5ms in the future — within 1ms tolerance
        guard.validate(features_ts=now + 0.0005, decision_ts=now)
        assert len(guard.get_violations()) == 0


# ── BacktestBarGuard ──────────────────────────────────────────────────────────


class TestBacktestBarGuard:
    def test_iteration_yields_all_rows(self):
        df = _make_df(5)
        guard = BacktestBarGuard(df)
        rows = list(guard)
        assert len(rows) == 5

    def test_current_index_advances(self):
        df = _make_df(3)
        guard = BacktestBarGuard(df)
        indices = []
        for _ in guard:
            indices.append(guard.current_index)
        assert indices == [0, 1, 2]

    def test_len(self):
        df = _make_df(7)
        guard = BacktestBarGuard(df)
        assert len(guard) == 7

    def test_get_current_bar_ok(self):
        df = _make_df(5)
        guard = BacktestBarGuard(df)
        for _ in guard:
            bar = guard.get(guard.current_index)
            assert bar is not None

    def test_get_past_bar_ok(self):
        df = _make_df(5)
        guard = BacktestBarGuard(df)
        list(guard)
        # After full iteration, current_index == 4; get(0) is past
        bar = guard.get(0)
        assert bar["close"] == df.iloc[0]["close"]

    def test_get_future_bar_raises(self):
        df = _make_df(5)
        guard = BacktestBarGuard(df)
        it = iter(guard)
        next(it)  # current_index = 0
        with pytest.raises(LookAheadBiasError, match="Look-ahead bias"):
            guard.get(3)

    def test_get_future_bar_non_strict(self):
        df = _make_df(5)
        guard = BacktestBarGuard(df, strict=False)
        it = iter(guard)
        next(it)  # current_index = 0
        bar = guard.get(3)  # should not raise
        assert bar is not None
        assert len(guard.get_violations()) == 1

    def test_get_slice_ok(self):
        df = _make_df(10)
        guard = BacktestBarGuard(df)
        list(guard)  # advance to end
        slc = guard.get_slice(0, 5)
        assert len(slc) == 5

    def test_get_slice_future_raises(self):
        df = _make_df(10)
        guard = BacktestBarGuard(df)
        it = iter(guard)
        next(it)  # current_index = 0
        with pytest.raises(LookAheadBiasError):
            guard.get_slice(0, 5)

    def test_get_slice_non_strict(self):
        df = _make_df(10)
        guard = BacktestBarGuard(df, strict=False)
        it = iter(guard)
        next(it)  # current_index = 0
        slc = guard.get_slice(0, 5)
        assert len(slc) == 5

    def test_requires_dataframe(self):
        with pytest.raises(TypeError):
            BacktestBarGuard([1, 2, 3])  # type: ignore[arg-type]

    def test_get_violations_empty_initially(self):
        df = _make_df(3)
        guard = BacktestBarGuard(df)
        assert guard.get_violations() == []


# ── no_lookahead_context ──────────────────────────────────────────────────────


class TestNoLookaheadContext:
    def test_positive_shift_allowed(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        with no_lookahead_context("test"):
            shifted = df["a"].shift(1)
        assert shifted.iloc[1] == 1.0

    def test_negative_df_shift_raises(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        with pytest.raises(LookAheadBiasError, match="shift"):
            with no_lookahead_context("feature_eng"):
                df.shift(-1)

    def test_negative_series_shift_raises(self):
        s = pd.Series([1, 2, 3, 4, 5])
        with pytest.raises(LookAheadBiasError, match="shift"):
            with no_lookahead_context("label_creation"):
                s.shift(-1)

    def test_shift_restored_after_context(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        with no_lookahead_context():
            pass
        # After context, negative shift should work normally
        result = df["a"].shift(-1)
        assert result.iloc[0] == 2.0

    def test_shift_restored_after_exception(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        try:
            with no_lookahead_context():
                df.shift(-1)
        except LookAheadBiasError:
            pass
        # Shift should be restored even after exception
        result = df["a"].shift(-1)
        assert result.iloc[0] == 2.0

    def test_label_without_context(self):
        # Outside the guard, negative shift is fine (label creation)
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]})
        labels = df["close"].shift(-1) > df["close"]
        assert labels.iloc[0] is True or labels.iloc[0] is np.bool_(True)


# ── LiveTradingGuard ──────────────────────────────────────────────────────────


class TestLiveTradingGuard:
    def test_valid_tick_passes(self):
        guard = LiveTradingGuard(max_staleness_seconds=30, strict=True)
        tick = {"timestamp": _now_epoch(), "price": 2000.0}
        guard.validate_tick(tick, symbol="XAUUSD")
        assert len(guard.get_violations()) == 0

    def test_future_timestamp_raises(self):
        guard = LiveTradingGuard(max_future_seconds=2.0, strict=True)
        tick = {"timestamp": _now_epoch() + 100, "price": 2000.0}
        with pytest.raises(FutureTimestampError, match="future"):
            guard.validate_tick(tick, symbol="XAUUSD")

    def test_future_timestamp_non_strict(self):
        guard = LiveTradingGuard(max_future_seconds=2.0, strict=False)
        tick = {"timestamp": _now_epoch() + 100, "price": 2000.0}
        guard.validate_tick(tick, symbol="XAUUSD")
        assert len(guard.get_violations()) == 1
        assert guard.get_violations()[0]["kind"] == "future_timestamp"

    def test_stale_tick_raises(self):
        guard = LiveTradingGuard(max_staleness_seconds=5, strict=True)
        tick = {"timestamp": _now_epoch() - 100, "price": 2000.0}
        with pytest.raises(StaleDataError):
            guard.validate_tick(tick, symbol="XAUUSD")

    def test_stale_tick_non_strict(self):
        guard = LiveTradingGuard(max_staleness_seconds=5, strict=False)
        tick = {"timestamp": _now_epoch() - 100, "price": 2000.0}
        guard.validate_tick(tick, symbol="XAUUSD")
        assert any(v["kind"] == "stale_data" for v in guard.get_violations())

    def test_nan_price_raises(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"timestamp": _now_epoch(), "price": float("nan")}
        with pytest.raises(LookAheadBiasError, match="NaN"):
            guard.validate_tick(tick)

    def test_inf_price_raises(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"timestamp": _now_epoch(), "price": float("inf")}
        with pytest.raises(LookAheadBiasError, match="NaN"):
            guard.validate_tick(tick)

    def test_nonpositive_price_raises(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"timestamp": _now_epoch(), "price": -5.0}
        with pytest.raises(LookAheadBiasError, match="Non-positive"):
            guard.validate_tick(tick)

    def test_zero_price_raises(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"timestamp": _now_epoch(), "price": 0.0}
        with pytest.raises(LookAheadBiasError, match="Non-positive"):
            guard.validate_tick(tick)

    def test_nan_price_non_strict(self):
        guard = LiveTradingGuard(strict=False)
        tick = {"timestamp": _now_epoch(), "price": float("nan")}
        guard.validate_tick(tick)
        assert any(v["kind"] == "invalid_price" for v in guard.get_violations())

    def test_nonpositive_price_non_strict(self):
        guard = LiveTradingGuard(strict=False)
        tick = {"timestamp": _now_epoch(), "price": -1.0}
        guard.validate_tick(tick)
        assert any(v["kind"] == "nonpositive_price" for v in guard.get_violations())

    def test_bid_ask_midpoint_valid(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"timestamp": _now_epoch(), "bid": 1999.0, "ask": 2001.0}
        guard.validate_tick(tick)
        assert len(guard.get_violations()) == 0

    def test_no_timestamp_still_validates_price(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"price": 2000.0}
        guard.validate_tick(tick)
        assert len(guard.get_violations()) == 0

    def test_no_timestamp_nan_price_raises(self):
        guard = LiveTradingGuard(strict=True)
        tick = {"price": float("nan")}
        with pytest.raises(LookAheadBiasError):
            guard.validate_tick(tick)

    def test_reset_clears_violations(self):
        guard = LiveTradingGuard(max_staleness_seconds=5, strict=False)
        tick = {"timestamp": _now_epoch() - 100, "price": 2000.0}
        guard.validate_tick(tick)
        guard.reset()
        assert len(guard.get_violations()) == 0

    def test_violations_capped_at_500(self):
        guard = LiveTradingGuard(max_staleness_seconds=5, strict=False)
        tick = {"timestamp": _now_epoch() - 100, "price": 2000.0}
        for _ in range(600):
            guard.validate_tick(tick)
        assert len(guard.get_violations()) <= 500

    def test_symbol_in_violation_message(self):
        guard = LiveTradingGuard(max_staleness_seconds=5, strict=False)
        tick = {"timestamp": _now_epoch() - 100, "price": 2000.0}
        guard.validate_tick(tick, symbol="XAUUSD")
        assert guard.get_violations()[0]["symbol"] == "XAUUSD"

    def test_object_tick_with_attrs(self):
        guard = LiveTradingGuard(strict=True)

        class Tick:
            timestamp = _now_epoch()
            price = 2000.0

        guard.validate_tick(Tick())
        assert len(guard.get_violations()) == 0


# ── Module-level singletons ───────────────────────────────────────────────────


class TestModuleSingletons:
    def test_feature_guard_is_instance(self):
        assert isinstance(feature_guard, FeatureTimestampGuard)
        assert feature_guard.strict is True

    def test_live_guard_is_instance(self):
        assert isinstance(live_guard, LiveTradingGuard)
        assert live_guard.max_staleness_seconds == 30
        assert live_guard.strict is True

    def test_feature_guard_validates(self):
        now = _now_epoch()
        feature_guard.validate(features_ts=now - 5, decision_ts=now)

    def test_live_guard_validates_valid_tick(self):
        tick = {"timestamp": _now_epoch(), "price": 2000.0}
        live_guard.validate_tick(tick)
