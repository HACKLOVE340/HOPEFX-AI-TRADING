"""Conformance tests for the scaffold broker connectors.

Locks in the interface unification that wired alpaca / binance / bybit / ccxt /
cme / ibkr into the live order path:
  - every connector is a BrokerConnector and inherits place_market_order;
  - place_market_order adapts place_order and normalises the result;
  - the env→config mapper and factory wiring resolve.

These do NOT hit live exchanges (no credentials) — they verify interface
conformance, import safety, and the order-path adapter, which is what makes the
connectors safe to wire. Live execution still needs per-broker credential smoke
tests before trusting real money.
"""

import asyncio
import importlib

import pytest

from brokers.base import (
    BrokerConnector,
    MarketOrderResult,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)

CONNECTORS = [
    ("brokers.alpaca", "AlpacaConnector"),
    ("brokers.binance", "BinanceConnector"),
    ("brokers.bybit_connector", "ByBitConnector"),
    ("brokers.ccxt_connector", "CCXTConnector"),
    ("brokers.cme_comex", "CMEComexConnector"),
    ("brokers.ibkr_connector", "IBKRConnector"),
]


@pytest.mark.parametrize("mod,cls", CONNECTORS)
def test_connector_imports_and_conforms(mod, cls):
    """Each connector imports safely and is a BrokerConnector with the adapter."""
    klass = getattr(importlib.import_module(mod), cls)
    assert issubclass(klass, BrokerConnector), f"{cls} must extend BrokerConnector"
    # place_market_order is inherited from the base adapter (order-path contract).
    assert hasattr(klass, "place_market_order")
    # Core interface present.
    for method in ("connect", "disconnect", "place_order", "cancel_order", "get_positions", "get_account_info"):
        assert callable(getattr(klass, method, None)), f"{cls}.{method} missing"


def test_market_order_result_normalises_any_order_shape():
    """from_order maps both id/average_price and order_id/average_fill_price shapes."""
    o = Order(
        id="X1", symbol="BTCUSD", side=OrderSide.BUY, type=OrderType.MARKET,
        quantity=0.5, status=OrderStatus.FILLED, filled_quantity=0.5, average_price=64000.0,
    )
    r = MarketOrderResult.from_order(o)
    assert r.order_id == "X1"
    assert r.average_fill_price == 64000.0
    assert r.filled_quantity == 0.5
    assert r.status.lower() == "filled"
    assert r.fill_price == r.average_fill_price


def test_place_market_order_adapter_normalises_and_accepts_str_side():
    """The base adapter accepts a string side, calls place_order, returns MarketOrderResult."""

    class _Demo(BrokerConnector):
        async def connect(self):
            self.connected = True
            return True

        async def disconnect(self):
            return True

        def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **k):
            assert side is OrderSide.BUY and order_type is OrderType.MARKET
            return Order(
                id="D1", symbol=symbol, side=side, type=order_type, quantity=quantity,
                status=OrderStatus.FILLED, filled_quantity=quantity, average_price=100.0,
            )

        async def cancel_order(self, oid):
            return True

        async def get_order(self, oid):
            return None

        async def get_positions(self):
            return []

        async def close_position(self, s):
            return True

        async def get_account_info(self):
            return None

        async def get_market_data(self, *a, **k):
            return None

    res = asyncio.run(_Demo({}).place_market_order("BTCUSD", "buy", 0.5, stop_loss=99.0))
    assert isinstance(res, MarketOrderResult)
    assert res.order_id == "D1" and res.average_fill_price == 100.0 and res.filled_quantity == 0.5


def test_place_market_order_raises_on_none():
    class _Reject(BrokerConnector):
        async def connect(self):
            return True

        async def disconnect(self):
            return True

        def place_order(self, **k):
            return None

        async def cancel_order(self, oid):
            return True

        async def get_order(self, oid):
            return None

        async def get_positions(self):
            return []

        async def close_position(self, s):
            return True

        async def get_account_info(self):
            return None

        async def get_market_data(self, *a, **k):
            return None

    with pytest.raises(RuntimeError):
        asyncio.run(_Reject({}).place_market_order("BTCUSD", "sell", 1.0))


def test_env_config_mapper_and_factory_wiring():
    import os

    from core.startup_factories import _broker_config_from_env

    os.environ["ALPACA_API_KEY"] = "k"
    os.environ["ALPACA_API_SECRET"] = "s"
    os.environ["ALPACA_PAPER"] = "true"
    cfg = _broker_config_from_env("alpaca")
    assert cfg["api_key"] == "k" and cfg["api_secret"] == "s" and cfg["paper"] is True

    from brokers.factory import BrokerFactory

    BrokerFactory._ensure_registered()
    # At least the connectors that import in this env should be registered.
    assert any(name in BrokerFactory._brokers for name in ("alpaca", "binance", "ccxt", "ibkr"))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
