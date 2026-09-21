# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Tests for TTL-based pruning of resting orders in risk/self_trade_prevention.py.

Regression coverage for the resource-leak / worsening-false-positive bug: live
callers add every submitted order to the resting book but never call
remove_resting_order() on fill/cancel, so without pruning the book grew unbounded
and long-since-filled phantom orders kept matching against new orders forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from risk.self_trade_prevention import Order, SelfTradeAction, SelfTradePrevention

UTC = timezone.utc


def _order(
    oid: str,
    *,
    symbol: str = "XAUUSD",
    side: str = "sell",
    size: float = 1.0,
    price: float = 1900.0,
    account_id: str = "acc1",
    strategy_id: str | None = "strat1",
    age_seconds: float = 0.0,
) -> Order:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Order(
        id=oid,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        timestamp=ts,
        account_id=account_id,
        strategy_id=strategy_id,
    )


class TestTTLPruningOnCheck:
    def test_stale_resting_order_pruned_and_does_not_match(self):
        # A resting SELL that would normally trigger a self-trade block, but it is
        # older than the TTL -> it must be pruned and NOT matched.
        stp = SelfTradePrevention(
            prevention_level="account",
            action=SelfTradeAction.CANCEL_NEW,
            resting_ttl_seconds=60.0,
        )
        stp.add_resting_order(_order("old_resting", side="sell", price=1900.0, age_seconds=3600))

        new_buy = _order("new", side="buy", price=1901.0, age_seconds=0)
        result = stp.check_self_trade(new_buy)

        assert result is None  # stale order no longer matches
        # and the stale order was physically removed from the book
        assert all(o.id != "old_resting" for o in stp.resting_orders.get("XAUUSD", []))

    def test_fresh_resting_order_still_matches(self):
        # A genuinely-live resting order (within TTL) MUST still be protected.
        stp = SelfTradePrevention(
            prevention_level="account",
            action=SelfTradeAction.CANCEL_NEW,
            resting_ttl_seconds=3600.0,
        )
        stp.add_resting_order(_order("fresh_resting", side="sell", price=1900.0, age_seconds=1))

        new_buy = _order("new", side="buy", price=1901.0, age_seconds=0)
        result = stp.check_self_trade(new_buy)

        assert result is not None
        assert result["action"] == "reject"


class TestTTLPruningOnAdd:
    def test_stale_orders_pruned_on_insert(self):
        stp = SelfTradePrevention(resting_ttl_seconds=60.0)
        stp.add_resting_order(_order("stale1", age_seconds=120))
        stp.add_resting_order(_order("stale2", age_seconds=300))
        # Adding a fresh order triggers a prune of the whole symbol book.
        stp.add_resting_order(_order("fresh", age_seconds=0))

        ids = {o.id for o in stp.resting_orders["XAUUSD"]}
        assert ids == {"fresh"}

    def test_ttl_disabled_keeps_orders(self):
        stp = SelfTradePrevention(resting_ttl_seconds=None, max_resting_per_symbol=10_000)
        stp.add_resting_order(_order("old", age_seconds=10_000))
        stp.add_resting_order(_order("new", age_seconds=0))
        assert len(stp.resting_orders["XAUUSD"]) == 2


class TestBoundedGrowth:
    def test_book_cannot_grow_unbounded_under_ttl(self):
        # Simulate the live pattern: many orders added, never explicitly removed.
        # All are stale relative to the final fresh order, so the book stays small.
        stp = SelfTradePrevention(resting_ttl_seconds=30.0)
        for i in range(500):
            stp.add_resting_order(_order(f"phantom_{i}", age_seconds=120))
        # Each insert prunes; book should already be empty of stale entries except
        # possibly the just-added one (which is also stale here).
        stp.add_resting_order(_order("live", age_seconds=0))
        book = stp.resting_orders["XAUUSD"]
        assert len(book) == 1
        assert book[0].id == "live"

    def test_hard_cap_enforced_within_ttl(self):
        # Even inside the TTL window, the per-symbol hard cap bounds the book.
        stp = SelfTradePrevention(resting_ttl_seconds=3600.0, max_resting_per_symbol=5)
        for i in range(20):
            # ascending age so earlier ids are older
            stp.add_resting_order(_order(f"o_{i}", age_seconds=20 - i))
        book = stp.resting_orders["XAUUSD"]
        assert len(book) == 5
        # The 5 newest (largest i -> smallest age) must be the survivors.
        surviving = {o.id for o in book}
        assert surviving == {f"o_{i}" for i in range(15, 20)}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
