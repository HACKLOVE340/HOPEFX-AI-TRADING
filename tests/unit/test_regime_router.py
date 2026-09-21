# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_regime_router.py
=================================
Which strategy runs, and why — the module that decides it, at 0%.

Coverage-floor programme, Task 6c. `strategies/regime_router.py` was recorded at
**0%** and is live three ways: `core/startup_factories.py:2343` constructs a
`RegimeRouter` at startup, `scripts/retrain_model.py:218` calls `detect_regime`
and `update_regime_performance` after every retrain, and `core/regime_router.py`
is a shim that re-exports the class. The shim was measured at 73.77%; the module
it points at was measured at nothing.

**Both sweeps come back clean, and that is the finding here.** The
`backtesting-frameworks` sweep: no `center=True`, no negative `.shift()`, no
`bfill`; `_ema` is a forward recursion, `_atr` and `_adx_approx` read trailing
windows, and `detect_regime` slices `[-lookback:]` to classify *the present*
rather than to compare a bar against a window containing itself — which is the
distinction that made F275 a defect and leaves this correct. The
`hopefx-dead-controls` sweep: `_DEFAULT_REGIME_STRATEGY` names
`"TrendFollowing"`, `"MeanReversion"` and `"Breakout"`, and those are exactly the
names `strategies/manager.py` registers (lines 225, 301, 381, keyed by
`strategy.name` at 486) — so the regime→strategy mapping resolves rather than
silently falling through to "first available", which is what a name mismatch
here would have produced. Asserted below rather than left as a reading.

So these tests are coverage of correct code, plus two properties worth pinning:
every regime label the detector can return is routable, and the manifest
survives a round trip through disk.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import strategies.regime_router as rr


@pytest.fixture(autouse=True)
def _manifest_in_tmp(tmp_path, monkeypatch):
    """The manifest path is a module global read from ``REGIME_MANIFEST`` at
    import. Every test gets its own file; none touches
    ``ml/saved_models/regime_manifest.json``."""
    monkeypatch.setattr(rr, "_MANIFEST_PATH", tmp_path / "regime_manifest.json")
    return tmp_path / "regime_manifest.json"


def _ohlc(closes: list[float], *, spread: float = 1.0) -> pd.DataFrame:
    highs = [c + spread for c in closes]
    lows = [c - spread for c in closes]
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * len(closes),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# detect_regime
# ─────────────────────────────────────────────────────────────────────────────


class TestTheDetectorRefusesBeforeItGuesses:
    def test_too_little_history_is_unknown_with_zero_confidence(self):
        regime, confidence = rr.detect_regime(_ohlc([2000.0] * 10))
        assert regime == rr.REGIME_UNKNOWN
        assert confidence == 0.0

    def test_exactly_the_lookback_is_enough(self):
        """The boundary is ``len(df) < lookback``, so 50 bars must classify.

        Stated as "not the refusal it gives at 49 bars with 0.0 confidence",
        which is the thing the off-by-one would change.
        """
        at_the_boundary = rr.detect_regime(_ohlc(list(np.linspace(1900.0, 2100.0, 50))))
        one_short = rr.detect_regime(_ohlc(list(np.linspace(1900.0, 2100.0, 49))))
        assert one_short == (rr.REGIME_UNKNOWN, 0.0)
        assert at_the_boundary != (rr.REGIME_UNKNOWN, 0.0)
        assert at_the_boundary[0] in rr.ALL_REGIMES

    def test_a_shorter_lookback_can_be_asked_for(self):
        regime, _ = rr.detect_regime(_ohlc([2000.0] * 30), lookback=20)
        assert regime in rr.ALL_REGIMES


