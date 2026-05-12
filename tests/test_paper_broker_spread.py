# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_paper_broker_spread.py
==================================
Regression tests for PaperTradingBroker fill-price bid/ask spread bug.

Before the fix, place_order() always passed mid_price to SlippageModel
regardless of order side, so buys and sells filled at the same reference
price.  After the fix:
  - BUY  fills at ask + impact + noise  (buyer crosses the spread)
  - SELL fills at bid - impact - noise  (seller crosses the spread)
  - close_position() applies the same directional logic
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brokers.base import OrderSide, OrderType
from brokers.paper_trading import PaperTradingBroker


def _make_broker(seed: int = 42) -> PaperTradingBroker:
    """Return a connected PaperTradingBroker with zero-noise slippage for determinism."""
    broker = PaperTradingBroker(
        config={
            "initial_balance": 100_000.0,
            "slippage_model": "zero",  # zero noise so we can assert exact prices
        },
        seed=seed,
    )
    broker.connected = True
    return broker


def _make_tick(bid: float, ask: float) -> SimpleNamespace:
    mid = (bid + ask) / 2.0
    return SimpleNamespace(bid=bid, ask=ask, mid=mid)


def _attach_feed(broker: PaperTradingBroker, bid: float, ask: float) -> None:
    """Wire a minimal price feed that returns a tick with real bid/ask."""
    tick = _make_tick(bid, ask)
    feed = MagicMock()
    feed.get_last_price.return_value = tick
    broker._price_feed = feed
    # Also seed market_prices so the staleness guard doesn't fire
    broker.market_prices["XAUUSD"] = (bid + ask) / 2.0
    import time

    broker._price_timestamps["XAUUSD"] = time.time()


class TestBuyFillsAtAsk:
    def test_buy_fills_at_ask_not_mid(self):
        """BUY market order must fill at ask (or above), never below mid."""
        broker = _make_broker()
        bid, ask = 1999.0, 2001.0
        mid = (bid + ask) / 2.0
        _attach_feed(broker, bid, ask)

        order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        # With zero-noise model and spread override=0, fill == ask exactly
        assert order.average_price == pytest.approx(ask, abs=1e-6), (
            f"BUY should fill at ask={ask}, got {order.average_price}"
        )
        assert order.average_price >= mid, f"BUY fill {order.average_price} must be >= mid {mid}"

    def test_sell_fills_at_bid_not_mid(self):
        """SELL market order must fill at bid (or below), never above mid."""
        broker = _make_broker()
        bid, ask = 1999.0, 2001.0
        mid = (bid + ask) / 2.0
        _attach_feed(broker, bid, ask)

        # Need an open long position to sell against
        broker.market_prices["XAUUSD"] = mid
        broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        assert order.average_price == pytest.approx(bid, abs=1e-6), (
            f"SELL should fill at bid={bid}, got {order.average_price}"
        )
        assert order.average_price <= mid, f"SELL fill {order.average_price} must be <= mid {mid}"

    def test_buy_and_sell_are_not_equal(self):
        """BUY and SELL fills must differ by at least the spread."""
        broker_buy = _make_broker(seed=1)
        broker_sell = _make_broker(seed=1)
        bid, ask = 1999.0, 2001.0
        spread = ask - bid

        _attach_feed(broker_buy, bid, ask)
        _attach_feed(broker_sell, bid, ask)

        buy_order = broker_buy.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        # Seed a long so sell doesn't fail on missing position
        broker_sell.market_prices["XAUUSD"] = (bid + ask) / 2.0
        broker_sell.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        sell_order = broker_sell.place_order(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

        diff = buy_order.average_price - sell_order.average_price
        assert diff >= spread * 0.9, (
            f"buy={buy_order.average_price} sell={sell_order.average_price} diff={diff} expected >= spread={spread}"
        )


class TestClosePositionSpread:
    def test_close_long_fills_at_bid(self):
        """Closing a LONG position (= SELL) must fill at bid, not mid."""
        broker = _make_broker()
        bid, ask = 1999.0, 2001.0

        # Attach feed BEFORE opening so entry uses ask correctly
        _attach_feed(broker, bid, ask)

        buy_order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        assert "XAUUSD" in broker.positions
        entry_price = buy_order.average_price  # should be ask=2001

        broker.close_position("XAUUSD")

        # Position should be gone and balance should reflect bid-based exit
        assert "XAUUSD" not in broker.positions
        # Entry at ask (2001), exit at bid (1999) → loss of 2 per unit
        expected_balance = 100_000.0 + (bid - entry_price) * 1.0
        assert broker.balance == pytest.approx(expected_balance, abs=0.01), (
            f"balance={broker.balance} expected={expected_balance} entry={entry_price} exit_bid={bid}"
        )

    def test_no_feed_falls_back_to_slippage_model(self):
        """Without a price feed, close_position must still work via SlippageModel."""
        broker = _make_broker()
        broker.market_prices["XAUUSD"] = 2000.0
        import time

        broker._price_timestamps["XAUUSD"] = time.time()

        broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        result = broker.close_position("XAUUSD")
        assert result is True
        assert "XAUUSD" not in broker.positions
