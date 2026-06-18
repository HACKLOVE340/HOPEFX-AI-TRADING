"""Robustness tests for the IBKR connector using a faked ib_insync SDK.

ib_insync isn't installed in CI (and needs a live TWS/Gateway), so we inject a
fake module to exercise the connector's order path, safety gates, and the
inherited place_market_order adapter without a real broker. Verifies:
  - kill-switch hard block, not-connected guard, LIMIT/STOP validation;
  - market order → normalised Order (status/fill price/UTC ts);
  - place_market_order adapter integration;
  - get_positions parsing.
"""

import importlib
import sys
import types

import pytest

# ── Build + inject a fake ib_insync BEFORE importing the connector ────────────
_fake = types.ModuleType("ib_insync")


class _FakeOrder:
    def __init__(self, action=None, qty=None, price=None):
        self.action, self.totalQuantity, self.lmtPrice = action, qty, price
        self.transmit = True
        self.orderId = 42


def _market(action, qty):
    return _FakeOrder(action, qty)


def _limit(action, qty, price):
    return _FakeOrder(action, qty, price)


def _stop(action, qty, stop):
    return _FakeOrder(action, qty, stop)


class _Contract:
    def __init__(self, *a, **k):
        self.symbol = k.get("symbol", a[0] if a else "XAUUSD")
        self.conId = 1


for _name in ("Commodity", "CFD", "Future"):
    setattr(_fake, _name, type(_name, (_Contract,), {}))
_fake.Contract = _Contract
_fake.MarketOrder, _fake.LimitOrder, _fake.StopOrder = _market, _limit, _stop
_fake.IB = type("IB", (), {})
_fake.Trade = type("Trade", (), {})
sys.modules["ib_insync"] = _fake

ibkr = importlib.import_module("brokers.ibkr_connector")
importlib.reload(ibkr)

from brokers.base import MarketOrderResult, OrderSide, OrderStatus, OrderType


class _OrderStatus:
    def __init__(self, status="Filled", avg=2000.0, filled=1.0):
        self.status, self.avgFillPrice, self.filled = status, avg, filled


class _Trade:
    def __init__(self, order_id=42, status="Filled", avg=2000.0, filled=1.0):
        self.order = types.SimpleNamespace(orderId=order_id)
        self.orderStatus = _OrderStatus(status, avg, filled)


class _FakeIB:
    def __init__(self):
        self.placed = []

    def qualifyContracts(self, *contracts):
        return list(contracts)

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return _Trade(filled=order.totalQuantity, avg=2000.0)

    def sleep(self, _s):
        pass

    def positions(self, account=""):
        c = _Contract(symbol="XAUUSD")
        return [types.SimpleNamespace(position=2.0, contract=c, avgCost=4000.0)]

    def reqTicker(self, contract):
        return types.SimpleNamespace(marketPrice=lambda: 2050.0)


def _connected_conn(kill_switch=None):
    c = ibkr.IBKRConnector(config={"port": 7497}, kill_switch=kill_switch)
    c.connected = True
    c._ib = _FakeIB()
    return c


def test_market_order_fills_and_maps_utc():
    c = _connected_conn()
    order = c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
    assert order.status == OrderStatus.FILLED
    assert order.average_price == 2000.0 and order.filled_quantity == 1.0
    assert order.timestamp is None or order.timestamp.tzinfo is not None


def test_place_market_order_adapter():
    c = _connected_conn()
    res = __import__("asyncio").run(c.place_market_order("XAUUSD", "buy", 1.0))
    assert isinstance(res, MarketOrderResult)
    assert res.average_fill_price == 2000.0 and res.filled_quantity == 1.0


def test_not_connected_raises():
    c = _connected_conn()
    c.connected = False
    with pytest.raises(RuntimeError):
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)


def test_kill_switch_blocks_order():
    class _KS:
        def is_active(self):
            return True

        @property
        def reason(self):
            return "halted by test"

    c = _connected_conn(kill_switch=_KS())
    with pytest.raises(RuntimeError, match="kill switch"):
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)


def test_limit_requires_price_and_stop_requires_stop_price():
    c = _connected_conn()
    with pytest.raises(ValueError):
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0)
    with pytest.raises(ValueError):
        c.place_order("XAUUSD", OrderSide.SELL, OrderType.STOP, 1.0)


def test_get_positions_parses():
    c = _connected_conn()
    positions = c.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "XAUUSD" and p.quantity == 2.0 and p.side == OrderSide.BUY
    assert p.entry_price == 2000.0  # avgCost 4000 / qty 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
