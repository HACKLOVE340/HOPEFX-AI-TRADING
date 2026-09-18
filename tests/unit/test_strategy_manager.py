# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_strategy_manager.py
====================================
The most-imported module in `strategies/`, at 31.7%.

Coverage-floor programme, Task 6c. `strategies/manager.py` has 234 production
importers — more than the rest of the package combined — and was the least
covered thing in it. It holds three built-in strategies, the subscription-tier
gate, the two zero-price guards that stand between a strategy and the execution
engine, signal deduplication, and every performance figure the platform reports
per strategy.

Three findings came out of covering it, all proved by execution before anything
was written:

**F283 — the brain's "is this strategy available" check cannot succeed.**
`brain/hopefx_brain.py:525` does `available = set(_list_fn())` where `_list_fn`
is `StrategyManager.list_strategies`, which returns a list of **dicts**. That
raises `TypeError: unhashable type: 'dict'` into
`except Exception: logger.debug(...)`, so `_route_strategy` always falls through
to `candidates[0]` — the first name in a hardcoded table — while believing it
consulted the manager.

**F284 — `max_drawdown` can report more than 100%.** It divides by cumulative
P&L rather than by account equity, so +10 then −20 measures as `2.0`.

**F285 — `profit_factor` is `float("inf")` when nothing has lost.** `round(inf, 4)`
is `inf`, and `json.dumps(..., allow_nan=False)` refuses it.

`risk-metrics-calculation` is the skill those last two come from: *document
assumptions* and *don't rely on a single metric*. A drawdown figure that exceeds
1.0 and a profit factor that cannot be serialised are both reporting the
arithmetic rather than the account.

The `backtesting-frameworks` sweep is clean — the two built-in strategies read
`closes[-period:]` and compare against the last bar, with no window that
contains the bar it is being compared against (the third, `BreakoutStrategy`,
did, and was F275).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import pytest

from strategies.base import StrategyStatus
from strategies.manager import (
    MeanReversionStrategy,
    Signal,
    StrategyManager,
    TrendFollowingStrategy,
    _plan_satisfies,
)


@dataclass
class _Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0


def _ramp(n: int, start: float, end: float, spread: float = 2.0) -> list[_Candle]:
    step = (end - start) / max(n - 1, 1)
    return [
        _Candle(start + step * i, start + step * i + spread, start + step * i - spread, start + step * i)
        for i in range(n)
    ]


def _flat(n: int, price: float = 2000.0, spread: float = 2.0) -> list[_Candle]:
    return [_Candle(price, price + spread, price - spread, price) for _ in range(n)]


class _Engine:
    """Minimal stand-in for the price engine the manager is handed."""

    def __init__(self, bars: list[_Candle] | None = None, raises: bool = False) -> None:
        self._bars = bars if bars is not None else _flat(100)
        self._raises = raises
        self.calls: list[tuple] = []

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
        self.calls.append((symbol, timeframe, limit))
        if self._raises:
            raise RuntimeError("feed is down")
        return self._bars


# ─────────────────────────────────────────────────────────────────────────────
# Plan gating
# ─────────────────────────────────────────────────────────────────────────────


class TestThePlanLadder:
    @pytest.mark.parametrize(
        ("user", "required", "expected"),
        [
            ("starter", "starter", True),
            ("professional", "starter", True),
            ("elite", "enterprise", True),
            ("starter", "professional", False),
            ("trial", "starter", False),
            ("STARTER", "starter", True),  # case-insensitive
            ("enterprise", "ELITE", False),
        ],
    )
    def test_a_plan_satisfies_what_it_meets_or_exceeds(self, user, required, expected):
        assert _plan_satisfies(user, required) is expected

    def test_an_unknown_plan_name_satisfies_nothing(self):
        """Fail closed: a typo in a plan name must not unlock a strategy."""
        assert _plan_satisfies("platinum", "starter") is False
        assert _plan_satisfies("starter", "platinum") is False


# ─────────────────────────────────────────────────────────────────────────────
# BaseStrategy.update_performance
# ─────────────────────────────────────────────────────────────────────────────


