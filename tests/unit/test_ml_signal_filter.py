# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_signal_filter.py
===================================
`ml/signal_filter.py` was 325 statements at 67.73 %.

`execution/trade_executor.py` imports this, and `api/ml.py`, `api/admin.py` and
`core/signal_engine.py` all import it too. It is the last thing between a model
probability and an order: six gates, evaluated in order, first failure
short-circuits.

    0. circuit breaker   — halt everything when rolling accuracy collapses
    1. macro blackout    — no signals during HIGH-impact event windows
    2. confidence        — probability must clear a direction-specific bar
    3. expected value    — rolling EV must be positive
    4. regime            — block in HIGH_VOL / MEAN_REVERTING
    5. MTF confluence    — H4/D1 trend must agree

Three properties get the most attention, because each one is a way the filter
could quietly stop filtering:

* **Order is load-bearing.** The circuit breaker runs first precisely so that a
  model in collapse cannot have its signals evaluated on their individual
  merits. A reordering that let a confident signal through during a breaker
  trip would look harmless in a diff.
* **HOLD is never forwarded.** A missing or empty direction must not fall
  through to a directional gate and get treated as a trade.
* **Every gate names itself.** `FilterResult.gate` is what an operator reads to
  learn *why* nothing is trading. A blocked result with an empty `gate` is
  indistinguishable from a bug.

`FilterResult.__bool__` returns `.passed`, so `if not filter.check(...)` is the
intended call shape — that truthiness is asserted rather than assumed, because
a caller writing `if result:` depends on it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import ml.signal_filter as sf
from ml.signal_filter import FilterResult, SignalFilter, get_signal_filter

pytestmark = pytest.mark.unit


@pytest.fixture
def filt(monkeypatch):
    """A filter with the optional/external gates neutralised.

    Blackout and MTF reach out to the orchestrator; the regime gate needs
    OHLCV. Each is exercised deliberately in its own class below.
    """
    monkeypatch.setattr(sf, "_BLACKOUT_GATE", False)
    monkeypatch.setattr(sf, "_MTF_CONFLUENCE", False)
    monkeypatch.setattr(sf, "_REGIME_FILTER", False)
    instance = SignalFilter()
    monkeypatch.setattr(instance, "_get_current_regime", lambda ohlcv: "TRENDING")
    return instance


def _signal(direction="BUY", confidence=0.90, symbol="XAU_USD"):
    return {"direction": direction, "confidence": confidence, "symbol": symbol}


def _losses(filt, symbol="XAU_USD", n=None, win_rate=0.0):
    n = n or sf._CB_MIN_OUTCOMES
    wins = int(n * win_rate)
    for i in range(n):
        filt.record_outcome(symbol, pnl_pct=1.0 if i < wins else -1.0, direction=1, confidence=0.8)


# ── the result record ─────────────────────────────────────────────────────────


class TestFilterResult:
    def test_a_passing_result_is_truthy(self):
        """Callers write `if not filter.check(...)`; this is that contract."""
        assert bool(FilterResult(passed=True)) is True

    def test_a_blocked_result_is_falsy(self):
        assert bool(FilterResult(passed=False)) is False

    def test_a_fresh_result_names_no_gate(self):
        assert FilterResult(passed=True).gate == ""

    def test_the_defaults_are_neutral(self):
        result = FilterResult(passed=True)

        assert result.confidence == 0.0
        assert result.regime == "unknown"
        assert result.mtf_aligned is None


# ── confidence ────────────────────────────────────────────────────────────────


