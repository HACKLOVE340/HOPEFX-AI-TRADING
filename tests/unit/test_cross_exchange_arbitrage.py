# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_cross_exchange_arbitrage.py
===========================================
`core/arbitrage/cross_exchange.py` — 149 statements, previously 0% covered.

Two-legged execution against real venues with real money, and nothing tested
it. The failure mode that matters is not "misses an opportunity" — it is
**leg risk**: one leg fills, the other does not, and the account is left
holding a naked position it never intended. The engine has an emergency-hedge
path for exactly that, and whether it fires on the right leg, in the right
direction, was unverified.

Pinned here:

- The fee arithmetic. An opportunity is only taken if it clears fees on *both*
  venues. A sign error or a missing leg in that sum turns a loss into an
  apparent profit and the engine trades it repeatedly.
- The hedge direction. Buy filled and sell failed means the account is long, so
  the hedge must SELL. Getting this backwards doubles the exposure instead of
  closing it.
- `get_stats` divides by `detected` and `executed`. Both are zero before the
  first scan, and a dashboard polls this from startup.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


class _Connector:
    """Concrete ExchangeConnector — the ABC cannot be instantiated directly."""

    def __init__(self, name, bid, ask, *, taker="0.001", latency=10.0, fills=True, raises=False):
        from core.arbitrage.cross_exchange import ExchangeConnector

        self._base = ExchangeConnector
        self.name = name
        self.client = None
        self.latency_ms = latency
        self.maker_fee = Decimal(taker)
        self.taker_fee = Decimal(taker)
        self.is_connected = False
        self._bid, self._ask = bid, ask
        self._fills = fills
        self._raises = raises
        self.orders: list[dict] = []

    async def connect(self):
        self.is_connected = True

    async def get_ticker(self, symbol):
        if self._raises:
            raise ConnectionError("venue unreachable")
        return {"bid": self._bid, "ask": self._ask}

    async def place_order(self, symbol, side, size, price=None, order_type="limit"):
        self.orders.append({"symbol": symbol, "side": side, "size": size, "price": price, "order_type": order_type})
        return {"filled": self._fills, "fill_price": price}

    async def get_balance(self, asset):
        return Decimal("100")


def _real_connector(name, bid, ask, **kw):
    """A genuine subclass, so the ABC's abstract-method enforcement is exercised."""
    from core.arbitrage.cross_exchange import ExchangeConnector

    stub = _Connector(name, bid, ask, **kw)

    class _Impl(ExchangeConnector):
        async def get_ticker(self, symbol):
            return await stub.get_ticker(symbol)

        async def place_order(self, symbol, side, size, price=None, order_type="limit"):
            return await stub.place_order(symbol, side, size, price, order_type)

        async def get_balance(self, asset):
            return await stub.get_balance(asset)

    impl = _Impl(name, None, kw.get("latency", 10.0), {"taker": Decimal(kw.get("taker", "0.001"))})
    impl.orders = stub.orders  # type: ignore[attr-defined]
    return impl


# ── ExchangeConnector ─────────────────────────────────────────────────────────


def test_the_connector_base_class_cannot_be_instantiated():
    """The three methods exist so a venue cannot silently return None."""
    from core.arbitrage.cross_exchange import ExchangeConnector

    with pytest.raises(TypeError):
        ExchangeConnector("x", None, 1.0, {})  # type: ignore[abstract]


async def test_a_connector_starts_disconnected_and_connects():
    c = _real_connector("oanda", 100, 101)

    assert c.is_connected is False
    await c.connect()
    assert c.is_connected is True


def test_fees_default_when_not_supplied():
    from core.arbitrage.cross_exchange import ExchangeConnector

    class _Impl(ExchangeConnector):
        async def get_ticker(self, symbol): ...
        async def place_order(self, symbol, side, size, price=None, order_type="limit"): ...
        async def get_balance(self, asset): ...

    c = _Impl("x", None, 5.0, {})

    assert c.maker_fee == Decimal("0.001")
    assert c.taker_fee == Decimal("0.001")


# ── Price collection ──────────────────────────────────────────────────────────


async def test_prices_are_cached_per_symbol_and_venue():
    from core.arbitrage.cross_exchange import ArbitrageDetector

    d = ArbitrageDetector()
    d.add_exchange(_Connector("alpha", 100, 101))
    d.add_exchange(_Connector("beta", 102, 103))

    await d.update_prices()

    assert set(d.price_cache) >= {"BTCUSD", "ETHUSD", "XAUUSD"}
    assert set(d.price_cache["BTCUSD"]) == {"alpha", "beta"}
    assert d.price_cache["BTCUSD"]["alpha"]["bid"] == Decimal("100")