class TestPerformanceBookkeeping:
    @pytest.fixture
    def strategy(self):
        return TrendFollowingStrategy()

    def test_a_fresh_strategy_reports_nothing_rather_than_guessing(self, strategy):
        m = strategy.performance_metrics
        assert m["trades_taken"] == 0
        assert m["win_rate"] == 0.0
        assert m["total_pnl"] == 0.0
        assert m["last_signal_at"] is None

    def test_a_winning_trade_is_counted_and_summed(self, strategy):
        strategy.update_performance({"pnl": 120.5, "won": True})
        m = strategy.performance_metrics
        assert m["trades_taken"] == 1
        assert m["winning_trades"] == 1
        assert m["total_pnl"] == pytest.approx(120.5)
        assert m["win_rate"] == 1.0

    def test_won_is_inferred_from_the_sign_when_not_given(self, strategy):
        strategy.update_performance({"pnl": -40.0})
        assert strategy.performance_metrics["losing_trades"] == 1

    def test_an_explicit_won_flag_overrides_the_sign(self, strategy):
        """A scratch closed at a tiny loss can still be a win by the caller's
        accounting; the flag is the caller's to set."""
        strategy.update_performance({"pnl": -0.01, "won": True})
        assert strategy.performance_metrics["winning_trades"] == 1

    def test_a_break_even_trade_counts_as_a_loss(self, strategy):
        """`won = bool(trade_result.get("won", pnl > 0))` — zero is not > 0.
        Asserted rather than changed: it is a convention, and a reader who
        assumes otherwise will mis-read the win rate."""
        strategy.update_performance({"pnl": 0.0})
        assert strategy.performance_metrics["losing_trades"] == 1

    def test_the_win_rate_is_the_ratio_of_trades_not_of_money(self, strategy):
        strategy.update_performance({"pnl": 1.0})
        strategy.update_performance({"pnl": -1000.0})
        assert strategy.performance_metrics["win_rate"] == pytest.approx(0.5)

    def test_the_profit_factor_is_gross_profit_over_gross_loss(self, strategy):
        strategy.update_performance({"pnl": 300.0})
        strategy.update_performance({"pnl": -100.0})
        assert strategy.performance_metrics["profit_factor"] == pytest.approx(3.0)

    def test_the_sharpe_needs_two_trades_before_it_says_anything(self, strategy):
        strategy.update_performance({"pnl": 10.0})
        assert strategy.performance_metrics["sharpe_ratio"] == 0.0

    def test_the_sharpe_is_the_annualised_mean_over_standard_deviation(self, strategy):
        for pnl in (10.0, 20.0, 30.0):
            strategy.update_performance({"pnl": pnl})
        expected = 20.0 / 10.0 * math.sqrt(8760)
        assert strategy.performance_metrics["sharpe_ratio"] == pytest.approx(round(expected, 4))

    def test_identical_returns_have_no_dispersion_and_so_no_sharpe(self, strategy):
        """`std_r > 0` guards the division. Three identical trades are a
        zero-variance series, and reporting an infinite Sharpe for it would be
        the same defect as F285's profit factor."""
        for _ in range(3):
            strategy.update_performance({"pnl": 10.0})
        assert strategy.performance_metrics["sharpe_ratio"] == 0.0


class TestTheTwoMetricsThatCannotBeRight:
    """F284 and F285, asserted as they behave today.

    Both are raised as §A19 rather than patched: changing what a reported risk
    figure means is the owner's call, and `CLAUDE.md` is explicit that a
    money-moving system gets targeted changes rather than invented numbers.
    """

    def test_the_drawdown_can_exceed_one_hundred_percent(self):
        """`(peak - equity) / (peak + 1e-9)` over cumulative P&L, not equity.

        Up 10 then down 20 leaves cumulative P&L at −10 against a peak of +10,
        which this arithmetic calls a 200% drawdown. No account can lose more
        than it had; the figure is a ratio of P&L to P&L, and a drawdown
        fraction needs capital in the denominator.
        """
        strategy = TrendFollowingStrategy()
        strategy.update_performance({"pnl": 10.0})
        strategy.update_performance({"pnl": -20.0})
        assert strategy.performance_metrics["max_drawdown"] == pytest.approx(2.0), (
            "if this is now <= 1.0 the metric was fixed — close F284 and update §A19"
        )

    def test_a_deeper_case_reports_one_hundred_and_fifty_percent(self):
        strategy = TrendFollowingStrategy()
        for pnl in (100.0, -100.0, -50.0):
            strategy.update_performance({"pnl": pnl})
        assert strategy.performance_metrics["max_drawdown"] == pytest.approx(1.5)

    def test_a_curve_that_never_goes_below_its_start_stays_inside_one(self):
        """The metric is only meaningful while the trough stays above zero —
        which is the case it was presumably written against."""
        strategy = TrendFollowingStrategy()
        for pnl in (100.0, -10.0, 50.0):
            strategy.update_performance({"pnl": pnl})
        assert 0.0 <= strategy.performance_metrics["max_drawdown"] <= 1.0

    def test_the_profit_factor_is_infinity_when_nothing_has_lost(self):
        strategy = TrendFollowingStrategy()
        for pnl in (5.0, 10.0):
            strategy.update_performance({"pnl": pnl})
        assert strategy.performance_metrics["profit_factor"] == float("inf")

    def test_that_infinity_is_not_valid_json(self):
        """Which is the part that bites: `list_strategies()` embeds the whole
        metrics dict under `"performance"`, and a strict encoder refuses it.
        `json.dumps` allows it by default and emits the non-standard literal
        `Infinity`, which many clients reject.
        """
        strategy = TrendFollowingStrategy()
        strategy.update_performance({"pnl": 5.0})
        metrics = strategy.performance_metrics

        with pytest.raises(ValueError, match="not JSON compliant"):
            json.dumps(metrics, allow_nan=False)
        assert "Infinity" in json.dumps(metrics)