class TestConfidenceGate:
    @pytest.mark.parametrize("direction", ["HOLD", "NEUTRAL", "", "hold", "neutral"])
    def test_a_non_directional_signal_is_never_forwarded(self, filt, direction):
        result = filt.check(_signal(direction=direction, confidence=0.99))

        assert result.passed is False
        assert result.gate == "confidence"

    def test_a_confident_long_passes(self, filt):
        assert filt.check(_signal("BUY", 0.95)).passed is True

    def test_a_decisive_short_is_blocked_S81(self):
        """S-81: the SELL path is inverted. Documented, not endorsed.

        `confidence` here is the raw ML P(up) -- core/signal_engine.py passes
        `signal_payload["probability"]` straight in. So P(up)=0.05 is a
        *maximum-conviction short*. It is blocked, by the absolute floor
        `_MIN_CONFIDENCE_ABS = 0.55` applied to raw P(up) rather than to
        `1 - P(up)`.
        """
        result = SignalFilter()._gate_confidence("SELL", 0.05, regime="TRENDING")

        assert result.passed is False
        assert "floor" in result.reason

    def test_a_bullish_probability_forwards_a_short_S81(self):
        """The other half of S-81, and the dangerous half.

        `_THRESHOLD_SHORT = 0.42` is plainly the lower edge of a two-sided band
        (`_THRESHOLD_LONG = 0.58`, symmetric about 0.5). The SELL branch blocks
        when `confidence < threshold_short`, which is backwards: it rejects
        exactly the shorts that should pass and admits the ones that should
        not. At P(up)=0.95 the model expects the market to *rise*, and the
        SELL is forwarded to execution.
        """
        result = SignalFilter()._gate_confidence("SELL", 0.95, regime="TRENDING")

        assert result.passed is True

    def test_the_short_band_is_inverted_across_its_whole_range_S81(self):
        """Measured, so the shape of the defect is unambiguous in the record."""
        instance = SignalFilter()
        passing = [
            c
            for c in (0.02, 0.05, 0.15, 0.30, 0.41, 0.45, 0.50, 0.55, 0.60, 0.75, 0.95)
            if instance._gate_confidence("SELL", c, regime="TRENDING").passed
        ]

        # A correct two-sided band would pass the LOW probabilities.
        assert min(passing) >= 0.55
        assert 0.05 not in passing

    def test_a_weak_long_is_blocked(self, filt):
        result = filt.check(_signal("BUY", 0.51))

        assert result.passed is False
        assert result.gate == "confidence"

    def test_a_signal_below_the_absolute_floor_is_blocked(self, filt, monkeypatch):
        monkeypatch.setattr(sf, "_MIN_CONFIDENCE_ABS", 0.55)

        assert filt.check(_signal("BUY", 0.50)).passed is False

    def test_a_mean_reverting_regime_tightens_the_bar(self, filt, monkeypatch):
        """Directional accuracy is historically lower there; demand more."""
        borderline = sf._THRESHOLD_LONG + 0.02

        monkeypatch.setattr(filt, "_get_current_regime", lambda ohlcv: "TRENDING")
        assert filt.check(_signal("BUY", borderline)).passed is True

        monkeypatch.setattr(filt, "_get_current_regime", lambda ohlcv: "MEAN_REVERTING")
        assert filt.check(_signal("BUY", borderline)).passed is False

    def test_a_high_vol_regime_also_tightens(self, filt, monkeypatch):
        borderline = sf._THRESHOLD_LONG + 0.01

        monkeypatch.setattr(filt, "_get_current_regime", lambda ohlcv: "HIGH_VOL")

        assert filt.check(_signal("BUY", borderline)).passed is False

    def test_the_reported_regime_is_the_one_used(self, filt, monkeypatch):
        monkeypatch.setattr(filt, "_get_current_regime", lambda ohlcv: "TRENDING")

        assert filt.check(_signal("BUY", 0.95)).regime == "TRENDING"

    def test_the_confidence_is_echoed_back(self, filt):
        assert filt.check(_signal("BUY", 0.93)).confidence == pytest.approx(0.93)


class TestConfidenceExtraction:
    def test_the_confidence_key_is_read(self, filt):
        assert filt._extract_confidence({"confidence": 0.7}) == pytest.approx(0.7)

    def test_probability_is_accepted_as_an_alias(self, filt):
        """Different producers in this codebase use different key names."""
        assert filt._extract_confidence({"probability": 0.7}) == pytest.approx(0.7)

    def test_a_signal_with_neither_is_neutral(self, filt):
        assert filt._extract_confidence({}) == pytest.approx(0.5)

    def test_a_non_numeric_confidence_raises_rather_than_degrading(self, filt):
        """Documented as-is: `float("high")` is uncaught, so a malformed
        payload propagates out of `check()` rather than degrading to neutral.
        `None` and a missing key both fall back to 0.5; only a non-numeric
        string raises."""
        with pytest.raises(ValueError):
            filt._extract_confidence({"confidence": "high"})

    def test_a_null_confidence_falls_back_to_neutral(self, filt):
        assert filt._extract_confidence({"confidence": None}) == pytest.approx(0.5)

    def test_a_percentage_is_normalised(self, filt):
        assert filt._extract_confidence({"probability": 85}) == pytest.approx(0.85)