class TestTheRegimesItCanName:
    def test_a_strong_rally_is_trending_up(self):
        regime, confidence = rr.detect_regime(_ohlc(list(np.linspace(1900.0, 2400.0, 60)), spread=0.5))
        assert regime == rr.REGIME_TRENDING_UP
        assert 0.0 < confidence <= 1.0

    def test_a_strong_slide_is_trending_down(self):
        regime, confidence = rr.detect_regime(_ohlc(list(np.linspace(2400.0, 1900.0, 60)), spread=0.5))
        assert regime == rr.REGIME_TRENDING_DOWN
        assert 0.0 < confidence <= 1.0

    def test_a_dead_flat_series_is_low_vol(self):
        """No returns at all, so ``vol_pct`` is 0 and falls under the 0.6 floor."""
        regime, confidence = rr.detect_regime(_ohlc([2000.0] * 60))
        assert regime == rr.REGIME_LOW_VOL
        assert confidence == pytest.approx(0.7)

    def test_a_late_volatility_burst_is_high_vol(self):
        """Recent 14-bar volatility more than 1.5x the whole window's."""
        rng = np.random.default_rng(3)
        quiet = list(2000.0 + rng.normal(0, 0.2, 46))
        burst = list(2000.0 + rng.normal(0, 20.0, 14))
        regime, confidence = rr.detect_regime(_ohlc(quiet + burst))
        assert regime == rr.REGIME_HIGH_VOL
        assert 0.0 < confidence <= 1.0

    def test_the_confidence_of_a_trend_is_capped_at_one(self):
        """``min(adx / 50, 1.0)`` — a violent trend must not report 1.4."""
        closes = list(np.linspace(1000.0, 5000.0, 60))
        _regime, confidence = rr.detect_regime(_ohlc(closes, spread=0.1))
        assert confidence <= 1.0

    def test_every_label_it_can_return_is_in_all_regimes(self):
        """`ALL_REGIMES` is what the dashboard and the manifest enumerate, so a
        label the detector can produce and that list omits would be invisible."""
        rng = np.random.default_rng(11)
        seen = set()
        for scale in (0.05, 0.5, 5.0, 40.0):
            for drift in (-8.0, -0.5, 0.0, 0.5, 8.0):
                closes = 2000.0 + np.cumsum(rng.normal(drift, scale, 60))
                seen.add(rr.detect_regime(_ohlc(list(closes)))[0])
        assert seen, "the sweep produced no classification at all"
        assert seen <= set(rr.ALL_REGIMES), f"unlisted labels: {seen - set(rr.ALL_REGIMES)}"


class TestTheNumericHelpers:
    def test_the_ema_starts_at_the_first_value_rather_than_at_zero(self):
        values = np.array([100.0, 101.0, 102.0])
        assert rr._ema(values, 10)[0] == 100.0

    def test_the_ema_follows_a_step_without_overshooting_it(self):
        values = np.array([100.0] * 10 + [200.0] * 10)
        out = rr._ema(values, 5)
        assert 100.0 < out[-1] < 200.0
        assert out[-1] > out[-5], "it must be converging upward"

    def test_the_ema_of_a_constant_series_is_that_constant(self):
        assert rr._ema(np.array([50.0] * 20), 7)[-1] == pytest.approx(50.0)

    def test_the_atr_of_a_fixed_range_is_that_range(self):
        highs = np.array([101.0] * 20)
        lows = np.array([99.0] * 20)
        closes = np.array([100.0] * 20)
        assert rr._atr(highs, lows, closes, 14) == pytest.approx(2.0)

    def test_the_atr_falls_back_to_the_whole_series_when_short(self):
        highs = np.array([101.0, 102.0, 103.0])
        lows = np.array([99.0, 100.0, 101.0])
        closes = np.array([100.0, 101.0, 102.0])
        assert rr._atr(highs, lows, closes, 14) > 0

    def test_the_atr_of_a_single_bar_is_zero_rather_than_a_nan(self):
        """``np.mean([])`` is NaN and a warning; the guard returns 0.0.

        A NaN ATR propagates into ``rel_atr`` and makes the range-bound
        comparison false, so the detector would silently lose a branch.
        """
        one = np.array([100.0])
        assert rr._atr(one, one, one, 14) == 0.0

    def test_the_adx_is_zero_when_there_is_not_enough_history(self):
        short = np.array([100.0] * 5)
        assert rr._adx_approx(short, short, short, 14) == 0.0

    def test_the_adx_is_high_for_a_one_way_move_and_low_for_chop(self):
        trend_h = np.linspace(100.0, 200.0, 40)
        trend = rr._adx_approx(trend_h, trend_h - 1, trend_h - 0.5, 14)

        rng = np.random.default_rng(5)
        chop_c = 150.0 + rng.normal(0, 1, 40)
        chop = rr._adx_approx(chop_c + 1, chop_c - 1, chop_c, 14)

        assert trend > chop

    def test_the_adx_of_a_flat_series_does_not_divide_by_zero(self):
        flat = np.array([100.0] * 40)
        assert rr._adx_approx(flat, flat, flat, 14) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# The manifest
