# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_realtime_heatmap.py
===================================
`core/analytics/realtime_heatmap.py` — 74 statements, previously 0% covered.

The engine that decides which market regime the platform thinks it is in. It
writes that verdict straight onto `orchestra.current_regime`, and the strategy
orchestra routes on it — so a misclassification here silently changes which
strategies are allowed to trade.

Worth pinning specifically:

- The classifier's thresholds. `volatility > 0.001` and `abs(trend) > 0.0005`
  and `adx > 25` are bare literals with no named constants; a change to any of
  them is invisible in review without a test that fixes the boundaries.
- The correlation matrix's several early returns, each yielding a differently
  shaped identity matrix. A caller indexing by symbol position gets a silently
  wrong answer if the shape is off.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import numpy as np
import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc


class _Orchestra:
    def __init__(self):
        self.current_regime = None
        self.heatmap = {"strategy_a": 1.0}

    def get_heatmap_data(self):
        return self.heatmap


class _Risk:
    class _Snapshot:
        var_95 = -1200.0
        cvar_95 = -1800.0
        volatility = 0.014
        max_drawdown = -0.08

    def __init__(self, has_risk=True):
        self.current_risk = self._Snapshot() if has_risk else None


def _engine(has_risk=True):
    from core.analytics.realtime_heatmap import RealtimeHeatmapEngine

    return RealtimeHeatmapEngine(_Orchestra(), _Risk(has_risk), event_bus=object())


def _trend(n, drift, noise, start=100.0, seed=7):
    """A trending series with realistic per-bar noise.

    A *perfectly* geometric series has zero return variance, which the
    classifier reads as "ranging" — see the test below. Live prices are never
    that clean, so anything asserting a trend has to carry noise.
    """
    rng = np.random.default_rng(seed)
    prices, p = [], start
    for _ in range(n):
        p *= 1 + drift + rng.normal(0.0, noise)
        prices.append(p)
    return prices


def _feed(engine, symbol, prices, start=None):
    ts = start or datetime.now(UTC)
    for p in prices:
        engine.on_price(symbol, p, ts)


# ── Price ingestion ───────────────────────────────────────────────────────────


def test_the_first_price_creates_the_buffers_and_yields_no_return():
    """A single price has nothing to compare against."""
    e = _engine()

    e.on_price("XAUUSD", 4000.0, datetime.now(UTC))

    assert list(e.price_history["XAUUSD"]) == [(pytest.approx, 4000.0)][0:0] or len(e.price_history["XAUUSD"]) == 1
    assert len(e.returns_history["XAUUSD"]) == 0


def test_the_second_price_produces_one_return():
    e = _engine()
    ts = datetime.now(UTC)

    e.on_price("XAUUSD", 100.0, ts)
    e.on_price("XAUUSD", 101.0, ts)

    assert len(e.returns_history["XAUUSD"]) == 1
    assert e.returns_history["XAUUSD"][0] == pytest.approx(0.01)


def test_a_falling_price_produces_a_negative_return():
    e = _engine()
    ts = datetime.now(UTC)

    e.on_price("XAUUSD", 100.0, ts)
    e.on_price("XAUUSD", 99.0, ts)

    assert e.returns_history["XAUUSD"][0] == pytest.approx(-0.01)


def test_separate_symbols_keep_separate_buffers():
    """The gold-price bug's shape: one symbol's data must never answer for another."""
    e = _engine()
    ts = datetime.now(UTC)

    e.on_price("XAUUSD", 4000.0, ts)
    e.on_price("XAUUSD", 4010.0, ts)
    e.on_price("EURUSD", 1.05, ts)

    assert len(e.returns_history["XAUUSD"]) == 1
    assert len(e.returns_history["EURUSD"]) == 0