# ── the circuit breaker ───────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_it_stays_open_before_enough_evidence(self, filt):
        """One bad streak is not a collapse; it needs CB_MIN_OUTCOMES.

        The EV gate blocks on the same losing history, so this asserts on
        *which* gate fired rather than on `.passed`.
        """
        _losses(filt, n=sf._CB_MIN_OUTCOMES - 1)

        assert filt.check(_signal("BUY", 0.95)).gate != "circuit_breaker"

    def test_a_collapsed_win_rate_trips_it(self, filt):
        _losses(filt)

        result = filt.check(_signal("BUY", 0.95))

        assert result.passed is False
        assert result.gate == "circuit_breaker"

    def test_a_healthy_win_rate_does_not_trip_it(self, filt):
        _losses(filt, win_rate=0.9)

        assert filt.check(_signal("BUY", 0.95)).passed is True

    def test_it_runs_before_the_confidence_gate(self, filt):
        """Order is the point: a tripped breaker outranks any conviction."""
        _losses(filt)

        result = filt.check(_signal("BUY", 0.99))

        assert result.gate == "circuit_breaker"

    def test_it_resets_when_accuracy_recovers(self, filt):
        _losses(filt)
        assert filt.check(_signal("BUY", 0.95)).passed is False

        _losses(filt, win_rate=1.0)

        assert filt.check(_signal("BUY", 0.95)).passed is True

    def test_a_trip_is_counted(self, filt):
        _losses(filt)
        filt.check(_signal("BUY", 0.95))

        assert filt._cb_trip_count >= 1

    def test_one_symbol_s_collapse_does_not_trip_another_s_breaker(self, filt):
        """The breaker reads per-symbol outcomes, deliberately."""
        _losses(filt, symbol="XAU_USD")

        assert filt.check(_signal("BUY", 0.95, symbol="XAU_USD")).gate == "circuit_breaker"
        assert filt.check(_signal("BUY", 0.95, symbol="EUR_USD")).gate != "circuit_breaker"

    def test_but_the_ev_gate_does_fall_back_to_global_history(self, filt):
        """An asymmetry worth knowing about.

        `_gate_circuit_breaker` uses only `self._outcomes[symbol]` and says so:
        "to avoid cross-symbol contamination". `_gate_expected_value` instead
        does `self._outcomes.get(symbol, []) or self._global_outcomes`, so a
        symbol with no history of its own inherits every other symbol's. That
        is defensible as a prior, but it is the opposite choice, made two
        methods apart.
        """
        _losses(filt, symbol="XAU_USD")

        assert filt.check(_signal("BUY", 0.95, symbol="EUR_USD")).gate == "expected_value"

    def test_the_reason_states_the_measured_rate(self, filt):
        _losses(filt)

        reason = filt.check(_signal("BUY", 0.95)).reason

        assert "win_rate" in reason
        assert "threshold" in reason

    def test_it_can_be_disabled(self, filt, monkeypatch):
        _losses(filt)
        monkeypatch.setattr(sf, "_CIRCUIT_BREAKER", False)

        assert filt.check(_signal("BUY", 0.95)).gate != "circuit_breaker"


# ── outcomes and expected value ───────────────────────────────────────────────


class TestRecordOutcome:
    def test_the_first_outcome_creates_the_window(self, filt):
        filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert len(filt._outcomes["XAU_USD"]) == 1

    def test_the_window_is_bounded(self, filt):
        for _ in range(sf._EV_WINDOW * 3):
            filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert len(filt._outcomes["XAU_USD"]) == sf._EV_WINDOW

    def test_outcomes_also_land_in_the_global_window(self, filt):
        filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert len(filt._global_outcomes) >= 1