# ─────────────────────────────────────────────────────────────────────────────
# TrendFollowingStrategy
# ─────────────────────────────────────────────────────────────────────────────


class TestTrendFollowing:
    @pytest.fixture
    def strategy(self):
        return TrendFollowingStrategy({"fast_period": 20, "slow_period": 50})

    @pytest.mark.parametrize("regime", ["ranging", "volatile", "unknown", "mean_reverting"])
    async def test_it_stays_out_of_every_regime_but_a_trend(self, strategy, regime):
        assert await strategy.generate_signals("XAUUSD", _ramp(80, 1900.0, 2200.0), regime) == []

    async def test_too_little_history_produces_nothing(self, strategy):
        assert await strategy.generate_signals("XAUUSD", _ramp(30, 1900.0, 2200.0), "trending_up") == []

    async def test_a_rising_market_in_an_uptrend_buys(self, strategy):
        signals = await strategy.generate_signals("XAUUSD", _ramp(80, 1900.0, 2400.0), "trending_up")
        assert [s.action for s in signals] == ["buy"]
        sig = signals[0]
        assert sig.strategy == "TrendFollowing"
        assert sig.metadata["fast_ma"] > sig.metadata["slow_ma"]
        assert sig.stop_loss < sig.entry_price < sig.take_profit
        assert 0.0 < sig.strength <= 1.0

    async def test_a_falling_market_in_a_downtrend_sells(self, strategy):
        signals = await strategy.generate_signals("XAUUSD", _ramp(80, 2400.0, 1900.0), "trending_down")
        assert [s.action for s in signals] == ["sell"]
        sig = signals[0]
        assert sig.metadata["fast_ma"] < sig.metadata["slow_ma"]
        assert sig.take_profit < sig.entry_price < sig.stop_loss

    async def test_the_direction_must_agree_with_the_regime(self, strategy):
        """A rising market labelled a downtrend produces nothing. The regime is
        the platform's classification and the MAs are the strategy's; the
        strategy refuses when they disagree rather than picking a side."""
        assert await strategy.generate_signals("XAUUSD", _ramp(80, 1900.0, 2400.0), "trending_down") == []
        assert await strategy.generate_signals("XAUUSD", _ramp(80, 2400.0, 1900.0), "trending_up") == []

    async def test_a_weak_trend_is_below_the_threshold(self, strategy):
        """`trend_strength = |fast - slow| / mean(high-low)`, against 0.3. A
        market whose MA separation is small next to its bar ranges is noise."""
        bars = _ramp(80, 2000.0, 2002.0, spread=50.0)
        assert await strategy.generate_signals("XAUUSD", bars, "trending_up") == []

    async def test_a_signal_is_counted_where_the_dashboard_reads_it(self, strategy):
        await strategy.generate_signals("XAUUSD", _ramp(80, 1900.0, 2400.0), "trending_up")
        m = strategy.performance_metrics
        assert m["signals_generated"] == 1
        assert m["last_signal_at"] is not None

    async def test_a_malformed_bar_marks_the_strategy_in_error_and_returns_nothing(self, strategy):
        """The status change is the part that matters: `generate_signals` on the
        manager skips anything not RUNNING or IDLE, so a strategy that starts
        raising takes itself out of the rotation rather than being retried
        silently forever."""
        signals = await strategy.generate_signals("XAUUSD", [object()] * 80, "trending_up")
        assert signals == []
        assert strategy.status is StrategyStatus.ERROR

    async def test_zero_range_bars_do_not_divide_by_zero(self, strategy):
        bars = [_Candle(2000.0, 2000.0, 2000.0, 2000.0 + i) for i in range(80)]
        assert await strategy.generate_signals("XAUUSD", bars, "trending_up") == []


# ─────────────────────────────────────────────────────────────────────────────
# MeanReversionStrategy
# ─────────────────────────────────────────────────────────────────────────────