def test_the_price_buffer_is_bounded():
    """Ten thousand ticks is minutes of live data — this must not grow forever."""
    e = _engine()

    assert e.price_history == {}
    e.on_price("XAUUSD", 1.0, datetime.now(UTC))

    assert e.price_history["XAUUSD"].maxlen == 10_000
    assert e.returns_history["XAUUSD"].maxlen == 10_000


# ── Regime detection ──────────────────────────────────────────────────────────


def test_no_regime_is_declared_before_fifty_bars():
    """Classifying on a handful of ticks would be noise, not a regime."""
    e = _engine()
    _feed(e, "XAUUSD", [100.0 + i * 0.01 for i in range(49)])

    assert e.orchestra.current_regime is None
    assert len(e.regime_history) == 0


def test_a_flat_series_is_classified_as_ranging():
    e = _engine()
    _feed(e, "XAUUSD", [100.0 + (i % 2) * 0.0001 for i in range(60)])

    assert e.orchestra.current_regime == "ranging"


def test_a_frictionless_trend_reads_as_ranging_because_its_variance_is_zero():
    """A real property of the classifier, pinned rather than papered over.

    `volatility` is `np.std(returns)`. A perfectly geometric series has an
    identical return on every bar, so its standard deviation is exactly zero
    and the `volatility > 0.001` branch is never taken — the strongest possible
    trend is classified as "ranging". Real prices always carry noise, so this
    is not reachable from live data, but it means the volatility gate is doing
    the classification before direction is ever consulted.
    """
    e = _engine()
    _feed(e, "XAUUSD", [100.0 * (1.002**i) for i in range(60)])

    assert e.orchestra.current_regime == "ranging"


def test_a_noisy_climb_is_classified_as_trending_up():
    e = _engine()
    _feed(e, "XAUUSD", _trend(60, drift=0.004, noise=0.003))

    assert e.orchestra.current_regime == "trending_up"


def test_a_noisy_fall_is_classified_as_trending_down():
    e = _engine()
    _feed(e, "XAUUSD", _trend(60, drift=-0.004, noise=0.003))

    assert e.orchestra.current_regime == "trending_down"


def test_a_directionless_but_noisy_series_is_classified_as_volatile():
    """High volatility with no net drift is not a trend — it must not read as one."""
    e = _engine()
    prices = [100.0 * (1 + (0.02 if i % 2 else -0.02)) for i in range(60)]
    _feed(e, "XAUUSD", prices)

    assert e.orchestra.current_regime == "volatile"


def test_a_regime_change_is_recorded_once_not_on_every_tick():
    """The history is a timeline of transitions, not a per-tick log."""
    e = _engine()
    _feed(e, "XAUUSD", _trend(80, drift=0.004, noise=0.003))

    assert e.orchestra.current_regime == "trending_up"
    transitions = [reg for _, reg in e.regime_history]
    assert transitions.count("trending_up") == 1, f"regime re-recorded on every tick: {transitions}"


def test_the_regime_history_is_bounded():
    e = _engine()

    assert e.regime_history.maxlen == 1000


# ── ADX ───────────────────────────────────────────────────────────────────────


def test_adx_is_zero_when_there_is_not_enough_history():
    e = _engine()

    assert e._calculate_adx([1.0, 2.0, 3.0]) == 0


def test_adx_is_high_for_a_clean_directional_move():
    """A monotone series has all directional movement on one side."""
    e = _engine()

    adx = e._calculate_adx([100.0 + i for i in range(40)])

    assert adx > 25


def test_adx_is_finite_for_a_perfectly_flat_series():
    """Zero ATR divides by zero unless guarded — this is the guard."""
    e = _engine()

    adx = e._calculate_adx([100.0] * 40)

    assert adx == 0
    assert np.isfinite(adx)


# ── Correlation matrix ────────────────────────────────────────────────────────


def test_a_single_symbol_yields_a_1x1_identity():
    e = _engine()

    assert e.get_correlation_matrix(["XAUUSD"]).shape == (1, 1)