class TestEvStats:
    def test_no_history_reports_none_rather_than_zero(self, filt):
        """0.0 EV means 'breakeven'. None means 'no data'."""
        stats = filt.ev_stats("NEVER_TRADED")

        assert stats["n"] == 0
        assert stats["ev"] is None
        assert stats["win_rate"] is None

    def test_an_all_winning_history_has_positive_ev(self, filt):
        for _ in range(20):
            filt.record_outcome("XAU_USD", pnl_pct=2.0, direction=1, confidence=0.8)

        assert filt.ev_stats("XAU_USD")["ev"] > 0

    def test_an_all_losing_history_has_negative_ev(self, filt):
        for _ in range(20):
            filt.record_outcome("XAU_USD", pnl_pct=-2.0, direction=1, confidence=0.8)

        assert filt.ev_stats("XAU_USD")["ev"] < 0

    def test_the_win_rate_is_the_share_of_positive_trades(self, filt):
        for i in range(10):
            filt.record_outcome("XAU_USD", pnl_pct=1.0 if i < 7 else -1.0, direction=1, confidence=0.8)

        assert filt.ev_stats("XAU_USD")["win_rate"] == pytest.approx(0.7)

    def test_a_breakeven_trade_counts_as_a_loss(self, filt):
        """`p > 0` is the win test, so exactly zero is not a win."""
        for _ in range(10):
            filt.record_outcome("XAU_USD", pnl_pct=0.0, direction=1, confidence=0.8)

        assert filt.ev_stats("XAU_USD")["win_rate"] == 0.0

    def test_it_reports_the_configured_threshold(self, filt):
        filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert filt.ev_stats("XAU_USD")["threshold"] == sf._EV_MIN

    def test_it_is_json_serialisable(self, filt):
        import json

        filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        json.dumps(filt.ev_stats("XAU_USD"))

    def test_an_unknown_symbol_falls_back_to_global_history(self, filt):
        filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert filt.ev_stats("SOMETHING_ELSE")["n"] >= 1


class TestExpectedValueGate:
    def test_a_thin_history_does_not_block(self, filt):
        """EV on three trades is noise; the gate waits for evidence."""
        for _ in range(3):
            filt.record_outcome("XAU_USD", pnl_pct=-5.0, direction=1, confidence=0.8)

        assert filt.check(_signal("BUY", 0.95)).passed is True

    def test_a_profitable_history_passes(self, filt):
        for _ in range(20):
            filt.record_outcome("XAU_USD", pnl_pct=2.0, direction=1, confidence=0.8)

        assert filt.check(_signal("BUY", 0.95)).passed is True


# ── the regime gate ───────────────────────────────────────────────────────────


