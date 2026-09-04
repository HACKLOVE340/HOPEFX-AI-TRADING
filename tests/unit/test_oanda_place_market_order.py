# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
OANDA can place an order.

``execution/trade_executor.py:409`` calls
``broker.place_market_order(symbol=, side=, quantity=, client_order_id=)`` and
expects a ``MarketOrderResult``. ``OANDABroker`` had ``place_order(dict)`` and
no ``place_market_order``, so ``BROKER_TYPE=oanda`` raised ``AttributeError``
before an order was constructed (F61/F107). The previous commit made that refuse
at startup instead of failing on the first live order; this closes it.

**The dangerous part is the side.** ``_units(direction, quantity)`` returns
``rounded if direction.lower() in ("long", "buy") else -rounded`` — so anything
it does not recognise becomes a **SELL**. An empty string, ``None``, a typo, or
an enum whose ``.value`` was not unwrapped would each silently place the opposite
of the intended trade. The adapter validates the side itself and refuses
anything ambiguous rather than inheriting that default.

**This is not venue-verified.** Every test here runs against a stubbed
``place_order``; nothing has spoken to OANDA. It must be exercised on a practice
account before ``OANDA_PRACTICE=false``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Broker:
    """OANDABroker with place_order stubbed to record what it was given."""

    def __init__(self, result=None):
        from brokers.oanda import OANDABroker

        self._real = OANDABroker.__new__(OANDABroker)
        self.seen: list[dict] = []
        self._result = result or {
            "status": "filled",
            "fill_price": 3301.25,
            "quantity": 12,
            "direction": "long",
            "order_id": "oanda-1",
            "broker": "oanda",
            "raw": {"ok": True},
        }

    async def place_order(self, order_request):
        self.seen.append(order_request)
        return self._result

    async def place_market_order(self, **kw):
        from brokers.oanda import OANDABroker

        self._real.place_order = self.place_order
        return await OANDABroker.place_market_order(self._real, **kw)


@pytest.mark.asyncio
async def test_a_buy_reaches_place_order_as_a_buy():
    b = _Broker()
    await b.place_market_order(symbol="XAU_USD", side="buy", quantity=12.0, client_order_id="c1")

    assert b.seen[0]["direction"] == "buy"
    assert b.seen[0]["order_type"] == "MARKET"
    assert b.seen[0]["quantity"] == 12.0
    assert b.seen[0]["order_id"] == "c1"


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["sell", "SELL", "Sell", "short", "SHORT"])
async def test_every_spelling_of_sell_is_a_sell(side):
    """_units() only recognises ("long","buy") as positive. Every other value
    becomes a sell -- which is correct here and catastrophic for a typo."""
    b = _Broker()
    await b.place_market_order(symbol="XAU_USD", side=side, quantity=1.0, client_order_id="c1")

    assert b.seen[0]["direction"].lower() in ("sell", "short")


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["buy", "BUY", "Buy", "long", "LONG"])
async def test_every_spelling_of_buy_is_a_buy(side):
    b = _Broker()
    await b.place_market_order(symbol="XAU_USD", side=side, quantity=1.0, client_order_id="c1")

    assert b.seen[0]["direction"].lower() in ("buy", "long")


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["", None, "byu", "b", "flat", 0, "hold"])
async def test_an_unrecognised_side_is_refused_not_guessed(side):
    """The whole reason this adapter validates rather than passing through:
    _units() would turn each of these into a SELL."""
    b = _Broker()

    with pytest.raises(ValueError, match="side"):
        await b.place_market_order(symbol="XAU_USD", side=side, quantity=1.0, client_order_id="c1")

    assert b.seen == [], "an ambiguous side reached the broker"


@pytest.mark.asyncio
async def test_an_enum_side_is_unwrapped():
    """trade_executor passes _OrderSide, not a string. str(enum) would be
    'OrderSide.SELL', which _units() does not recognise as a buy."""
    from brokers.base import OrderSide

    b = _Broker()
    await b.place_market_order(symbol="XAU_USD", side=OrderSide.BUY, quantity=1.0, client_order_id="c1")

    assert b.seen[0]["direction"].lower() in ("buy", "long")


@pytest.mark.asyncio
async def test_the_result_is_a_market_order_result():
    from brokers.base import MarketOrderResult

    b = _Broker()
    result = await b.place_market_order(symbol="XAU_USD", side="buy", quantity=12.0, client_order_id="c1")

    assert isinstance(result, MarketOrderResult)
    assert result.order_id == "oanda-1"
    assert result.average_fill_price == 3301.25
    assert result.filled_quantity == 12
    assert result.status == "filled"


@pytest.mark.asyncio
async def test_a_rejected_order_is_reported_as_rejected():
    b = _Broker(result={"status": "rejected", "reason": "zero_quantity", "broker": "oanda"})
    result = await b.place_market_order(symbol="XAU_USD", side="buy", quantity=0.4, client_order_id="c1")

    assert result.status == "rejected"
    assert result.filled_quantity == 0
    assert result.average_fill_price == 0.0


@pytest.mark.asyncio
async def test_brackets_are_passed_through_and_reported():
    """MarketOrderResult.brackets_applied exists because 'silently returning
    success for a stop that does not exist is how a trader ends up believing
    they are protected' (F151). place_order does attach them, so say so."""
    b = _Broker()
    result = await b.place_market_order(
        symbol="XAU_USD",
        side="buy",
        quantity=1.0,
        client_order_id="c1",
        stop_loss=3290.0,
        take_profit=3320.0,
    )

    assert b.seen[0]["stop_loss"] == 3290.0
    assert b.seen[0]["take_profit"] == 3320.0
    assert result.brackets_applied is True


@pytest.mark.asyncio
async def test_no_brackets_requested_is_not_a_bracket_claim():
    b = _Broker()
    result = await b.place_market_order(symbol="XAU_USD", side="buy", quantity=1.0, client_order_id="c1")

    assert "stop_loss" not in b.seen[0] or b.seen[0]["stop_loss"] is None
    assert result.brackets_applied is True  # nothing was asked for, nothing was dropped


@pytest.mark.asyncio
async def test_a_non_positive_quantity_is_refused():
    b = _Broker()
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="quantity"):
            await b.place_market_order(symbol="XAU_USD", side="buy", quantity=bad, client_order_id="c1")
    assert b.seen == []


def test_the_startup_guard_now_passes():
    """core/startup_factories.py refuses BROKER_TYPE=oanda when the connector is
    missing this method. It should stop refusing now."""
    from brokers.oanda import AsyncOANDAConnector

    for m in ("place_market_order", "get_account_info", "get_positions"):
        assert hasattr(AsyncOANDAConnector, m), f"still missing {m}"