# ─────────────────────────────────────────────────────────────────────────────


class TestTheManifest:
    def test_a_missing_manifest_is_empty_rather_than_an_error(self):
        assert rr.load_regime_manifest() == {}

    def test_a_saved_manifest_comes_back(self, _manifest_in_tmp):
        rr.save_regime_manifest(
            {
                rr.REGIME_TRENDING_UP: [
                    rr.RegimePerformance(strategy_name="TrendFollowing", regime=rr.REGIME_TRENDING_UP, sharpe=1.8),
                ]
            }
        )
        assert _manifest_in_tmp.exists()
        loaded = rr.load_regime_manifest()
        assert loaded[rr.REGIME_TRENDING_UP][0].strategy_name == "TrendFollowing"
        assert loaded[rr.REGIME_TRENDING_UP][0].sharpe == pytest.approx(1.8)

    def test_saving_creates_the_directory_it_needs(self, tmp_path, monkeypatch):
        nested = tmp_path / "does" / "not" / "exist" / "manifest.json"
        monkeypatch.setattr(rr, "_MANIFEST_PATH", nested)
        rr.save_regime_manifest({})
        assert nested.exists()

    def test_entries_come_back_sorted_by_sharpe_descending(self, _manifest_in_tmp):
        _manifest_in_tmp.write_text(
            json.dumps(
                {
                    rr.REGIME_HIGH_VOL: [
                        {"strategy_name": "Weak", "regime": rr.REGIME_HIGH_VOL, "sharpe": 0.2},
                        {"strategy_name": "Strong", "regime": rr.REGIME_HIGH_VOL, "sharpe": 2.4},
                        {"strategy_name": "Middling", "regime": rr.REGIME_HIGH_VOL, "sharpe": 1.1},
                    ]
                }
            ),
            encoding="utf-8",
        )
        names = [p.strategy_name for p in rr.load_regime_manifest()[rr.REGIME_HIGH_VOL]]
        assert names == ["Strong", "Middling", "Weak"]

    def test_an_unreadable_manifest_is_empty_and_logged_at_warning(self, _manifest_in_tmp, caplog):
        """Not DEBUG. A router that lost its performance history and said
        nothing would route on defaults while the dashboard showed a manifest."""
        import logging

        _manifest_in_tmp.write_text("{ this is not json", encoding="utf-8")
        with caplog.at_level(logging.DEBUG, logger="strategies.regime_router"):
            assert rr.load_regime_manifest() == {}
        records = [r for r in caplog.records if "regime manifest" in r.getMessage().lower()]
        assert records
        assert all(r.levelno >= logging.WARNING for r in records)

    def test_a_manifest_entry_with_an_unknown_field_is_refused_rather_than_half_loaded(self, _manifest_in_tmp):
        """``RegimePerformance(**e)`` raises on an extra key, which the
        ``except`` turns into an empty manifest — all-or-nothing rather than a
        partial history that looks complete."""
        _manifest_in_tmp.write_text(
            json.dumps({rr.REGIME_LOW_VOL: [{"strategy_name": "X", "regime": rr.REGIME_LOW_VOL, "bogus": 1}]}),
            encoding="utf-8",
        )
        assert rr.load_regime_manifest() == {}

    def test_a_performance_record_stamps_itself(self):
        from datetime import datetime

        record = rr.RegimePerformance(strategy_name="X", regime=rr.REGIME_LOW_VOL)
        assert datetime.fromisoformat(record.updated_at).tzinfo is not None


