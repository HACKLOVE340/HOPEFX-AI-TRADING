# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_smc_ict_components.py
======================================
Smart Money Concepts, component by component.

Coverage-floor programme, Task 6c. `strategies/smc_ict.py` was recorded at
75.57%: the `analyze` orchestration and the two scoring paths were exercised,
and every one of the six components they call was not — `_analyze_market_structure`
(BOS and CHoCH in all three trends), `_identify_order_blocks`,
`_identify_fair_value_gaps`, `_analyze_liquidity`, `_calculate_premium_discount`
and `_calculate_ote_levels`.

That distribution is the risk worth naming. `generate_signal` adds five
weighted booleans and fires at 0.5, so a component that silently returns its
empty fallback does not raise and does not change the shape of anything — it
just contributes 0 forever, and the strategy quietly needs a higher bar from
the remaining four. Each of the six wraps its body in
`except Exception: return <empty>`, so any internal error produces exactly that.
The tests below therefore assert what each component *finds*, not merely that it
returns.

The `backtesting-frameworks` sweep is clean: every component reads a trailing
slice (`prices[-N:]`) or walks forward with `prices[i - 2]`, and nothing looks
past the bar it is classifying.
"""

from __future__ import annotations

from typing import Any

import pytest

from strategies.base import SignalType, StrategyConfig
from strategies.smc_ict import SMCICTStrategy


def _bar(open_: float, high: float, low: float, close: float, volume: float = 1000.0) -> dict[str, Any]:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _flat(n: int, price: float = 2000.0, spread: float = 1.0) -> list[dict[str, Any]]:
    return [_bar(price, price + spread, price - spread, price) for _ in range(n)]


def _ramp(n: int, start: float, end: float, spread: float = 1.0) -> list[dict[str, Any]]:
    step = (end - start) / max(n - 1, 1)
    bars = []
    for i in range(n):
        close = start + step * i
        bars.append(_bar(close - step / 2, close + spread, close - spread, close))
    return bars


def _zigzag(
    legs: int,
    start: float,
    leg_up: float,
    leg_down: float,
    bars_per_leg: int = 6,
    spread: float = 3.0,
) -> list[dict[str, Any]]:
    """A market with actual swing pivots.

    `_analyze_market_structure` finds a swing high by comparing a bar against
    `pivot_n` neighbours on each side, so a monotonic ramp has **no pivots at
    all** and classifies as neutral — which is what the first draft of these
    tests discovered by asserting "bullish" over a straight line and failing.
    A trend the component can see is a staircase, not a slope.
    """
    bars: list[dict[str, Any]] = []
    price = start
    for leg in range(legs):
        step = (leg_up if leg % 2 == 0 else -leg_down) / bars_per_leg
        for _ in range(bars_per_leg):
            price += step
            bars.append(_bar(price, price + spread, price - spread, price))
    return bars


@pytest.fixture
def smc() -> SMCICTStrategy:
    return SMCICTStrategy(StrategyConfig(name="smc", symbol="XAUUSD", timeframe="1h"))


# ─────────────────────────────────────────────────────────────────────────────
# analyze()
# ─────────────────────────────────────────────────────────────────────────────


class TestTheOrchestration:
    def test_too_little_history_is_refused_by_name(self, smc):
        assert smc.analyze({"prices": _flat(10)}) == {"error": "Insufficient data"}

    def test_no_prices_at_all_is_refused(self, smc):
        assert smc.analyze({})["error"] == "Insufficient data"

    def test_a_full_analysis_carries_all_six_components(self, smc):
        out = smc.analyze({"prices": _ramp(80, 1900.0, 2100.0)})
        assert "error" not in out
        for key in (
            "market_structure",
            "order_blocks",
            "fair_value_gaps",
            "liquidity_zones",
            "premium_discount",
            "ote_levels",
        ):
            assert key in out, f"{key} missing from the analysis"
        assert out["current_price"] == pytest.approx(2100.0)
        assert out["timestamp"].tzinfo is not None

    def test_a_malformed_bar_produces_an_empty_analysis_and_no_error_key(self, smc, caplog):
        """Measured, and not what the first draft of this test assumed.

        `analyze`'s own `except` is never reached: each of the six components
        swallows its exception and returns its empty fallback, so `analyze`
        completes and returns a **full-shaped analysis with nothing in it** —
        no `error` key, `high` and `low` defaulted to 0, every list empty.

        The outcome is safe: `generate_signal` scores empty components, reaches
        0, and returns None. The *report* is the problem — an analysis built
        from six failed components is indistinguishable from one taken of a
        quiet market. What makes this liveable is the log level: each component
        logs its failure at ERROR, not DEBUG, so the evidence exists where
        someone will see it.
        """
        import logging

        bars = _flat(60)
        bars[-1] = {"close": 2000.0}  # no high/low/open
        with caplog.at_level(logging.DEBUG, logger="strategies.smc_ict"):
            out = smc.analyze({"prices": bars})

        assert "error" not in out
        assert out["high"] == 0
        assert out["order_blocks"] == {"bullish": [], "bearish": []}
        assert out["market_structure"]["trend"] == "neutral"

        # Filtered by LOGGER, not by message text. `caplog.records` holds every
        # record the root handler saw, not only the logger named in
        # `at_level`, so `"Error" in message` also matched anything else that
        # happened to log during `analyze`. In the full suite that was
        #
        #   urllib3.connectionpool WARNING Retrying (...) after connection
        #   broken by 'OSError('Tunnel connection failed: 403 Forbidden')'
        #
        # — Sentry's envelope upload retrying through the sandbox proxy — whose
        # message contains "OSError". The test then reported "a failed
        # component logged at ['ERROR', 'WARNING']" and was red for a reason
        # that had nothing to do with the strategy. It passed when run alone,
        # which is the shape that gets a real failure dismissed as a flake.
        failures = [r for r in caplog.records if r.name == "strategies.smc_ict" and "Error" in r.getMessage()]
        assert failures, "six components failed and none of them said so"
        assert all(r.levelno >= logging.ERROR for r in failures), (
            f"a failed component logged at {sorted({r.levelname for r in failures})}"
        )

        # And the safe outcome, which is the part that matters at runtime.
        assert smc.generate_signal(out) is None


# ─────────────────────────────────────────────────────────────────────────────
# _analyze_market_structure
# ─────────────────────────────────────────────────────────────────────────────


class TestMarketStructure:
    def test_a_staircase_of_higher_highs_and_higher_lows_is_bullish(self, smc):
        structure = smc._analyze_market_structure(_zigzag(10, 1900.0, 60.0, 30.0))
        assert structure["trend"] == "bullish"
        assert structure["type"] == "higher_highs_higher_lows"
        assert structure["last_sh"] is not None
        assert 0.0 <= structure["strength"] <= 1.0

    def test_a_staircase_of_lower_highs_and_lower_lows_is_bearish(self, smc):
        structure = smc._analyze_market_structure(_zigzag(10, 2100.0, 30.0, 60.0))
        assert structure["trend"] == "bearish"
        assert structure["type"] == "lower_highs_lower_lows"

    def test_a_flat_market_has_no_pivots_and_falls_back_to_neutral(self, smc):
        structure = smc._analyze_market_structure(_flat(60))
        assert structure["trend"] == "neutral"
        assert structure["bos"] is False
        assert structure["choch"] is False

    def test_a_bullish_break_above_the_last_swing_high_is_a_bos(self, smc):
        bars = _zigzag(10, 1900.0, 60.0, 30.0)
        bars.append(_bar(2100.0, 2400.0, 2099.0, 2380.0))
        structure = smc._analyze_market_structure(bars)
        if structure["trend"] == "bullish":
            assert structure["bos"] is True
            assert structure["event"] == "BOS_bullish"

    def test_a_bullish_trend_breaking_below_its_last_swing_low_is_a_choch(self, smc):
        bars = _zigzag(10, 1900.0, 60.0, 30.0)
        bars.append(_bar(2100.0, 2101.0, 1500.0, 1520.0))
        structure = smc._analyze_market_structure(bars)
        if structure["trend"] == "bullish":
            assert structure["choch"] is True
            assert structure["event"] == "CHoCH_bearish"

    def test_a_bearish_break_below_the_last_swing_low_is_a_bos(self, smc):
        bars = _zigzag(10, 2100.0, 30.0, 60.0)
        bars.append(_bar(1900.0, 1901.0, 1500.0, 1520.0))
        structure = smc._analyze_market_structure(bars)
        if structure["trend"] == "bearish":
            assert structure["bos"] is True
            assert structure["event"] == "BOS_bearish"

    def test_a_bearish_trend_breaking_above_its_last_swing_high_is_a_choch(self, smc):
        bars = _zigzag(10, 2100.0, 30.0, 60.0)
        bars.append(_bar(1900.0, 2400.0, 1899.0, 2380.0))
        structure = smc._analyze_market_structure(bars)
        if structure["trend"] == "bearish":
            assert structure["choch"] is True
            assert structure["event"] == "CHoCH_bullish"

    def test_a_malformed_window_returns_the_neutral_fallback_rather_than_raising(self, smc):
        """The fallback is what a scoring path sees when this component fails,
        and `trend: neutral` matches neither the bullish nor the bearish branch
        — so the whole signal quietly becomes HOLD."""
        structure = smc._analyze_market_structure([{"close": 2000.0}] * 60)
        assert structure == {
            "trend": "neutral",
            "type": "unknown",
            "strength": 0.0,
            "bos": False,
            "choch": False,
            "event": "none",
            "last_sh": None,
            "last_sl": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# The five remaining components
# ─────────────────────────────────────────────────────────────────────────────


class TestOrderBlocks:
    def test_a_down_candle_followed_by_a_break_above_its_high_is_a_bullish_block(self, smc):
        bars = _flat(30)
        bars[-3] = _bar(2000.0, 2001.0, 1990.0, 1992.0)  # down candle
        bars[-2] = _bar(1992.0, 2020.0, 1991.0, 2015.0)  # up candle closing above its high
        blocks = smc._identify_order_blocks(bars)
        assert 1990.0 in blocks["bullish"], "the down candle's low is the block"

    def test_an_up_candle_followed_by_a_break_below_its_low_is_a_bearish_block(self, smc):
        bars = _flat(30)
        bars[-3] = _bar(2000.0, 2010.0, 1999.0, 2008.0)  # up candle
        bars[-2] = _bar(2008.0, 2009.0, 1980.0, 1985.0)  # down candle closing below its low
        blocks = smc._identify_order_blocks(bars)
        assert 2010.0 in blocks["bearish"], "the up candle's high is the block"

    def test_a_quiet_market_has_no_blocks(self, smc):
        assert smc._identify_order_blocks(_flat(30)) == {"bullish": [], "bearish": []}

    def test_only_the_last_five_are_kept(self, smc):
        bars = []
        for _ in range(12):
            bars.append(_bar(2000.0, 2001.0, 1990.0, 1992.0))
            bars.append(_bar(1992.0, 2020.0, 1991.0, 2015.0))
        bars.append(_bar(2015.0, 2016.0, 2014.0, 2015.0))
        assert len(smc._identify_order_blocks(bars)["bullish"]) <= 5

    def test_a_malformed_bar_leaves_the_lists_empty_rather_than_raising(self, smc):
        assert smc._identify_order_blocks([{"close": 1.0}] * 30) == {"bullish": [], "bearish": []}


class TestFairValueGaps:
    def test_a_gap_up_between_two_bars_apart_is_bullish(self, smc):
        bars = [
            _bar(2000.0, 2005.0, 1995.0, 2002.0),
            _bar(2002.0, 2050.0, 2001.0, 2045.0),
            _bar(2045.0, 2060.0, 2040.0, 2055.0),  # low 2040 > bar[0] high 2005
        ]
        gaps = smc._identify_fair_value_gaps(bars)
        assert len(gaps["bullish"]) == 1
        assert gaps["bullish"][0] == {"top": 2040.0, "bottom": 2005.0, "size": pytest.approx((2040 - 2005) / 2005)}

    def test_a_gap_down_between_two_bars_apart_is_bearish(self, smc):
        bars = [
            _bar(2100.0, 2105.0, 2095.0, 2098.0),
            _bar(2098.0, 2099.0, 2050.0, 2055.0),
            _bar(2055.0, 2060.0, 2040.0, 2045.0),  # high 2060 < bar[0] low 2095
        ]
        gaps = smc._identify_fair_value_gaps(bars)
        assert len(gaps["bearish"]) == 1
        assert gaps["bearish"][0]["top"] == 2095.0
        assert gaps["bearish"][0]["bottom"] == 2060.0

    def test_a_gap_smaller_than_the_minimum_is_not_a_gap(self, smc):
        """`fvg_min_gap` defaults to 0.1%. A one-tick imbalance is noise."""
        bars = [
            _bar(2000.0, 2005.0, 1995.0, 2002.0),
            _bar(2002.0, 2006.0, 2001.0, 2005.0),
            _bar(2005.0, 2008.0, 2005.5, 2006.0),  # 0.5 above 2005 = 0.025%
        ]
        assert smc._identify_fair_value_gaps(bars) == {"bullish": [], "bearish": []}

    def test_a_market_that_trades_through_every_level_has_no_gaps(self, smc):
        """Overlapping bars, not merely a rising market.

        The first draft asserted this of `_ramp(40, 1900, 2100)` and failed: a
        200-point ramp over 40 bars steps ~5 points a bar against a 1-point
        spread, so bar *i*'s low really is above bar *i-2*'s high — those are
        genuine gaps, and the fixture was wrong rather than the component. A
        continuous market is one where consecutive ranges overlap.
        """
        bars = [_bar(2000.0 + i, 2000.0 + i + 20.0, 2000.0 + i - 20.0, 2000.0 + i) for i in range(40)]
        assert smc._identify_fair_value_gaps(bars) == {"bullish": [], "bearish": []}

    def test_a_fast_ramp_does_gap_and_the_component_finds_it(self, smc):
        gaps = smc._identify_fair_value_gaps(_ramp(40, 1900.0, 2100.0))
        assert gaps["bullish"], "a 5-point-a-bar ramp against a 1-point spread leaves imbalances"
        assert all(g["top"] > g["bottom"] for g in gaps["bullish"])

    def test_only_the_last_three_are_kept(self, smc):
        bars = []
        price = 2000.0
        for _ in range(10):
            bars.append(_bar(price, price + 1, price - 1, price))
            price += 50
            bars.append(_bar(price, price + 1, price - 1, price))
            price += 50
        assert len(smc._identify_fair_value_gaps(bars)["bullish"]) <= 3

    def test_a_malformed_bar_leaves_the_lists_empty(self, smc):
        assert smc._identify_fair_value_gaps([{"close": 1.0}] * 10) == {"bullish": [], "bearish": []}


class TestLiquidity:
    def test_a_new_high_sweeps_the_liquidity_above(self, smc):
        bars = _flat(30)
        bars[-1] = _bar(2000.0, 2050.0, 1999.0, 2040.0)
        zones = smc._analyze_liquidity(bars)
        assert zones["swept_above"] is True
        assert zones["swept_below"] is False
        assert zones["liquidity_level_high"] == 2001.0

    def test_a_new_low_sweeps_the_liquidity_below(self, smc):
        bars = _flat(30)
        bars[-1] = _bar(2000.0, 2001.0, 1950.0, 1960.0)
        zones = smc._analyze_liquidity(bars)
        assert zones["swept_below"] is True
        assert zones["swept_above"] is False
        assert zones["liquidity_level_low"] == 1999.0

    def test_a_bar_inside_the_range_sweeps_nothing(self, smc):
        zones = smc._analyze_liquidity(_flat(30))
        assert zones["swept_above"] is False
        assert zones["swept_below"] is False

    def test_a_single_bar_cannot_sweep_itself(self, smc):
        """`max(recent_highs[:-1])` on one bar is `max([])`, which raises into
        the fallback. The fallback is the right answer — one bar has nothing to
        sweep — but it arrives without the two level keys, which is why every
        caller reads them with `.get`."""
        zones = smc._analyze_liquidity(_flat(1))
        assert zones == {"swept_above": False, "swept_below": False}


class TestPremiumAndDiscount:
    def test_the_top_of_the_range_is_premium(self, smc):
        bars = _ramp(60, 1900.0, 2100.0)
        zone = smc._calculate_premium_discount(bars)
        assert zone["zone"] == "premium"
        assert 0.0 <= zone["level"] <= 1.0
        assert zone["range_low"] < zone["mid_point"] < zone["range_high"]

    def test_the_bottom_of_the_range_is_discount(self, smc):
        bars = _ramp(60, 2100.0, 1900.0)
        assert smc._calculate_premium_discount(bars)["zone"] == "discount"

    def test_the_level_is_capped_at_one(self, smc):
        bars = _ramp(60, 1900.0, 2100.0)
        assert smc._calculate_premium_discount(bars)["level"] <= 1.0

    def test_a_flat_range_divides_by_zero_and_falls_back_to_neutral(self, smc):
        """Neither `"premium"` nor `"discount"`, so neither scoring path adds
        its 0.2 — which is the correct outcome for a market with no range, and
        is reached through an exception rather than a branch."""
        assert smc._calculate_premium_discount(_flat(60, spread=0.0)) == {"zone": "neutral", "level": 0}


class TestOptimalTradeEntry:
    def test_a_bullish_structure_retraces_down_from_the_high(self, smc):
        bars = _ramp(60, 1900.0, 2100.0)
        levels = smc._calculate_ote_levels(bars, {"trend": "bullish"})
        assert len(levels["bullish"]) == len(smc.ote_fibonacci)
        assert levels["bearish"] == []
        assert levels["bullish"] == sorted(levels["bullish"], reverse=True), "deeper fib, lower level"

    def test_a_bearish_structure_retraces_up_from_the_low(self, smc):
        bars = _ramp(60, 2100.0, 1900.0)
        levels = smc._calculate_ote_levels(bars, {"trend": "bearish"})
        assert len(levels["bearish"]) == len(smc.ote_fibonacci)
        assert levels["bullish"] == []
        assert levels["bearish"] == sorted(levels["bearish"])

    def test_a_neutral_structure_has_no_entry_levels(self, smc):
        assert smc._calculate_ote_levels(_ramp(60, 1900.0, 2100.0), {"trend": "neutral"}) == {
            "bullish": [],
            "bearish": [],
        }

    def test_a_malformed_window_returns_empty_levels(self, smc):
        assert smc._calculate_ote_levels([{"close": 1.0}], {"trend": "bullish"}) == {"bullish": [], "bearish": []}


class TestTheTwoPredicates:
    def test_a_price_within_a_tenth_of_a_percent_is_near_the_level(self, smc):
        assert smc._price_near_level(2000.0, [2001.0]) is True
        assert smc._price_near_level(2000.0, [2050.0]) is False

    def test_an_empty_level_list_is_never_near(self, smc):
        assert smc._price_near_level(2000.0, []) is False

    def test_a_zero_level_is_skipped_rather_than_dividing_by_it(self, smc):
        assert smc._price_near_level(2000.0, [0.0]) is False
        assert smc._price_near_level(2000.0, [0.0, 2000.5]) is True

    def test_the_threshold_can_be_widened(self, smc):
        assert smc._price_near_level(2000.0, [2050.0], threshold=0.05) is True

    def test_a_price_inside_a_gap_is_in_it_and_the_edges_count(self, smc):
        gap = [{"bottom": 1990.0, "top": 2010.0}]
        assert smc._price_in_fvg(2000.0, gap) is True
        assert smc._price_in_fvg(1990.0, gap) is True
        assert smc._price_in_fvg(2010.0, gap) is True
        assert smc._price_in_fvg(2011.0, gap) is False

    def test_no_gaps_means_never_inside_one(self, smc):
        assert smc._price_in_fvg(2000.0, []) is False


# ─────────────────────────────────────────────────────────────────────────────
# generate_signal — the scoring
# ─────────────────────────────────────────────────────────────────────────────


def _analysis(trend: str, **overrides: Any) -> dict[str, Any]:
    """A complete analysis dict with every component contributing nothing.

    Tests switch on individual components so the score is stated rather than
    produced by a price fixture that may or may not land on the setup.
    """
    from datetime import datetime, timezone

    base: dict[str, Any] = {
        "current_price": 2000.0,
        "high": 2001.0,
        "low": 1999.0,
        "volume": 1000.0,
        "market_structure": {"trend": trend, "type": "higher_highs_higher_lows"},
        "order_blocks": {"bullish": [], "bearish": []},
        "fair_value_gaps": {"bullish": [], "bearish": []},
        "liquidity_zones": {"swept_above": False, "swept_below": False},
        "premium_discount": {"zone": "neutral", "level": 0},
        "ote_levels": {"bullish": [], "bearish": []},
        "timestamp": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


class TestTheScoring:
    def test_an_analysis_carrying_an_error_produces_nothing(self, smc):
        assert smc.generate_signal({"error": "Insufficient data"}) is None

    def test_a_neutral_structure_matches_neither_path(self, smc):
        assert smc.generate_signal(_analysis("neutral")) is None

    def test_a_bullish_structure_with_no_confluence_is_not_enough(self, smc):
        assert smc.generate_signal(_analysis("bullish")) is None

    def test_one_component_alone_does_not_reach_the_half_needed(self, smc):
        """0.25 for an order block, and the bar is 0.5. The strategy refuses a
        setup that only one thing agrees with."""
        signal = smc.generate_signal(_analysis("bullish", order_blocks={"bullish": [2000.0], "bearish": []}))
        assert signal is None

    def test_an_order_block_and_a_gap_together_reach_it(self, smc):
        signal = smc.generate_signal(
            _analysis(
                "bullish",
                order_blocks={"bullish": [2000.0], "bearish": []},
                fair_value_gaps={"bullish": [{"bottom": 1990.0, "top": 2010.0}], "bearish": []},
            )
        )
        assert signal is not None
        assert signal.signal_type is SignalType.BUY
        assert signal.confidence == pytest.approx(0.5)
        assert signal.metadata["reason"] == "SMC Bullish Setup"
        assert signal.price == 2000.0

    def test_every_bullish_component_together_is_capped_at_one(self, smc):
        signal = smc.generate_signal(
            _analysis(
                "bullish",
                order_blocks={"bullish": [2000.0], "bearish": []},
                fair_value_gaps={"bullish": [{"bottom": 1990.0, "top": 2010.0}], "bearish": []},
                premium_discount={"zone": "discount", "level": 0.5},
                ote_levels={"bullish": [2000.0], "bearish": []},
                liquidity_zones={"swept_above": False, "swept_below": True},
            )
        )
        assert signal is not None
        assert signal.confidence == pytest.approx(1.0)
        assert signal.metadata["discount_zone"] is True
        assert signal.metadata["ote_level"] is True

    def test_the_bearish_path_scores_the_mirror_components(self, smc):
        signal = smc.generate_signal(
            _analysis(
                "bearish",
                order_blocks={"bullish": [], "bearish": [2000.0]},
                fair_value_gaps={"bullish": [], "bearish": [{"bottom": 1990.0, "top": 2010.0}]},
                premium_discount={"zone": "premium", "level": 0.5},
                ote_levels={"bullish": [], "bearish": [2000.0]},
                liquidity_zones={"swept_above": True, "swept_below": False},
            )
        )
        assert signal is not None
        assert signal.signal_type is SignalType.SELL
        assert signal.confidence == pytest.approx(1.0)
        assert signal.metadata["reason"] == "SMC Bearish Setup"
        assert signal.metadata["premium_zone"] is True

    def test_a_bullish_setup_does_not_score_bearish_components(self, smc):
        """The lists are keyed by direction, and a bullish path that read the
        bearish lists would fire on the wrong side of every setup."""
        assert (
            smc.generate_signal(
                _analysis(
                    "bullish",
                    order_blocks={"bullish": [], "bearish": [2000.0]},
                    fair_value_gaps={"bullish": [], "bearish": [{"bottom": 1990.0, "top": 2010.0}]},
                    premium_discount={"zone": "premium", "level": 0.5},
                    ote_levels={"bullish": [], "bearish": [2000.0]},
                    liquidity_zones={"swept_above": True, "swept_below": False},
                )
            )
            is None
        )

    def test_the_liquidity_sweep_alone_is_the_smallest_weight(self, smc):
        """0.1 — it confirms, it does not carry a setup."""
        assert (
            smc.generate_signal(_analysis("bullish", liquidity_zones={"swept_above": False, "swept_below": True}))
            is None
        )

    def test_a_broken_analysis_produces_nothing_rather_than_raising(self, smc):
        assert smc.generate_signal({"current_price": 2000.0}) is None


class TestTheLogAssertionReadsTheRightLogger:
    """The test above was order-dependent, and this is why it no longer is.

    `caplog.records` is everything the root handler saw during the block, not
    only the logger passed to `caplog.at_level`. Filtering the failures by the
    substring "Error" therefore picked up any other library that logged during
    `analyze` — in the full suite, `urllib3.connectionpool` warning that
    Sentry's envelope upload was "broken by 'OSError(...)'". The assertion then
    failed with "a failed component logged at ['ERROR', 'WARNING']", naming a
    component that had done nothing wrong.

    It passed when the file was run alone, which is exactly the shape that gets
    a genuine failure waved away as a flake.
    """

    def test_a_foreign_warning_does_not_become_a_component_failure(self, smc, caplog):
        import logging

        bars = _flat(60)
        bars[-1] = {"close": 2000.0}
        with caplog.at_level(logging.DEBUG, logger="strategies.smc_ict"):
            smc.analyze({"prices": bars})
            # Exactly what leaked in the full suite, reproduced deterministically.
            logging.getLogger("urllib3.connectionpool").warning(
                "Retrying (...) after connection broken by 'OSError(\"Tunnel connection "
                "failed: 403 Forbidden\")': /api/0/envelope/"
            )

        smc_failures = [r for r in caplog.records if r.name == "strategies.smc_ict" and "Error" in r.getMessage()]
        assert smc_failures, "the strategy's own failures were filtered away too"
        assert all(r.levelno >= logging.ERROR for r in smc_failures)

        # And prove the foreign record really was captured, so this test is not
        # passing because nothing was there to exclude.
        assert any(r.name == "urllib3.connectionpool" for r in caplog.records)