def _ohlcv(n=120, seed=0, trend=0.0):
    rng = np.random.default_rng(seed)
    closes = 2000 + np.cumsum(rng.normal(trend, 3, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 4,
            "low": closes - 4,
            "close": closes,
            "volume": rng.integers(100, 900, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


class TestRegimeGate:
    def test_it_is_skipped_without_ohlcv(self, filt, monkeypatch):
        monkeypatch.setattr(sf, "_REGIME_FILTER", True)

        assert filt.check(_signal("BUY", 0.95), ohlcv=None).passed is True

    def test_it_runs_when_ohlcv_is_supplied(self, filt, monkeypatch):
        monkeypatch.setattr(sf, "_REGIME_FILTER", True)

        result = filt.check(_signal("BUY", 0.95), ohlcv=_ohlcv())

        assert isinstance(result.passed, bool)

    def test_a_blocked_regime_names_itself(self, filt, monkeypatch):
        monkeypatch.setattr(sf, "_REGIME_FILTER", True)
        monkeypatch.setattr(
            filt,
            "_gate_regime",
            lambda ohlcv, direction, confidence: FilterResult(
                passed=False, gate="regime", reason="blocked", confidence=confidence
            ),
        )

        assert filt.check(_signal("BUY", 0.95), ohlcv=_ohlcv()).gate == "regime"

    def test_a_parabolic_market_is_detected(self, filt):
        n = 250
        closes = [100.0] * (n - 20) + list(np.linspace(100, 240, 20))
        frame = pd.DataFrame({"close": closes}, index=pd.date_range("2024-01-01", periods=n, freq="h"))

        assert sf._is_parabolic(frame) is True

    def test_a_calm_market_is_not_parabolic(self, filt):
        assert sf._is_parabolic(_ohlcv(250)) is False

    def test_a_frame_without_close_is_not_parabolic(self, filt):
        assert sf._is_parabolic(pd.DataFrame({"open": [1.0] * 100})) is False


class TestHurstExponent:
    def test_it_returns_a_unit_interval_value(self, filt):
        rng = np.random.default_rng(0)

        assert 0.0 <= filt._hurst_exponent(rng.normal(0, 1, 200)) <= 1.0

    def test_a_short_series_falls_back_to_a_random_walk(self, filt):
        """0.5 is 'no information', the honest answer on too little data."""
        assert filt._hurst_exponent(np.array([1.0, 2.0, 3.0])) == pytest.approx(0.5)

    def test_a_constant_series_does_not_divide_by_zero(self, filt):
        import math

        assert math.isfinite(filt._hurst_exponent(np.full(200, 5.0)))

    def test_a_trending_series_scores_above_noise(self, filt):
        rng = np.random.default_rng(0)
        trend = np.cumsum(np.full(300, 1.0) + rng.normal(0, 0.1, 300))
        noise = rng.normal(0, 1, 300)

        assert filt._hurst_exponent(trend) > filt._hurst_exponent(noise)


# ── the blackout gate ─────────────────────────────────────────────────────────


class TestBlackoutGate:
    def test_a_blackout_window_blocks(self, monkeypatch):
        monkeypatch.setattr(sf, "_BLACKOUT_GATE", True)
        monkeypatch.setattr(sf, "_MTF_CONFLUENCE", False)
        monkeypatch.setattr(sf, "_REGIME_FILTER", False)
        from data_layer.orchestrator import orchestrator

        monkeypatch.setattr(orchestrator, "is_blackout_window", lambda: True, raising=False)

        result = SignalFilter().check(_signal("BUY", 0.95))

        assert result.passed is False
        assert result.gate == "blackout"

    def test_outside_a_blackout_it_passes(self, monkeypatch):
        monkeypatch.setattr(sf, "_BLACKOUT_GATE", True)
        monkeypatch.setattr(sf, "_MTF_CONFLUENCE", False)
        monkeypatch.setattr(sf, "_REGIME_FILTER", False)
        from data_layer.orchestrator import orchestrator

        monkeypatch.setattr(orchestrator, "is_blackout_window", lambda: False, raising=False)
        instance = SignalFilter()
        monkeypatch.setattr(instance, "_get_current_regime", lambda ohlcv: "TRENDING")

        assert instance.check(_signal("BUY", 0.95)).passed is True

    def test_an_unavailable_orchestrator_does_not_block(self, monkeypatch):
        """Blackout is an enhancement; losing it must not halt all trading."""
        monkeypatch.setattr(sf, "_BLACKOUT_GATE", True)
        monkeypatch.setattr(sf, "_MTF_CONFLUENCE", False)
        monkeypatch.setattr(sf, "_REGIME_FILTER", False)
        from data_layer.orchestrator import orchestrator

        def _boom():
            raise RuntimeError("orchestrator down")

        monkeypatch.setattr(orchestrator, "is_blackout_window", _boom, raising=False)
        instance = SignalFilter()
        monkeypatch.setattr(instance, "_get_current_regime", lambda ohlcv: "TRENDING")

        assert instance.check(_signal("BUY", 0.95)).passed is True


# ── aggregate reporting ───────────────────────────────────────────────────────


class TestStats:
    def test_stats_are_json_serialisable(self, filt):
        import json

        json.dumps(filt.get_stats())

    def test_stats_report_the_gate_configuration(self, filt):
        rendered = str(filt.get_stats())

        assert "threshold" in rendered or "enabled" in rendered

    def test_stats_reflect_recorded_outcomes(self, filt):
        for _ in range(5):
            filt.record_outcome("XAU_USD", pnl_pct=1.0, direction=1, confidence=0.8)

        assert "XAU_USD" in str(filt.get_stats())

    def test_stats_report_circuit_breaker_state(self, filt):
        _losses(filt)
        filt.check(_signal("BUY", 0.95))

        assert "trip" in str(filt.get_stats()).lower() or "circuit" in str(filt.get_stats()).lower()


class TestPublicSurface:
    def test_filter_is_an_alias_for_check(self, filt):
        signal = _signal("BUY", 0.95)

        assert filt.filter(signal).passed == filt.check(signal).passed

    def test_the_singleton_is_shared(self):
        assert get_signal_filter() is get_signal_filter()

    def test_a_passing_result_reports_its_expected_value(self, filt):
        result = filt.check(_signal("BUY", 0.95))

        assert result.passed is True
        assert isinstance(result.expected_value, float)

    def test_a_signal_without_a_symbol_is_still_evaluated(self, filt):
        result = filt.check({"direction": "BUY", "confidence": 0.95})

        assert isinstance(result.passed, bool)

    def test_every_blocked_result_names_the_gate_that_blocked_it(self, filt):
        """An empty `gate` on a block is indistinguishable from a bug."""
        blocked = [
            filt.check(_signal("HOLD", 0.99)),
            filt.check(_signal("BUY", 0.10)),
        ]

        for result in blocked:
            assert result.passed is False
            assert result.gate != ""
            assert result.reason != ""