class TestUpdatingPerformance:
    def test_a_new_strategy_is_inserted(self):
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.5, 0.6, 40, 2.1)
        entries = rr.load_regime_manifest()[rr.REGIME_HIGH_VOL]
        assert [e.strategy_name for e in entries] == ["Breakout"]
        assert entries[0].total_trades == 40

    def test_an_existing_strategy_is_replaced_rather_than_duplicated(self):
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.5, 0.6, 40, 2.1)
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 0.4, 0.5, 55, 0.9)
        entries = rr.load_regime_manifest()[rr.REGIME_HIGH_VOL]
        assert len(entries) == 1, "the retrain loop runs repeatedly; duplicates would accumulate forever"
        assert entries[0].sharpe == pytest.approx(0.4)
        assert entries[0].total_trades == 55

    def test_the_timestamp_moves_when_an_entry_is_replaced(self):
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.5, 0.6, 40, 2.1)
        first = rr.load_regime_manifest()[rr.REGIME_HIGH_VOL][0].updated_at
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.6, 0.6, 41, 2.2)
        assert rr.load_regime_manifest()[rr.REGIME_HIGH_VOL][0].updated_at >= first

    def test_the_best_sharpe_ends_up_first(self):
        rr.update_regime_performance("Weak", rr.REGIME_RANGE_BOUND, 0.1, 0.5, 20, 0.2)
        rr.update_regime_performance("Strong", rr.REGIME_RANGE_BOUND, 2.0, 0.7, 30, 3.0)
        entries = rr.load_regime_manifest()[rr.REGIME_RANGE_BOUND]
        assert [e.strategy_name for e in entries] == ["Strong", "Weak"]

    def test_regimes_do_not_bleed_into_each_other(self):
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.5, 0.6, 40, 2.1)
        rr.update_regime_performance("MeanReversion", rr.REGIME_LOW_VOL, 1.2, 0.6, 40, 1.1)
        manifest = rr.load_regime_manifest()
        assert [e.strategy_name for e in manifest[rr.REGIME_HIGH_VOL]] == ["Breakout"]
        assert [e.strategy_name for e in manifest[rr.REGIME_LOW_VOL]] == ["MeanReversion"]


# ─────────────────────────────────────────────────────────────────────────────
# RegimeRouter
# ─────────────────────────────────────────────────────────────────────────────


class _Manager:
    def __init__(self, *names: str) -> None:
        self.strategies = dict.fromkeys(names, object())


class TestTheDefaultMappingResolves:
    """`hopefx-dead-controls`: a mapping whose names nothing registers routes
    every regime to whatever `next(iter(...))` happens to yield.

    These assert the names line up against the real `StrategyManager` rather
    than against a fixture, because the fixture is what would hide it.
    """

    def test_the_names_the_mapping_uses_are_the_names_the_manager_registers(self):
        from strategies.manager import StrategyManager

        registered = set(StrategyManager(preload_defaults=True).strategies)
        mapped = set(rr._DEFAULT_REGIME_STRATEGY.values())
        assert mapped <= registered, f"regime mapping names nothing registers: {mapped - registered}"

    def test_every_regime_has_a_default(self):
        assert set(rr._DEFAULT_REGIME_STRATEGY) == set(rr.ALL_REGIMES)


