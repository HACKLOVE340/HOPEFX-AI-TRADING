"""Hardening tests for alpaca / ccxt / bybit / cme connectors (mocked — no live API).

Verifies the deep-harden pass: alpaca per-call timeouts, ccxt rate-limit+timeout
config, bybit's hardened-ccxt delegation + recvWindow, and the cme factory
config-dict fix + paper fill path. Plus the inherited place_market_order adapter.
"""

import asyncio
import sys
import types

import pytest
import requests

from brokers.base import MarketOrderResult, OrderSide, OrderStatus, OrderType


# ── Shared fake HTTP ──────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, data, status_code=200):
        self._d = data
        self.status_code = status_code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.post_response = None
        self.calls = []

    def mount(self, *_a):
        pass

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return FakeResponse({})

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.post_response

    def close(self):
        pass


# ── ALPACA ────────────────────────────────────────────────────────────────────
_ALPACA_FILL = {
    "id": "a-1", "symbol": "AAPL", "side": "buy", "type": "market", "qty": "10",
    "status": "filled", "filled_qty": "10", "filled_avg_price": "190.5",
    "created_at": "2026-01-01T00:00:00Z",
}


def _alpaca():
    from brokers.alpaca import AlpacaConnector

    c = AlpacaConnector({"api_key": "k", "api_secret": "s", "paper": True})
    c.connected = True
    c.session = FakeSession()
    return c


def test_alpaca_place_order_and_adapter_and_timeout():
    c = _alpaca()
    c.session.post_response = FakeResponse(_ALPACA_FILL)
    order = c.place_order("AAPL", OrderSide.BUY, quantity=10, order_type=OrderType.MARKET)
    assert order is not None and order.status == OrderStatus.FILLED and order.average_price == 190.5
    # every call carries a timeout
    assert all("timeout" in kw for _, _, kw in c.session.calls)
    res = asyncio.run(c.place_market_order("AAPL", "buy", 10))
    assert isinstance(res, MarketOrderResult) and res.average_fill_price == 190.5


def test_alpaca_not_connected_returns_none():
    c = _alpaca()
    c.connected = False
    assert c.place_order("AAPL", OrderSide.BUY, quantity=10) is None


# ── CCXT (+ rate-limit/timeout hardening) ─────────────────────────────────────
def _install_fake_ccxt(monkeypatch):
    captured = {}

    class FakeExchange:
        has = {"fetchPositions": False}

        def __init__(self, params):
            captured["params"] = params
            self.markets = {"BTC/USDT": {}}

        def set_sandbox_mode(self, _b):
            pass

        def load_markets(self):
            return self.markets

        def create_order(self, symbol, type_, side, amount, price=None, params=None):
            return {
                "id": "c-1", "symbol": symbol, "side": side, "type": type_,
                "amount": amount, "price": price, "status": "closed",
                "filled": amount, "average": 64000.0, "timestamp": 1700000000000,
            }

    fake = types.ModuleType("ccxt")
    fake.binance = FakeExchange
    monkeypatch.setitem(sys.modules, "ccxt", fake)
    return captured


def test_ccxt_connect_enables_ratelimit_and_timeout(monkeypatch):
    captured = _install_fake_ccxt(monkeypatch)
    from brokers.ccxt_connector import CCXTConnector

    c = CCXTConnector({"exchange": "binance", "api_key": "k", "api_secret": "s"})
    assert c.connect() is True
    assert captured["params"]["enableRateLimit"] is True
    assert captured["params"]["timeout"] == 15000


def test_ccxt_place_order_and_adapter(monkeypatch):
    _install_fake_ccxt(monkeypatch)
    from brokers.ccxt_connector import CCXTConnector

    c = CCXTConnector({"exchange": "binance", "api_key": "k", "api_secret": "s"})
    c.connect()
    order = c.place_order("BTC/USDT", OrderSide.BUY, OrderType.MARKET, 0.5)
    assert order.status == OrderStatus.FILLED and order.filled_quantity == 0.5
    res = asyncio.run(c.place_market_order("BTC/USDT", "buy", 0.5))
    assert isinstance(res, MarketOrderResult) and res.average_fill_price == 64000.0


# ── BYBIT (wraps hardened ccxt) ───────────────────────────────────────────────
def test_bybit_wraps_ccxt_with_recvwindow_and_symbol_map():
    from brokers.bybit_connector import ByBitConnector

    b = ByBitConnector({"api_key": "k", "api_secret": "s"})
    assert b._ccxt.config["options"]["recvWindow"] == 5000
    assert b._ccxt._exchange_id == "bybit"
    # symbol translation round-trips
    internal = "XAUUSD"
    bybit_sym = b._to_bybit(internal)
    assert b._from_bybit(bybit_sym) == internal


# ── CME (factory config-dict fix + paper fill) ────────────────────────────────
def test_cme_accepts_factory_config_dict():
    from brokers.cme_comex import CMEComexConnector

    # Previously a dict bound to fix_host (positional) and broke; now mapped.
    c = CMEComexConnector({"paper_fallback": True, "ibkr_fallback": False})
    assert c._paper_fallback is True and c._ibkr_fallback is False
    assert isinstance(c._fix_host, str)


def test_cme_paper_fill_and_adapter():
    from brokers.cme_comex import CMEComexConnector

    c = CMEComexConnector({"paper_fallback": True, "ibkr_fallback": False})
    c.connected = True
    c._fix_available = False
    c._ibkr_available = False
    # Simulate an available market-data feed so the paper fill can price a
    # MARKET order (place_market_order does not carry a price, by design).
    c._resolve_market_price = lambda _sym: 2000.0
    order = c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
    assert order is not None and order.average_price == 2000.0
    res = asyncio.run(c.place_market_order("XAUUSD", "buy", 1.0))
    assert isinstance(res, MarketOrderResult) and res.average_fill_price == 2000.0


def test_cme_no_path_raises():
    from brokers.cme_comex import CMEComexConnector

    c = CMEComexConnector({"paper_fallback": False, "ibkr_fallback": False})
    c.connected = True
    c._fix_available = False
    c._ibkr_available = False
    with pytest.raises(RuntimeError):
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0, price=2000.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
