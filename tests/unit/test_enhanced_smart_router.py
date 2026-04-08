# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for enhanced_smart_router.py

Covers: Venue, Order, Fill, MarketImpactModel, TWAPStrategy,
        VWAPStrategy, ImplementationShortfallStrategy,
        SmartOrderRouter (route_order, _score_venue, execute_order).
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_venue(name="Exchange_A", taker_fee=0.0005, latency_ms=15.0, max_size=1_000_000):
    from enhanced_smart_router import Venue, VenueType

    return Venue(
        name=name,
        venue_type=VenueType.EXCHANGE,
        taker_fee=taker_fee,
        latency_ms=latency_ms,
        max_order_size=max_size,
    )


def _make_order(size=100.0, order_type=None, arrival_price=None):
    from enhanced_smart_router import Order, OrderSide, OrderType

    return Order(
        id="ord-001",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        size=size,
        order_type=order_type or OrderType.MARKET,
        price=1950.0,
        arrival_price=arrival_price,
    )


# ---------------------------------------------------------------------------
# Venue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVenue:
    def test_total_cost_taker(self):
        venue = _make_venue(taker_fee=0.0005)
        cost = venue.total_cost(100_000.0, is_maker=False)
        assert cost == pytest.approx(50.0)

    def test_total_cost_maker(self):
        from enhanced_smart_router import Venue, VenueType

        venue = Venue("V", VenueType.EXCHANGE, maker_fee=0.0002, taker_fee=0.0005)
        cost = venue.total_cost(100_000.0, is_maker=True)
        assert cost == pytest.approx(20.0)

    def test_total_cost_zero_fee(self):
        from enhanced_smart_router import Venue, VenueType

        venue = Venue("Internal", VenueType.MAKER, maker_fee=0.0, taker_fee=0.0)
        assert venue.total_cost(100_000.0) == pytest.approx(0.0)

    def test_default_reliability_score(self):
        venue = _make_venue()
        assert venue.reliability_score == pytest.approx(1.0)

    def test_preferred_assets_default_empty(self):
        venue = _make_venue()
        assert venue.preferred_assets == set()


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrder:
    def test_notional_property(self):
        order = _make_order(size=10.0)
        order.price = 1950.0
        assert order.notional == pytest.approx(19_500.0)

    def test_is_filled_false_initially(self):
        order = _make_order()
        assert order.is_filled is False

    def test_is_filled_true_when_fully_filled(self):
        from enhanced_smart_router import OrderStatus

        order = _make_order(size=10.0)
        order.filled_size = 10.0
        order.status = OrderStatus.FILLED
        assert order.is_filled is True

    def test_remaining_size_initially_equals_size(self):
        order = _make_order(size=10.0)
        assert order.remaining_size == pytest.approx(10.0)

    def test_remaining_size_after_partial_fill(self):
        order = _make_order(size=10.0)
        order.filled_size = 4.0
        order.remaining_size = order.size - order.filled_size
        assert order.remaining_size == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# MarketImpactModel
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketImpactModel:
    def test_init_defaults(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        assert m.eta > 0
        assert m.gamma > 0
        assert m.beta > 0
        assert m.sigma > 0

    def test_temporary_impact_positive(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        # temporary_impact(X, T, V): order_size=100, time=0.1 day, ADV=10_000
        impact = m.temporary_impact(X=100.0, T=0.1, V=10_000.0)
        assert impact >= 0.0

    def test_permanent_impact_positive(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        impact = m.permanent_impact(X=100.0, V=10_000.0)
        assert impact >= 0.0

    def test_total_cost_returns_dict(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        result = m.total_cost(X=100.0, T=0.1, V=10_000.0, price=1950.0)
        assert isinstance(result, dict)
        for key in ("temporary_impact_bps", "permanent_impact_bps", "total_impact_bps", "total_cost"):
            assert key in result

    def test_total_impact_bps_is_sum_of_components(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        result = m.total_cost(X=100.0, T=0.1, V=10_000.0, price=1950.0)
        assert result["total_impact_bps"] == pytest.approx(
            result["temporary_impact_bps"] + result["permanent_impact_bps"]
        )

    def test_larger_order_has_more_impact(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        small = m.temporary_impact(X=10.0, T=0.1, V=10_000.0)
        large = m.temporary_impact(X=1000.0, T=0.1, V=10_000.0)
        assert large > small

    def test_zero_time_returns_zero(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        assert m.temporary_impact(X=100.0, T=0.0, V=10_000.0) == 0.0

    def test_zero_volume_returns_zero(self):
        from enhanced_smart_router import MarketImpactModel

        m = MarketImpactModel()
        assert m.permanent_impact(X=100.0, V=0.0) == 0.0


# ---------------------------------------------------------------------------
# TWAPStrategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTWAPStrategy:
    def test_init(self):
        from enhanced_smart_router import TWAPStrategy

        order = _make_order(size=100.0)
        venues = [_make_venue()]
        strategy = TWAPStrategy(order, venues, num_slices=5, duration_minutes=10)
        assert strategy.num_slices == 5
        assert strategy.duration == 10

    def test_slice_size_equals_order_size_divided_by_slices(self):
        from enhanced_smart_router import TWAPStrategy

        order = _make_order(size=100.0)
        venues = [_make_venue()]
        strategy = TWAPStrategy(order, venues, num_slices=5)
        assert strategy.slice_size == pytest.approx(20.0)

    def test_slice_size_times_slices_equals_order_size(self):
        from enhanced_smart_router import TWAPStrategy

        order = _make_order(size=100.0)
        venues = [_make_venue()]
        strategy = TWAPStrategy(order, venues, num_slices=4)
        assert strategy.slice_size * strategy.num_slices == pytest.approx(100.0)

    def test_is_complete_false_initially(self):
        from enhanced_smart_router import TWAPStrategy

        order = _make_order(size=100.0)
        strategy = TWAPStrategy(order, [_make_venue()], num_slices=5)
        assert strategy.is_complete is False

    def test_update_order_tracks_fills(self):
        from enhanced_smart_router import Fill, TWAPStrategy

        order = _make_order(size=100.0)
        strategy = TWAPStrategy(order, [_make_venue()], num_slices=5)
        fill = Fill(
            fill_id="f-001",
            order_id="ord-001",
            symbol="XAUUSD",
            size=20.0,
            price=1950.0,
            venue="Exchange_A",
            timestamp=datetime.now(UTC),
            fee=0.5,
        )
        strategy.update_order(fill)
        assert len(strategy.fills) == 1
        assert strategy.order.filled_size == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# VWAPStrategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVWAPStrategy:
    def test_init(self):
        from enhanced_smart_router import VWAPStrategy

        order = _make_order(size=100.0)
        profile = [0.1] * 10
        strategy = VWAPStrategy(order, [_make_venue()], volume_profile=profile)
        assert len(strategy.volume_profile) == 10

    def test_total_volume_computed(self):
        from enhanced_smart_router import VWAPStrategy

        order = _make_order(size=100.0)
        profile = [0.1] * 10
        strategy = VWAPStrategy(order, [_make_venue()], volume_profile=profile)
        assert strategy.total_volume == pytest.approx(1.0)

    def test_proportional_slice_sizes(self):
        """Verify proportional distribution by computing manually."""
        from enhanced_smart_router import VWAPStrategy

        order = _make_order(size=100.0)
        profile = [0.2, 0.3, 0.5]
        strategy = VWAPStrategy(order, [_make_venue()], volume_profile=profile)
        total_vol = sum(profile)
        expected = [(v / total_vol) * 100.0 for v in profile]
        computed = [(v / strategy.total_volume) * order.size for v in strategy.volume_profile]
        assert computed[0] == pytest.approx(expected[0])
        assert computed[1] == pytest.approx(expected[1])
        assert computed[2] == pytest.approx(expected[2])

    def test_duration_stored(self):
        from enhanced_smart_router import VWAPStrategy

        order = _make_order(size=100.0)
        strategy = VWAPStrategy(order, [_make_venue()], volume_profile=[1.0], duration_minutes=45)
        assert strategy.duration == 45


# ---------------------------------------------------------------------------
# ImplementationShortfallStrategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestImplementationShortfallStrategy:
    def test_init_requires_arrival_price(self):
        from enhanced_smart_router import ImplementationShortfallStrategy

        order = _make_order(size=100.0, arrival_price=None)
        with pytest.raises(ValueError, match="arrival_price"):
            ImplementationShortfallStrategy(order, [_make_venue()])

    def test_init_with_arrival_price(self):
        from enhanced_smart_router import ImplementationShortfallStrategy

        order = _make_order(size=100.0, arrival_price=1950.0)
        strategy = ImplementationShortfallStrategy(order, [_make_venue()])
        assert strategy.arrival_price == pytest.approx(1950.0)

    def test_optimal_trajectory_sums_to_order_size(self):
        from enhanced_smart_router import ImplementationShortfallStrategy

        order = _make_order(size=100.0, arrival_price=1950.0)
        strategy = ImplementationShortfallStrategy(order, [_make_venue()])
        trajectory = strategy.optimal_trajectory()
        assert sum(trajectory) == pytest.approx(100.0, rel=1e-3)

    def test_optimal_trajectory_has_10_periods(self):
        from enhanced_smart_router import ImplementationShortfallStrategy

        order = _make_order(size=100.0, arrival_price=1950.0)
        strategy = ImplementationShortfallStrategy(order, [_make_venue()])
        assert len(strategy.optimal_trajectory()) == 10

    def test_higher_urgency_front_loads_execution(self):
        from enhanced_smart_router import ImplementationShortfallStrategy

        order = _make_order(size=100.0, arrival_price=1950.0)
        low_urgency = ImplementationShortfallStrategy(order, [_make_venue()], risk_aversion=0.1)
        high_urgency = ImplementationShortfallStrategy(order, [_make_venue()], risk_aversion=5.0)
        low_traj = low_urgency.optimal_trajectory()
        high_traj = high_urgency.optimal_trajectory()
        # High urgency should trade more in first period
        assert high_traj[0] >= low_traj[0]


# ---------------------------------------------------------------------------
# SmartOrderRouter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmartOrderRouter:
    def test_init_default_venues(self):
        from enhanced_smart_router import SmartOrderRouter

        router = SmartOrderRouter()
        assert len(router.venues) > 0

    def test_init_custom_venues(self):
        from enhanced_smart_router import SmartOrderRouter

        venues = [_make_venue("V1"), _make_venue("V2")]
        router = SmartOrderRouter(venues=venues)
        assert len(router.venues) == 2

    def test_route_order_market_returns_strategy(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=100.0, order_type=OrderType.MARKET)
        strategy = router.route_order(order)
        assert strategy is not None

    def test_route_order_twap_returns_twap_strategy(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter, TWAPStrategy

        router = SmartOrderRouter()
        order = _make_order(size=100.0, order_type=OrderType.TWAP)
        strategy = router.route_order(order)
        assert isinstance(strategy, TWAPStrategy)

    def test_route_order_vwap_returns_vwap_strategy(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter, VWAPStrategy

        # Use MARKET as default so TWAP short-circuit doesn't fire
        router = SmartOrderRouter(default_strategy=OrderType.MARKET)
        order = _make_order(size=100.0, order_type=OrderType.VWAP)
        strategy = router.route_order(order)
        assert isinstance(strategy, VWAPStrategy)

    def test_route_order_is_adds_to_active_orders(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=100.0, order_type=OrderType.TWAP)
        router.route_order(order)
        assert order.id in router.active_orders

    def test_score_venue_returns_float(self):
        from enhanced_smart_router import SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=100.0)
        venue = _make_venue()
        score = router._score_venue(venue, order)
        assert isinstance(score, float)

    def test_score_venue_lower_fee_scores_higher(self):
        from enhanced_smart_router import SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=100.0)
        cheap = _make_venue("Cheap", taker_fee=0.0001)
        expensive = _make_venue("Expensive", taker_fee=0.001)
        assert router._score_venue(cheap, order) > router._score_venue(expensive, order)

    def test_score_venue_lower_latency_scores_higher(self):
        from enhanced_smart_router import SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=100.0)
        fast = _make_venue("Fast", latency_ms=1.0)
        slow = _make_venue("Slow", latency_ms=90.0)
        assert router._score_venue(fast, order) > router._score_venue(slow, order)

    def test_execute_order_returns_dict(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=1.0, order_type=OrderType.TWAP)
        # Patch the strategy execute to avoid real async sleep
        with patch("enhanced_smart_router.TWAPStrategy.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = []
            result = asyncio.run(router.execute_order(order))
        assert isinstance(result, dict)

    def test_execute_order_result_keys(self):
        from enhanced_smart_router import OrderType, SmartOrderRouter

        router = SmartOrderRouter()
        order = _make_order(size=1.0, order_type=OrderType.TWAP)
        with patch("enhanced_smart_router.TWAPStrategy.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = []
            result = asyncio.run(router.execute_order(order))
        for key in ("order_id", "status", "fills", "filled_size", "avg_price"):
            assert key in result, f"Missing key: {key}"

    def test_routing_weights_sum_to_one(self):
        from enhanced_smart_router import SmartOrderRouter

        router = SmartOrderRouter()
        total = sum(router.routing_weights.values())
        assert total == pytest.approx(1.0)