class TestSelection:
    def test_the_default_mapping_is_used_when_the_manifest_is_empty(self):
        router = rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "Breakout"
        assert router._select_strategy(rr.REGIME_TRENDING_UP) == "TrendFollowing"
        assert router._select_strategy(rr.REGIME_RANGE_BOUND) == "MeanReversion"

    def test_a_manifest_winner_overrides_the_default(self):
        rr.update_regime_performance("MeanReversion", rr.REGIME_HIGH_VOL, 3.0, 0.7, 50, 4.0)
        router = rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "MeanReversion"

    def test_a_manifest_entry_with_too_few_trades_is_ignored(self):
        """The docstring's own reason: ≥ 10 trades, to avoid overfitting on a
        tiny sample. A two-trade Sharpe of 9 is noise."""
        rr.update_regime_performance("MeanReversion", rr.REGIME_HIGH_VOL, 9.0, 1.0, 2, 20.0)
        router = rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "Breakout"

    def test_a_manifest_entry_naming_an_unregistered_strategy_is_ignored(self):
        rr.update_regime_performance("Ghost", rr.REGIME_HIGH_VOL, 9.0, 1.0, 500, 20.0)
        router = rr.RegimeRouter(_Manager("Breakout"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "Breakout"

    def test_the_first_registered_strategy_is_the_last_resort(self):
        router = rr.RegimeRouter(_Manager("SomethingElse"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "SomethingElse"

    def test_with_nothing_registered_it_names_the_safe_default(self):
        router = rr.RegimeRouter(_Manager())
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "TrendFollowing"

    def test_a_manager_that_is_none_does_not_raise(self):
        assert rr.RegimeRouter(None)._select_strategy(rr.REGIME_LOW_VOL) == "TrendFollowing"

    def test_an_unmapped_regime_label_still_gets_the_safe_default(self):
        router = rr.RegimeRouter(_Manager("TrendFollowing"))
        assert router._select_strategy("a regime that does not exist") == "TrendFollowing"

    def test_selection_rereads_the_manifest_so_a_retrain_takes_effect(self):
        """`_select_strategy` calls `_reload_manifest()` on every call.

        The retrain loop writes the manifest from another process; a router that
        cached it at construction would route on last week's Sharpe until
        restart.
        """
        router = rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "Breakout"

        rr.update_regime_performance("TrendFollowing", rr.REGIME_HIGH_VOL, 5.0, 0.8, 99, 6.0)
        assert router._select_strategy(rr.REGIME_HIGH_VOL) == "TrendFollowing"


class TestRouting:
    @pytest.fixture
    def router(self):
        return rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))

    def test_route_returns_both_the_regime_and_the_strategy(self, router):
        regime, strategy = router.route(_ohlc(list(np.linspace(1900.0, 2400.0, 60)), spread=0.5))
        assert regime == rr.REGIME_TRENDING_UP
        assert strategy == "TrendFollowing"

    def test_routing_updates_the_reported_state(self, router):
        router.route(_ohlc([2000.0] * 60))
        assert router.current_regime == rr.REGIME_LOW_VOL
        assert router.current_confidence == pytest.approx(0.7)

    def test_a_regime_change_is_recorded_and_a_repeat_is_not(self, router):
        flat = _ohlc([2000.0] * 60)
        router.route(flat)
        router.route(flat)
        router.route(flat)
        assert len(router.regime_history()) == 1, "an unchanged regime must not fill the history"

    def test_a_genuine_change_appends(self, router):
        router.route(_ohlc([2000.0] * 60))
        router.route(_ohlc(list(np.linspace(1900.0, 2400.0, 60)), spread=0.5))
        history = router.regime_history()
        assert [h["regime"] for h in history] == [rr.REGIME_LOW_VOL, rr.REGIME_TRENDING_UP]
        assert all("timestamp" in h and "confidence" in h for h in history)

    def test_the_history_is_bounded(self, router):
        for i in range(1200):
            router._regime_history.append((rr.ALL_REGIMES[i % len(rr.ALL_REGIMES)], 0.5, "t"))
        router.route(_ohlc([2000.0] * 60))
        assert len(router._regime_history) <= 500

    def test_the_history_limit_is_honoured(self, router):
        for i in range(50):
            router._regime_history.append((rr.ALL_REGIMES[i % len(rr.ALL_REGIMES)], 0.5, f"t{i}"))
        assert len(router.regime_history(limit=5)) == 5
        assert router.regime_history(limit=5)[-1]["timestamp"] == "t49"

    def test_a_fresh_router_reports_unknown_rather_than_a_guess(self, router):
        assert router.current_regime == rr.REGIME_UNKNOWN
        assert router.current_confidence == 0.0
        assert router.regime_history() == []


class TestTheStatusPayload:
    def test_it_reports_the_regime_the_confidence_and_the_choice(self):
        router = rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))
        router.route(_ohlc([2000.0] * 60))
        status = router.status()
        assert status["current_regime"] == rr.REGIME_LOW_VOL
        assert status["confidence"] == pytest.approx(0.7)
        assert status["selected_strategy"] == "MeanReversion"

    def test_the_manifest_is_summarised_for_the_dashboard(self):
        rr.update_regime_performance("Breakout", rr.REGIME_HIGH_VOL, 1.23456, 0.65432, 40, 2.1)
        router = rr.RegimeRouter(_Manager("Breakout"))
        entries = router.status()["manifest_entries"][rr.REGIME_HIGH_VOL]
        assert entries == [{"strategy": "Breakout", "sharpe": 1.235, "win_rate": 0.654, "trades": 40}]

    def test_an_empty_manifest_is_an_empty_dict_not_a_missing_key(self):
        assert rr.RegimeRouter(_Manager("Breakout")).status()["manifest_entries"] == {}


class TestTheShimPointsAtThisModule:
    def test_core_regime_router_reexports_the_same_class(self):
        """`core/regime_router.py` was measured at 73.77% while the module it
        re-exports was at 0%, which is how a shim ends up better covered than
        the thing it points at."""
        from core.regime_router import RegimeRouter as Shimmed

        assert Shimmed is rr.RegimeRouter