class TestMeanReversion:
    @pytest.fixture
    def strategy(self):
        return MeanReversionStrategy({"period": 20, "std_dev": 2.0})

    @pytest.mark.parametrize("regime", ["trending_up", "trending_down", "volatile", "unknown"])
    async def test_it_only_trades_a_range(self, strategy, regime):
        bars = _flat(40) + [_Candle(2000.0, 2001.0, 1890.0, 1900.0)]
        assert await strategy.generate_signals("XAUUSD", bars, regime) == []

    async def test_too_little_history_produces_nothing(self, strategy):
        assert await strategy.generate_signals("XAUUSD", _flat(5), "ranging") == []

    async def test_a_price_far_below_the_lower_band_buys(self, strategy):
        import numpy as np

        rng = np.random.default_rng(0)
        bars = [_Candle(2000.0, 2002.0, 1998.0, 2000.0 + float(rng.normal(0, 5))) for _ in range(30)]
        bars.append(_Candle(2000.0, 2001.0, 1880.0, 1900.0))
        signals = await strategy.generate_signals("XAUUSD", bars, "ranging")
        assert [s.action for s in signals] == ["buy"]
        sig = signals[0]
        assert sig.metadata["z_score"] < 0
        assert sig.take_profit == pytest.approx(sig.metadata["sma"]), "mean reversion targets the mean"
        # The stop is asserted in TestTheStopCanSitOnTheWrongSideOfTheEntry, not
        # here: on this fixture it lands ABOVE the buy entry. F286.
        assert sig.stop_loss == pytest.approx(sig.metadata["lower_band"] * 0.99)

    async def test_a_price_far_above_the_upper_band_sells(self, strategy):
        import numpy as np

        rng = np.random.default_rng(0)
        bars = [_Candle(2000.0, 2002.0, 1998.0, 2000.0 + float(rng.normal(0, 5))) for _ in range(30)]
        bars.append(_Candle(2000.0, 2120.0, 1999.0, 2100.0))
        signals = await strategy.generate_signals("XAUUSD", bars, "ranging")
        assert [s.action for s in signals] == ["sell"]
        assert signals[0].metadata["z_score"] > 0
        assert signals[0].stop_loss == pytest.approx(signals[0].metadata["upper_band"] * 1.01)

    async def test_a_price_inside_the_bands_produces_nothing(self, strategy):
        import numpy as np

        rng = np.random.default_rng(0)
        bars = [_Candle(2000.0, 2002.0, 1998.0, 2000.0 + float(rng.normal(0, 5))) for _ in range(31)]
        assert await strategy.generate_signals("XAUUSD", bars, "ranging") == []

    async def test_a_flat_series_has_no_deviation_and_so_no_z_score(self, strategy):
        """`std > 0` guards the division; a zero-variance window has no
        outlier to revert from."""
        assert await strategy.generate_signals("XAUUSD", _flat(40), "ranging") == []

    async def test_a_malformed_bar_marks_the_strategy_in_error(self, strategy):
        assert await strategy.generate_signals("XAUUSD", [object()] * 40, "ranging") == []
        assert strategy.status is StrategyStatus.ERROR


# ─────────────────────────────────────────────────────────────────────────────
# StrategyManager — registration and lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistrationAndLifecycle:
    def test_an_empty_manager_preloads_nothing(self):
        assert StrategyManager().strategies == {}

    def test_the_defaults_are_the_three_built_ins(self):
        assert set(StrategyManager(preload_defaults=True).strategies) == {
            "TrendFollowing",
            "MeanReversion",
            "Breakout",
        }

    def test_registering_keys_by_the_strategy_name(self):
        manager = StrategyManager()
        manager.register_strategy(TrendFollowingStrategy())
        assert "TrendFollowing" in manager.strategies

    def test_registering_the_same_name_twice_replaces_rather_than_duplicates(self):
        manager = StrategyManager()
        first = TrendFollowingStrategy()
        second = TrendFollowingStrategy()
        manager.register_strategy(first)
        manager.register_strategy(second)
        assert len(manager.strategies) == 1
        assert manager.strategies["TrendFollowing"] is second

    def test_unregistering_reports_whether_it_found_anything(self):
        manager = StrategyManager(preload_defaults=True)
        assert manager.unregister_strategy("Breakout") is True
        assert manager.unregister_strategy("Breakout") is False
        assert "Breakout" not in manager.strategies

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("start_strategy", StrategyStatus.RUNNING),
            ("stop_strategy", StrategyStatus.STOPPED),
            ("pause_strategy", StrategyStatus.PAUSED),
        ],
    )
    def test_each_lifecycle_call_sets_its_status_and_reports_success(self, method, expected):
        manager = StrategyManager(preload_defaults=True)
        assert getattr(manager, method)("TrendFollowing") is True
        assert manager.strategies["TrendFollowing"].status is expected

    @pytest.mark.parametrize(
        "method",
        ["start_strategy", "stop_strategy", "pause_strategy", "enable_strategy", "disable_strategy"],
    )
    def test_a_name_that_is_not_registered_reports_failure_rather_than_raising(self, method):
        assert getattr(StrategyManager(), method)("Nonexistent") is False

    def test_start_all_and_stop_all_move_every_strategy(self):
        manager = StrategyManager(preload_defaults=True)
        manager.start_all()
        assert all(s.status is StrategyStatus.RUNNING for s in manager.strategies.values())
        manager.stop_all()
        assert all(s.status is StrategyStatus.STOPPED for s in manager.strategies.values())

    def test_enable_and_disable_move_the_flag_not_the_status(self):
        manager = StrategyManager(preload_defaults=True)
        manager.start_strategy("Breakout")
        assert manager.disable_strategy("Breakout") is True
        assert manager.strategies["Breakout"].enabled is False
        assert manager.strategies["Breakout"].status is StrategyStatus.RUNNING, (
            "disabled and stopped are different states; conflating them would make "
            "a re-enable silently resume something the operator had stopped"
        )
        assert manager.enable_strategy("Breakout") is True
        assert manager.strategies["Breakout"].enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# StrategyManager.generate_signals — the gates
