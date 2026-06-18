"""Robustness tests for the hardened Binance connector (mocked HTTP — no live API).

Covers the production-hardening: per-request timeouts, signed-request shape
(timestamp + recvWindow + signature), UTC fill timestamps, idempotent duplicate
handling, and graceful failure (not-connected / network error → None) — plus the
inherited place_market_order order-path adapter.
"""

import asyncio

import pytest
import requests

from brokers.base import MarketOrderResult, OrderSide, OrderStatus, OrderType
from brokers.binance import _REQUEST_TIMEOUT, BinanceConnector, _session_with_timeout


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []
        self.headers = {}
        self.post_response = None
        self.delete_response = None
        self.get_response = None
        self.raise_on_post = None

    def post(self, url, params=None, **kw):
        self.calls.append(("POST", url, params))
        if self.raise_on_post:
            raise self.raise_on_post
        return self.post_response

    def get(self, url, params=None, **kw):
        self.calls.append(("GET", url, params))
        return self.get_response

    def delete(self, url, params=None, **kw):
        self.calls.append(("DELETE", url, params))
        return self.delete_response

    def close(self):
        pass


def _conn():
    c = BinanceConnector({"api_key": "k", "api_secret": "s", "testnet": True})
    c.connected = True
    c.session = FakeSession()
    return c


_FILL = {
    "orderId": 555,
    "origQty": "0.5",
    "executedQty": "0.5",
    "cummulativeQuoteQty": "32000.0",
    "status": "FILLED",
    "transactTime": 1700000000000,
    "price": "0",
}


def test_session_injects_default_timeout(monkeypatch):
    captured = {}

    def fake_request(self, *a, **kw):
        captured.update(kw)
        return FakeResponse({})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    s = _session_with_timeout(_REQUEST_TIMEOUT)
    s.get("https://example.test/ping")
    assert captured.get("timeout") == _REQUEST_TIMEOUT


def test_place_order_success_signed_shape_and_utc():
    c = _conn()
    c.session.post_response = FakeResponse(_FILL)
    order = c.place_order("BTC/USDT", OrderSide.BUY, quantity=0.5, order_type=OrderType.MARKET)
    assert order is not None
    assert order.id == "555" and order.filled_quantity == 0.5
    assert order.status == OrderStatus.FILLED
    # UTC-aware fill timestamp (was naive local before hardening)
    assert order.timestamp is not None and order.timestamp.tzinfo is not None
    # Signed request carried timestamp + recvWindow + signature
    _, _, params = c.session.calls[-1]
    assert "timestamp" in params and "recvWindow" in params and "signature" in params


def test_place_order_duplicate_is_idempotent():
    c = _conn()
    c.session.post_response = FakeResponse({"code": -2010, "msg": "duplicate"}, status_code=400)
    out = c.place_order("BTC/USDT", OrderSide.BUY, quantity=0.5, client_order_id="dedupe-1")
    assert out is None  # already submitted — not resubmitted, no second fill


def test_place_order_not_connected_returns_none():
    c = _conn()
    c.connected = False
    assert c.place_order("BTC/USDT", OrderSide.BUY, quantity=0.5) is None


def test_place_order_network_error_returns_none():
    c = _conn()
    c.session.raise_on_post = requests.ConnectionError("boom")
    assert c.place_order("BTC/USDT", OrderSide.BUY, quantity=0.5) is None


def test_place_market_order_adapter_normalises():
    c = _conn()
    c.session.post_response = FakeResponse(_FILL)
    res = asyncio.run(c.place_market_order("BTC/USDT", "buy", 0.5))
    assert isinstance(res, MarketOrderResult)
    assert res.order_id == "555" and res.filled_quantity == 0.5


def test_order_type_and_status_mappings():
    c = _conn()
    assert c._convert_order_type(OrderType.MARKET) == "MARKET"
    assert c._convert_order_type(OrderType.STOP_LIMIT) == "STOP_LOSS_LIMIT"
    assert c._parse_order_status("FILLED") == OrderStatus.FILLED
    assert c._parse_order_status("REJECTED") == OrderStatus.REJECTED
    assert c._parse_order_status("CANCELED") == OrderStatus.CANCELLED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