class TestTheRegimeChangeEvent:
    """A regime change publishes to the legacy bus so `StrategyOrchestra`
    can rebalance allocations. Three ways it silently does not.

    `hopefx-dead-controls` shape #1 and #4 together: the publish is gated on
    `_get_shared_orchestra()` returning something *and* on there being a running
    event loop, and every failure is swallowed at DEBUG. That is defensible —
    a missed rebalance must not take down the router that decides which
    strategy trades — but it means "no rebalance happened" and "no regime
    change happened" look identical in production logs, so the conditions are
    worth pinning.
    """

    @pytest.fixture
    def router(self):
        return rr.RegimeRouter(_Manager("TrendFollowing", "MeanReversion", "Breakout"))

    class _Bus:
        def __init__(self) -> None:
            self.published: list = []

        async def publish(self, event):
            self.published.append(event)

    class _Orchestra:
        def __init__(self, bus) -> None:
            self.event_bus = bus

    @pytest.mark.asyncio
    async def test_a_regime_change_reaches_the_orchestras_bus(self, router, monkeypatch):
        import asyncio

        import core.strategy_orchestra as orchestra_mod

        bus = self._Bus()
        monkeypatch.setattr(orchestra_mod, "_get_shared_orchestra", lambda: self._Orchestra(bus))

        router.route(_ohlc([2000.0] * 60))
        await asyncio.sleep(0)  # let the created task run

        assert len(bus.published) == 1
        event = bus.published[0]
        # `DomainEvent` is the compact wire form: the type is an int code and
        # the body is a compressed payload, so read it the way a subscriber
        # would rather than reaching for a `.data` attribute it does not have.
        assert event.event_type == 9, "REGIME_CHANGE is code 9 in DomainEvent.create"
        assert event.source == "regime_router"
        body = event.decode()
        assert body["regime"] == rr.REGIME_LOW_VOL
        assert body["confidence"] == pytest.approx(0.7)
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_an_unchanged_regime_publishes_nothing(self, router, monkeypatch):
        import asyncio

        import core.strategy_orchestra as orchestra_mod

        bus = self._Bus()
        monkeypatch.setattr(orchestra_mod, "_get_shared_orchestra", lambda: self._Orchestra(bus))

        flat = _ohlc([2000.0] * 60)
        router.route(flat)
        router.route(flat)
        await asyncio.sleep(0)
        assert len(bus.published) == 1, "the bus is only told about changes, not about every bar"

    @pytest.mark.asyncio
    async def test_no_orchestra_means_no_publish_and_no_error(self, router, monkeypatch):
        import core.strategy_orchestra as orchestra_mod

        monkeypatch.setattr(orchestra_mod, "_get_shared_orchestra", lambda: None)
        regime, strategy = router.route(_ohlc([2000.0] * 60))
        assert regime == rr.REGIME_LOW_VOL
        assert strategy == "MeanReversion"

    @pytest.mark.asyncio
    async def test_an_orchestra_that_explodes_does_not_stop_the_routing(self, router, monkeypatch):
        """The routing decision is the product; the notification is not.

        Asserted because the alternative — letting a bus failure propagate —
        would make a rebalance hook able to stop the platform choosing a
        strategy at all.
        """
        import core.strategy_orchestra as orchestra_mod

        def _boom():
            raise RuntimeError("orchestra is down")

        monkeypatch.setattr(orchestra_mod, "_get_shared_orchestra", _boom)
        assert router.route(_ohlc([2000.0] * 60)) == (rr.REGIME_LOW_VOL, "MeanReversion")
        # And the change is still recorded locally, so the dashboard is right
        # even when the rebalance never happened.
        assert [h["regime"] for h in router.regime_history()] == [rr.REGIME_LOW_VOL]

    def test_outside_an_event_loop_it_declines_rather_than_raising(self, router, monkeypatch):
        """`asyncio.get_running_loop()` raises `RuntimeError` in a sync context.

        `route` is called from synchronous code paths, so this is the normal
        case rather than the edge case — and it means the orchestra is *not*
        notified whenever the router is driven synchronously.
        """
        import core.strategy_orchestra as orchestra_mod

        bus = self._Bus()
        monkeypatch.setattr(orchestra_mod, "_get_shared_orchestra", lambda: self._Orchestra(bus))

        assert router.route(_ohlc([2000.0] * 60)) == (rr.REGIME_LOW_VOL, "MeanReversion")
        assert bus.published == [], "a sync caller cannot schedule the publish; this is by construction"