# ─────────────────────────────────────────────────────────────────────────────


class TestTheSignalGates:
    @pytest.fixture
    def manager(self):
        manager = StrategyManager(preload_defaults=True)
        manager.start_all()
        return manager

    async def test_a_feed_that_raises_skips_the_symbol_rather_than_the_run(self, manager, caplog):
        import logging

        with caplog.at_level(logging.DEBUG, logger="strategies.manager"):
            signals = await manager.generate_signals({"XAUUSD": "trending_up"}, _Engine(raises=True), user_plan="elite")
        assert signals == []
        records = [r for r in caplog.records if "price_data_error" in r.getMessage()]
        assert records
        assert all(r.levelno >= logging.WARNING for r in records)

    async def test_too_few_bars_skips_the_symbol(self, manager):
        assert await manager.generate_signals({"XAUUSD": "trending_up"}, _Engine(_flat(10)), "elite") == []

    async def test_no_bars_at_all_skips_the_symbol(self, manager):
        assert await manager.generate_signals({"XAUUSD": "trending_up"}, _Engine([]), "elite") == []

    async def test_a_zero_close_on_the_last_bar_is_refused_loudly(self, manager, caplog):
        """The guard's own comment says why: a zero close becomes a zero-price
        broker order. It logs at ERROR, which is the level a refused trade
        deserves."""
        import logging

        bars = _flat(100)
        bars[-1] = _Candle(0.0, 0.0, 0.0, 0.0)
        with caplog.at_level(logging.DEBUG, logger="strategies.manager"):
            signals = await manager.generate_signals({"XAUUSD": "trending_up"}, _Engine(bars), "elite")
        assert signals == []
        records = [r for r in caplog.records if "skip_zero_price" in r.getMessage()]
        assert records
        assert all(r.levelno >= logging.ERROR for r in records)

    async def test_a_last_bar_with_no_close_attribute_is_refused(self, manager):
        bars = _flat(100)
        bars[-1] = object()  # type: ignore[assignment]
        assert await manager.generate_signals({"XAUUSD": "trending_up"}, _Engine(bars), "elite") == []

    async def test_a_disabled_strategy_is_not_asked(self, manager):
        manager.disable_strategy("TrendFollowing")
        signals = await manager.generate_signals(
            {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
        )
        assert all(s["strategy"] != "TrendFollowing" for s in signals)

    @pytest.mark.parametrize("status", [StrategyStatus.STOPPED, StrategyStatus.PAUSED, StrategyStatus.ERROR])
    async def test_a_strategy_that_is_not_running_or_idle_is_not_asked(self, manager, status):
        manager.strategies["TrendFollowing"].status = status
        signals = await manager.generate_signals(
            {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
        )
        assert all(s["strategy"] != "TrendFollowing" for s in signals)

    async def test_an_idle_strategy_is_asked(self, manager):
        """IDLE is explicitly allowed alongside RUNNING. That is load-bearing:
        a freshly registered strategy is IDLE, and a gate that required RUNNING
        would mean nothing traded until someone called start."""
        manager.stop_all()
        manager.strategies["TrendFollowing"].status = StrategyStatus.IDLE
        signals = await manager.generate_signals(
            {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
        )
        assert [s["strategy"] for s in signals] == ["TrendFollowing"]

    async def test_the_plan_gate_withholds_a_strategy_above_the_users_tier(self, manager):
        """`TrendFollowing` is starter; `MeanReversion` and `Breakout` are
        professional. A starter user gets the first and not the others."""
        signals = await manager.generate_signals(
            {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), user_plan="starter"
        )
        assert [s["strategy"] for s in signals] == ["TrendFollowing"]

    async def test_a_trial_user_gets_nothing_at_all(self, manager):
        assert (
            await manager.generate_signals(
                {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), user_plan="trial"
            )
            == []
        )

    async def test_a_strategy_that_raises_is_marked_in_error_and_the_run_continues(self, manager):
        class _Exploding(TrendFollowingStrategy):
            async def generate_signals(self, symbol, price_data, market_regime):
                raise RuntimeError("strategy is broken")

        broken = _Exploding()
        broken.name = "Exploding"
        manager.register_strategy(broken)
        manager.start_all()

        signals = await manager.generate_signals(
            {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
        )
        assert broken.status is StrategyStatus.ERROR
        assert any(s["strategy"] == "TrendFollowing" for s in signals), "one broken strategy must not silence the rest"

    async def test_a_zero_price_signal_is_discarded_loudly(self, manager, caplog):
        import logging

        class _ZeroPrice(TrendFollowingStrategy):
            async def generate_signals(self, symbol, price_data, market_regime):
                return [
                    Signal(
                        symbol=symbol,
                        action="buy",
                        strength=0.9,
                        strategy=self.name,
                        entry_price=0.0,
                        stop_loss=0.0,
                        take_profit=0.0,
                        timeframe="1h",
                    )
                ]

        zero = _ZeroPrice()
        zero.name = "ZeroPrice"
        manager.register_strategy(zero)
        manager.start_all()

        with caplog.at_level(logging.DEBUG, logger="strategies.manager"):
            signals = await manager.generate_signals(
                {"XAUUSD": "trending_up"}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
            )
        assert all(s["strategy"] != "ZeroPrice" for s in signals)
        records = [r for r in caplog.records if "zero_price_signal" in r.getMessage()]
        assert records
        assert all(r.levelno >= logging.ERROR for r in records)

    async def test_a_regime_enum_is_read_through_its_value(self, manager):
        from enum import Enum

        class _Regime(Enum):
            TRENDING_UP = "trending_up"

        signals = await manager.generate_signals(
            {"XAUUSD": _Regime.TRENDING_UP}, _Engine(_ramp(100, 1900.0, 2400.0)), "elite"
        )
        assert [s["strategy"] for s in signals] == ["TrendFollowing"]

    async def test_every_symbol_is_asked_for_its_own_bars(self, manager):
        engine = _Engine(_ramp(100, 1900.0, 2400.0))
        await manager.generate_signals({"XAUUSD": "trending_up", "EURUSD": "trending_up"}, engine, "elite")
        assert {call[0] for call in engine.calls} == {"XAUUSD", "EURUSD"}


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────────


def _sig_dict(symbol: str, action: str, strength: float, strategy: str = "S") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "action": action,
        "strength": strength,
        "strategy": strategy,
        "entry_price": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
        "timeframe": "1h",
        "timestamp": 0.0,
        "metadata": {},
    }


class TestDeduplication:
    @pytest.fixture
    def manager(self):
        return StrategyManager()

    def test_the_strongest_signal_per_symbol_and_action_survives(self, manager):
        out = manager._deduplicate_signals(
            [
                _sig_dict("XAUUSD", "buy", 0.4, "weak"),
                _sig_dict("XAUUSD", "buy", 0.9, "strong"),
                _sig_dict("XAUUSD", "buy", 0.6, "middling"),
            ]
        )
        assert [s["strategy"] for s in out] == ["strong"]

    def test_opposite_actions_on_one_symbol_both_survive(self, manager):
        """Deliberate, and worth pinning: the key is (symbol, action), so a buy
        and a sell on the same symbol are not duplicates. Whatever consumes
        this list has to resolve that conflict — the manager does not."""
        out = manager._deduplicate_signals([_sig_dict("XAUUSD", "buy", 0.9), _sig_dict("XAUUSD", "sell", 0.8)])
        assert {s["action"] for s in out} == {"buy", "sell"}

    def test_different_symbols_are_never_duplicates(self, manager):
        out = manager._deduplicate_signals([_sig_dict("XAUUSD", "buy", 0.5), _sig_dict("EURUSD", "buy", 0.5)])
        assert len(out) == 2

    def test_the_result_is_sorted_strongest_first(self, manager):
        out = manager._deduplicate_signals(
            [
                _sig_dict("A", "buy", 0.2),
                _sig_dict("B", "buy", 0.9),
                _sig_dict("C", "buy", 0.5),
            ]
        )
        assert [s["strength"] for s in out] == [0.9, 0.5, 0.2]

    def test_a_tie_keeps_the_first_seen(self, manager):
        """`>` rather than `>=`, so an equally strong later signal does not
        displace the earlier one. Arbitrary but stable, which is what matters
        for a list that decides orders."""
        out = manager._deduplicate_signals(
            [_sig_dict("XAUUSD", "buy", 0.5, "first"), _sig_dict("XAUUSD", "buy", 0.5, "second")]
        )
        assert [s["strategy"] for s in out] == ["first"]

    def test_an_empty_list_stays_empty(self, manager):
        assert manager._deduplicate_signals([]) == []


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────


class TestReporting:
    @pytest.fixture
    def manager(self):
        return StrategyManager(preload_defaults=True)

    def test_performance_for_one_strategy_is_its_own_metrics(self, manager):
        manager.update_strategy_performance("TrendFollowing", {"pnl": 50.0})
        assert manager.get_strategy_performance("TrendFollowing")["total_pnl"] == pytest.approx(50.0)

    def test_performance_for_an_unknown_strategy_is_empty_rather_than_an_error(self, manager):
        assert manager.get_strategy_performance("Nonexistent") == {}

    def test_performance_for_all_is_keyed_by_name(self, manager):
        assert set(manager.get_strategy_performance()) == set(manager.strategies)

    def test_updating_an_unknown_strategy_is_a_no_op(self, manager):
        manager.update_strategy_performance("Nonexistent", {"pnl": 1.0})  # must not raise

    def test_the_summary_counts_only_running_strategies_as_active(self, manager):
        manager.start_strategy("TrendFollowing")
        summary = manager.performance_summary
        assert summary["total_strategies"] == 3
        assert summary["active_strategies"] == 1

    def test_the_summary_sums_pnl_and_signals_across_strategies(self, manager):
        manager.update_strategy_performance("TrendFollowing", {"pnl": 30.0})
        manager.update_strategy_performance("MeanReversion", {"pnl": -10.0})
        summary = manager.performance_summary
        assert summary["total_pnl"] == pytest.approx(20.0)
        assert set(summary["strategies"]) == set(manager.strategies)

    def test_the_summary_tolerates_a_strategy_with_no_metrics_at_all(self, manager):
        """`_strategy_metrics`, `_strategy_status` and `_strategy_enabled` all
        default rather than raise, because legacy code registers objects that
        are not `BaseStrategy`. One such object must not break the summary for
        the others — the same shape as F278's `get_heatmap_data`."""

        class _Bare:
            name = "Bare"

        manager.register_strategy(_Bare())  # type: ignore[arg-type]
        summary = manager.performance_summary
        assert "Bare" in summary["strategies"]
        assert summary["strategies"]["Bare"]["status"] == StrategyStatus.IDLE.value
        assert summary["strategies"]["Bare"]["enabled"] is True

    def test_a_legacy_string_status_is_coerced(self, manager):
        manager.strategies["TrendFollowing"].status = "RUNNING"  # type: ignore[assignment]
        assert manager.performance_summary["active_strategies"] == 1

    def test_an_unrecognisable_status_falls_back_to_idle(self, manager):
        manager.strategies["TrendFollowing"].status = "NOT_A_STATUS"  # type: ignore[assignment]
        assert manager.performance_summary["strategies"]["TrendFollowing"]["status"] == StrategyStatus.IDLE.value


class TestListStrategies:
    @pytest.fixture
    def manager(self):
        return StrategyManager(preload_defaults=True)

    def test_it_reports_the_plan_each_strategy_needs(self, manager):
        rows = {row["name"]: row for row in manager.list_strategies("starter")}
        assert rows["TrendFollowing"]["required_plan"] == "starter"
        assert rows["Breakout"]["required_plan"] == "professional"

    def test_accessibility_is_relative_to_the_plan_asked_about(self, manager):
        starter = {row["name"]: row["accessible"] for row in manager.list_strategies("starter")}
        elite = {row["name"]: row["accessible"] for row in manager.list_strategies("elite")}
        assert starter["TrendFollowing"] is True
        assert starter["Breakout"] is False
        assert all(elite.values())

    def test_it_lists_everything_rather_than_filtering(self, manager):
        """The docstring says "Returns only strategies accessible on user_plan"
        and the code returns them all with an `accessible` flag. Asserted as it
        behaves, because a caller that trusted the docstring and skipped the
        flag would show a starter user a professional strategy as available."""
        assert len(manager.list_strategies("starter")) == 3

    def test_an_unknown_strategy_name_defaults_to_the_lowest_tier(self, manager):
        class _Custom:
            name = "CustomThing"

        manager.register_strategy(_Custom())  # type: ignore[arg-type]
        row = next(r for r in manager.list_strategies("starter") if r["name"] == "CustomThing")
        assert row["required_plan"] == "starter"
        assert row["accessible"] is True


# ─────────────────────────────────────────────────────────────────────────────
# The seam the brain reads through
# ─────────────────────────────────────────────────────────────────────────────


class TestTheBrainCannotReadThisManager:
    """F283. `brain/hopefx_brain.py:525` — `available = set(_list_fn())`.

    `list_strategies` returns a list of dicts, so `set()` on it raises
    `TypeError: unhashable type: 'dict'` into
    `except Exception: logger.debug(...)`, and `_route_strategy` falls through to
    `candidates[0]` — the first name in a hardcoded table — while believing it
    consulted the manager. Measured:

        DEBUG brain.hopefx_brain: Strategy manager query failed: unhashable type: 'dict'
        trending_up -> smc_ict
        ranging     -> mean_reversion
        volatile    -> breakout

    and with a stub whose `list_strategies` returns plain names, the intended
    logic works and picks `ema_crossover`.

    **A second mismatch sits behind the first.** This manager registers
    `TrendFollowing`, `MeanReversion` and `Breakout`; the brain's table names
    `smc_ict`, `ema_crossover`, `ma_crossover`, `mean_reversion`,
    `bollinger_bands`, `stochastic`, `rsi_strategy` and `breakout` — snake_case
    against CamelCase. So extracting the names correctly restores the mechanism
    and still matches nothing here, which is why the naming is raised as a
    decision (§A19) rather than guessed at. It is the third encoding mismatch
    recorded in this package, after §A9's three spellings of "long".
    """

    def test_the_public_shape_is_a_list_of_dicts(self):
        rows = StrategyManager(preload_defaults=True).list_strategies()
        assert isinstance(rows, list)
        assert all(isinstance(row, dict) for row in rows)

    def test_calling_set_on_it_is_what_raises(self):
        rows = StrategyManager(preload_defaults=True).list_strategies()
        with pytest.raises(TypeError, match="unhashable type: 'dict'"):
            set(rows)

    def test_the_names_are_recoverable_from_the_rows(self):
        """Which is the fix: read the `name` key rather than hashing the row."""
        rows = StrategyManager(preload_defaults=True).list_strategies()
        assert {row["name"] for row in rows} == {"TrendFollowing", "MeanReversion", "Breakout"}

    def test_the_brains_table_and_this_manager_share_no_name(self):
        from brain.hopefx_brain import _REGIME_STRATEGY_MAP

        registered = set(StrategyManager(preload_defaults=True).strategies)
        tabled = {name for names in _REGIME_STRATEGY_MAP.values() for name in names}
        assert registered.isdisjoint(tabled), (
            "a name now matches — the routing decision in §A19 has been taken, so update F283"
        )
        # And the near-miss that makes it a naming problem rather than a gap:
        # lower-casing recovers "breakout" but not "MeanReversion", because the
        # table spells it "mean_reversion" with an underscore. Case alone is not
        # the whole mismatch, which is why §A19 is a naming decision and not a
        # one-line `.lower()`.
        assert {n.lower() for n in registered} & tabled == {"breakout"}
        assert "mean_reversion" in tabled
        assert "meanreversion" not in tabled


class TestTheStopCanSitOnTheWrongSideOfTheEntry:
    """F286. `MeanReversionStrategy` anchors its stop to the band, not the fill.

    ```python
    stop_loss=lower * 0.99,   # buy
    stop_loss=upper * 1.01,   # sell
    ```

    The entry condition is `current < lower`, so the stop is below the entry
    only while the entry is inside the band's own 1% buffer — `entry > lower *
    0.99`. Any close that gaps further than 1% past the band (about 20 points on
    XAUUSD at 2000) gets a **stop above its buy entry**, which a broker either
    rejects or fills immediately at a loss. The sell branch is the mirror.

    Measured over 3,000 random ranging windows before anything was changed:

        buy signals with stop BELOW entry (correct): 887
        buy signals with stop ABOVE entry (broken) : 990

    So it is wrong on roughly **53%** of the signals it produces — not an edge
    case, and not always, which is why it survived: half the fixtures anyone
    would reach for look fine.

    **Not fixed here.** The obvious repair (`min(lower * 0.99, entry * 0.99)`)
    changes the stop distance, and therefore the position size every risk model
    downstream derives from it. Inventing a stop-loss rule in a money-moving
    system is exactly what `CLAUDE.md` forbids doing without the owner. Raised
    as §A19 alongside F283–F285.
    """

    @pytest.fixture
    def strategy(self):
        return MeanReversionStrategy({"period": 20, "std_dev": 2.0})

    @staticmethod
    def _window(last_close: float, seed: int = 0) -> list[_Candle]:
        import numpy as np

        rng = np.random.default_rng(seed)
        base = [_Candle(2000.0, 2002.0, 1998.0, 2000.0 + float(rng.normal(0, 5))) for _ in range(30)]
        return [*base, _Candle(2000.0, 2001.0, last_close - 5.0, last_close)]

    async def test_a_buy_that_gapped_past_the_band_gets_a_stop_above_its_entry(self, strategy):
        (sig,) = await strategy.generate_signals("XAUUSD", self._window(1900.0), "ranging")
        assert sig.action == "buy"
        assert sig.stop_loss > sig.entry_price, "if this now fails the stop was fixed — close F286 and update §A19"

    async def test_the_stop_is_the_band_rather_than_the_fill(self, strategy):
        """Which is the whole mechanism: it never looks at what it paid."""
        (sig,) = await strategy.generate_signals("XAUUSD", self._window(1900.0), "ranging")
        assert sig.stop_loss == pytest.approx(sig.metadata["lower_band"] * 0.99)
        assert sig.stop_loss != pytest.approx(sig.entry_price * 0.99)

    async def test_a_buy_that_only_just_cleared_the_band_is_fine(self, strategy):
        """The half that works, so the boundary is recorded rather than implied.

        Inside the band's 1% buffer the stop lands below the entry, which is why
        this reads as correct in any fixture that does not overshoot.
        """
        import numpy as np

        rng = np.random.default_rng(7)
        found = None
        for _ in range(400):
            vol = rng.uniform(0.5, 40.0)
            base = [_Candle(2000.0, 2002.0, 1998.0, 2000.0 + float(rng.normal(0, vol))) for _ in range(30)]
            last = 2000.0 + float(rng.normal(0, vol)) - rng.uniform(0, 6 * vol)
            out = await strategy.generate_signals(
                "XAUUSD", [*base, _Candle(2000.0, 2001.0, last - 1.0, last)], "ranging"
            )
            if out and out[0].action == "buy" and out[0].stop_loss < out[0].entry_price:
                found = out[0]
                break
        assert found is not None, "no correctly-stopped buy in 400 windows — F286 may now be total"
        assert found.entry_price > found.metadata["lower_band"] * 0.99