def test_symbols_with_no_history_yield_an_identity_of_the_requested_size():
    """The shape must match the symbol list, or a positional caller misreads it."""
    e = _engine()

    m = e.get_correlation_matrix(["XAUUSD", "EURUSD", "GBPUSD"])

    assert m.shape == (3, 3)
    assert np.allclose(m, np.eye(3))


def test_two_symbols_moving_together_correlate_positively():
    e = _engine()
    ts = datetime.now(UTC)
    for i in range(30):
        e.on_price("A", 100.0 + i, ts)
        e.on_price("B", 200.0 + 2 * i, ts)

    m = e.get_correlation_matrix(["A", "B"])

    assert m.shape == (2, 2)
    assert m[0][1] == pytest.approx(1.0, abs=0.05)


def test_two_symbols_moving_oppositely_correlate_negatively():
    e = _engine()
    ts = datetime.now(UTC)
    up = _trend(30, drift=0.004, noise=0.004)
    for price in up:
        e.on_price("A", price, ts)
        # Mirror image: B's return is the negative of A's on every bar.
        e.on_price("B", 200.0 - (price - 100.0), ts)

    m = e.get_correlation_matrix(["A", "B"])

    assert m[0][1] < -0.9


def test_series_of_different_lengths_are_truncated_to_the_shortest():
    """Otherwise np.corrcoef raises on a ragged matrix."""
    e = _engine()
    ts = datetime.now(UTC)
    for i in range(40):
        e.on_price("A", 100.0 + i, ts)
    for i in range(15):
        e.on_price("B", 50.0 + i, ts)

    m = e.get_correlation_matrix(["A", "B"])

    assert m.shape == (2, 2)
    assert np.all(np.isfinite(m))


# ── Heatmap payload ───────────────────────────────────────────────────────────


def test_the_heatmap_payload_carries_every_section():
    e = _engine()
    _feed(e, "XAUUSD", [100.0 * (1.002**i) for i in range(60)])

    data = e.get_heatmap_data()

    assert set(data) == {"strategies", "correlation", "risk", "regime_timeline", "timestamp"}
    assert data["strategies"] == {"strategy_a": 1.0}
    assert data["correlation"]["symbols"] == ["XAUUSD"]
    assert isinstance(data["correlation"]["matrix"], list), "the matrix must be JSON-serialisable"


def test_the_risk_section_is_populated_from_the_current_snapshot():
    e = _engine(has_risk=True)

    risk = e.get_heatmap_data()["risk"]

    assert risk == {"var_95": -1200.0, "cvar_95": -1800.0, "volatility": 0.014, "max_dd": -0.08}


def test_the_risk_section_is_empty_when_no_snapshot_exists_yet():
    """Startup, before the first risk calculation — must not raise."""
    e = _engine(has_risk=False)

    assert e.get_heatmap_data()["risk"] == {}


def test_the_regime_timeline_is_serialisable():
    e = _engine()
    _feed(e, "XAUUSD", [100.0 * (1.002**i) for i in range(60)])

    timeline = e.get_heatmap_data()["regime_timeline"]

    assert timeline, "a detected regime never reached the timeline"
    assert all(isinstance(entry["time"], str) for entry in timeline)
    assert all(entry["regime"] in {"trending_up", "trending_down", "volatile", "ranging"} for entry in timeline)


def test_the_payload_is_produced_with_no_data_at_all():
    """The dashboard polls this from startup — it must not raise on an empty engine."""
    e = _engine(has_risk=False)

    data = e.get_heatmap_data()

    assert data["correlation"]["symbols"] == []
    assert data["regime_timeline"] == []


def test_the_engine_starts_with_empty_buffers_and_configured_windows():
    e = _engine()

    assert e.price_history == {} and e.returns_history == {}
    assert isinstance(e.regime_history, deque)
    assert e.lookback_windows == {"1m": 12, "5m": 60, "1h": 720, "1d": 8640}