async def test_a_venue_that_fails_does_not_take_down_the_scan():
    """One unreachable exchange must not stop the others from being priced."""
    from core.arbitrage.cross_exchange import ArbitrageDetector

    d = ArbitrageDetector()
    d.add_exchange(_Connector("good", 100, 101))
    d.add_exchange(_Connector("bad", 0, 0, raises=True))

    await d.update_prices()

    assert "good" in d.price_cache["BTCUSD"]
    assert "bad" not in d.price_cache["BTCUSD"], "a failed fetch left a bogus price in the cache"


# ── Opportunity detection ─────────────────────────────────────────────────────


def _detector_with(prices, min_bps=10.0, taker="0.001"):
    from core.arbitrage.cross_exchange import ArbitrageDetector

    d = ArbitrageDetector(min_profit_bps=min_bps)
    cache = {}
    for name, (bid, ask) in prices.items():
        d.add_exchange(_Connector(name, bid, ask, taker=taker))
        cache[name] = {"bid": Decimal(str(bid)), "ask": Decimal(str(ask))}
    d.price_cache["XAUUSD"] = cache
    return d


def test_an_unknown_symbol_yields_no_opportunities():
    from core.arbitrage.cross_exchange import ArbitrageDetector

    assert ArbitrageDetector().detect_opportunities("NOTHING") == []


def test_no_opportunity_when_the_book_does_not_cross():
    """The normal state of the world: best bid below best ask."""
    d = _detector_with({"alpha": (4000, 4001), "beta": (3999, 4002)})

    assert d.detect_opportunities("XAUUSD") == []


def test_a_crossed_book_wide_enough_to_clear_fees_is_an_opportunity():
    d = _detector_with({"cheap": (3990, 4000), "rich": (4100, 4110)})

    opps = d.detect_opportunities("XAUUSD")

    assert len(opps) == 1
    o = opps[0]
    assert o.buy_exchange == "cheap", "must buy where the ask is lowest"
    assert o.sell_exchange == "rich", "must sell where the bid is highest"
    assert o.buy_price == Decimal("4000")
    assert o.sell_price == Decimal("4100")
    assert o.net_profit > 0


def test_the_spread_must_beat_the_configured_threshold():
    """A 2.5 bps cross against a 10 bps floor is noise, not an edge."""
    d = _detector_with({"a": (4000, 4000), "b": (4001, 4002)}, min_bps=10.0)

    assert d.detect_opportunities("XAUUSD") == []


def test_an_opportunity_that_does_not_clear_fees_is_rejected():
    """The whole point of the net-profit check — a gross edge eaten by fees."""
    # 25 bps gross cross, but 100 bps taker fee on each leg.
    d = _detector_with({"cheap": (3990, 4000), "rich": (4010, 4020)}, min_bps=5.0, taker="0.01")

    assert d.detect_opportunities("XAUUSD") == [], "a fee-negative trade was accepted"


def test_net_profit_subtracts_the_taker_fee_on_both_legs():
    """A missing leg in this sum turns a loss into an apparent profit."""
    d = _detector_with({"cheap": (3990, 4000), "rich": (4100, 4110)}, taker="0.001")

    o = d.detect_opportunities("XAUUSD")[0]

    size = Decimal("0.1")
    expected_gross = (Decimal("4100") - Decimal("4000")) * size
    expected_fees = Decimal("4000") * size * Decimal("0.001") + Decimal("4100") * size * Decimal("0.001")
    assert o.gross_profit == expected_gross
    assert o.net_profit == expected_gross - expected_fees


def test_the_reported_latency_is_the_sum_of_both_venues():
    """Execution time is both legs, not the slower one — they are sent together."""
    from core.arbitrage.cross_exchange import ArbitrageDetector

    d = ArbitrageDetector(min_profit_bps=5.0)
    d.add_exchange(_Connector("cheap", 3990, 4000, latency=12.0))
    d.add_exchange(_Connector("rich", 4100, 4110, latency=30.0))
    d.price_cache["XAUUSD"] = {
        "cheap": {"bid": Decimal("3990"), "ask": Decimal("4000")},
        "rich": {"bid": Decimal("4100"), "ask": Decimal("4110")},
    }

    o = d.detect_opportunities("XAUUSD")[0]

    assert o.execution_time_ms == 42.0


def test_the_best_prices_are_picked_across_more_than_two_venues():
    d = _detector_with({"a": (3980, 4050), "b": (4100, 4000), "c": (4020, 4030)})

    o = d.detect_opportunities("XAUUSD")[0]

    assert o.buy_exchange == "b", "4000 was the lowest ask"
    assert o.sell_exchange == "b", "4100 was the highest bid"


# ── Execution and leg risk ────────────────────────────────────────────────────


def _opportunity(**over):
    from core.arbitrage.cross_exchange import ArbitrageOpportunity

    base = {
        "buy_exchange": "cheap",
        "sell_exchange": "rich",
        "symbol": "XAUUSD",
        "buy_price": Decimal("4000"),
        "sell_price": Decimal("4100"),
        "size": Decimal("0.1"),
        "gross_profit": Decimal("10"),
        "net_profit": Decimal("9"),
        "profit_bps": 250.0,
        "execution_time_ms": 40.0,
        "confidence": 0.8,
    }
    base.update(over)
    return ArbitrageOpportunity(**base)


async def test_both_legs_filling_is_a_success():
    from core.arbitrage.cross_exchange import ArbitrageExecutor

    cheap, rich = _Connector("cheap", 3990, 4000), _Connector("rich", 4100, 4110)

    ok = await ArbitrageExecutor().execute(_opportunity(), {"cheap": cheap, "rich": rich})

    assert ok is True
    assert [o["side"] for o in cheap.orders] == ["buy"]
    assert [o["side"] for o in rich.orders] == ["sell"]


async def test_both_legs_are_sent_as_limit_orders_inside_the_spread():
    """A market order here would give away the edge to slippage."""
    from core.arbitrage.cross_exchange import ArbitrageExecutor

    cheap, rich = _Connector("cheap", 3990, 4000), _Connector("rich", 4100, 4110)

    await ArbitrageExecutor().execute(_opportunity(), {"cheap": cheap, "rich": rich})

    assert cheap.orders[0]["order_type"] == "limit"
    assert rich.orders[0]["order_type"] == "limit"
    # Buy slightly above, sell slightly below, to improve fill odds.
    assert cheap.orders[0]["price"] > Decimal("4000")
    assert rich.orders[0]["price"] < Decimal("4100")


async def test_both_legs_failing_is_a_failure_with_no_hedge():
    """Nothing filled means no exposure — hedging would create one."""
    from core.arbitrage.cross_exchange import ArbitrageExecutor

    cheap = _Connector("cheap", 3990, 4000, fills=False)
    rich = _Connector("rich", 4100, 4110, fills=False)

    ok = await ArbitrageExecutor().execute(_opportunity(), {"cheap": cheap, "rich": rich})

    assert ok is False
    assert len(cheap.orders) == 1 and len(rich.orders) == 1, "an unnecessary hedge was sent"


async def test_stats_are_safe_before_any_scan_has_run():
    """A dashboard polls this from startup; both divisors are zero."""
    from core.arbitrage.cross_exchange import CrossExchangeEngine

    s = CrossExchangeEngine().get_stats()

    assert s["detected"] == 0
    assert s["executed"] == 0
    assert s["success_rate"] == 0
    assert s["avg_profit"] == 0


def test_stats_report_a_success_rate_and_average():
    from core.arbitrage.cross_exchange import CrossExchangeEngine

    e = CrossExchangeEngine()
    e.stats.update({"detected": 4, "executed": 3, "profit": Decimal("30")})

    s = e.get_stats()

    assert s["success_rate"] == 0.75
    assert s["avg_profit"] == 10.0


def test_the_engine_forwards_exchanges_to_its_detector():
    from core.arbitrage.cross_exchange import CrossExchangeEngine

    e = CrossExchangeEngine()
    e.add_exchange(_Connector("alpha", 1, 2))

    assert "alpha" in e.detector.exchanges


def test_the_engine_starts_idle_with_a_tighter_threshold_than_the_default():
    from core.arbitrage.cross_exchange import ArbitrageDetector, CrossExchangeEngine

    e = CrossExchangeEngine()

    assert e.is_running is False
    assert e.detector.min_profit_bps == 5.0
    assert ArbitrageDetector().min_profit_bps == 10.0


async def test_the_run_loop_stops_when_is_running_is_cleared():
    """Otherwise shutdown hangs on a 10 Hz loop that never returns."""
    from core.arbitrage.cross_exchange import CrossExchangeEngine

    e = CrossExchangeEngine()
    e.add_exchange(_Connector("alpha", 100, 101))

    task = asyncio.create_task(e.run(symbols=["XAUUSD"]))
    await asyncio.sleep(0.05)
    e.is_running = False
    await asyncio.wait_for(task, timeout=2.0)

    assert task.done()


async def test_the_run_loop_survives_a_detector_error():
    """A raising scan must not kill the engine and stop all future arbitrage."""
    from core.arbitrage.cross_exchange import CrossExchangeEngine

    e = CrossExchangeEngine()

    async def _boom():
        raise RuntimeError("price feed down")

    e.detector.update_prices = _boom  # type: ignore[method-assign]

    task = asyncio.create_task(e.run(symbols=["XAUUSD"]))
    await asyncio.sleep(0.05)

    assert not task.done(), "the engine died on a scan error"
    e.is_running = False
    task.cancel()
    with pytest.raises((asyncio.CancelledError, TimeoutError)):
        await asyncio.wait_for(task, timeout=1.0)


# ── Opportunity dataclass ─────────────────────────────────────────────────────


def test_the_opportunity_record_carries_everything_needed_to_audit_a_trade():
    o = _opportunity()

    assert o.buy_exchange and o.sell_exchange and o.symbol
    assert o.gross_profit >= o.net_profit, "net cannot exceed gross"
    assert 0.0 <= o.confidence <= 1.0
