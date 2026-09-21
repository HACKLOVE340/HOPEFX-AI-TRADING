# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_order_intent_reconciliation.py
==============================================
The order-intent alarm never converged.

`TradeExecutor` journals a write-ahead "intent" record before submitting an
order and clears it once the position is tracked (S7-02). If the process dies
between the broker ack and `add_position`, the intent survives — which is the
point: at the next boot `PositionManager.audit_order_intents` logs

    UNRECONCILED ORDER INTENT | client_order_id=… symbol=… position_now_open=…

at CRITICAL, because that order may have filled and be live and unmanaged.

But nothing ever removes it. `_clear_intent` is reached only on the happy path
inside `TradeExecutor`; no other code in `execution/`, `core/`, `api/` or
`brokers/` calls `remove_order`. And `audit_order_intents`' return value is
discarded by its only caller. So one crash three weeks ago produced a CRITICAL
line on every boot since, forever, and a genuinely new intent — the one that
means money may be moving unwatched right now — arrives indistinguishable from
that permanent backlog. An alarm that always fires is an alarm nobody reads.

Two cases, and they are not the same:

* **The symbol is open after broker reconciliation.** `_reconcile_with_broker`
  has already diffed the persisted positions against `broker.get_positions()`
  and dropped everything the broker does not hold, so a symbol still present is
  one the broker itself confirmed. The order completed; only the journal write
  failed. That is resolved, and the record is cleared — with a log line saying
  what happened, not silently.

* **The symbol is not open.** Either the order never reached the broker, or it
  filled and there is no local record. This is the dangerous case and it is
  never auto-cleared. It does get an age: the record carries how many boots it
  has survived, so an operator can tell a new intent from a known one instead of
  reading the same undifferentiated CRITICAL line every restart.

Nothing here closes or cancels anything at the broker. It only clears journal
records the broker has already confirmed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


class _Store:
    """Stands in for AsyncRedisStateStore's order journal."""

    def __init__(self, orders):
        self.orders = list(orders)
        self.removed: list[str] = []
        self.saved: list[dict] = []

    async def load_orders(self):
        return list(self.orders)

    async def remove_order(self, order_id):
        self.removed.append(order_id)
        self.orders = [o for o in self.orders if (o.get("client_order_id") or o.get("id")) != order_id]

    async def save_order(self, order):
        self.saved.append(order)
        oid = order.get("client_order_id") or order.get("id")
        self.orders = [o for o in self.orders if (o.get("client_order_id") or o.get("id")) != oid]
        self.orders.append(order)

    async def load_state_on_boot(self):
        return {"orders": list(self.orders), "positions": []}


def _intent(cid="ord-1", symbol="XAUUSD", **extra):
    base = {
        "id": cid,
        "client_order_id": cid,
        "symbol": symbol,
        "side": "BUY",
        "quantity": 0.1,
        "status": "intent",
    }
    base.update(extra)
    return base


def _pm(store):
    from execution.position_manager import PositionManager

    pm = PositionManager()
    pm._redis_store = store
    return pm


class TestAConfirmedIntentIsResolved:
    def test_it_is_cleared_when_the_symbol_is_open(self):
        """_reconcile_with_broker already proved the broker holds this position."""
        store = _Store([_intent("ord-1", "XAUUSD")])
        pm = _pm(store)

        asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        assert store.removed == ["ord-1"], (
            "the broker confirmed this position, so the order completed and only the "
            "journal write failed; leaving the record re-alerts CRITICAL every boot"
        )

    def test_it_does_not_re_alert_on_the_next_boot(self):
        store = _Store([_intent("ord-1", "XAUUSD")])
        pm = _pm(store)

        asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))
        second = asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        assert second == [], "the alarm must converge, or nobody reads it"

    def test_clearing_is_reported_not_silent(self, caplog):
        import logging

        store = _Store([_intent("ord-1", "XAUUSD")])
        pm = _pm(store)

        with caplog.at_level(logging.INFO, logger="execution.position_manager"):
            asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        assert any("ord-1" in r.message or "ord-1" in str(r.args) for r in caplog.records)


class TestAnUnconfirmedIntentIsKept:
    def test_it_is_not_cleared_when_the_symbol_is_not_open(self):
        """Either it never reached the broker, or it filled and we have no record."""
        store = _Store([_intent("ord-2", "EURUSD")])
        pm = _pm(store)

        orphans = asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        assert store.removed == []
        assert [o["client_order_id"] for o in orphans] == ["ord-2"]

    def test_it_is_still_critical(self, caplog):
        import logging

        store = _Store([_intent("ord-2", "EURUSD")])
        pm = _pm(store)

        with caplog.at_level(logging.CRITICAL, logger="execution.position_manager"):
            asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        assert [r for r in caplog.records if r.levelno >= logging.CRITICAL]

    def test_it_carries_an_age_so_a_new_one_is_distinguishable(self):
        """Otherwise every boot prints the same undifferentiated line."""
        store = _Store([_intent("ord-2", "EURUSD")])
        pm = _pm(store)

        first = asyncio.run(pm.audit_order_intents({}))[0]
        second = asyncio.run(pm.audit_order_intents({}))[0]
        third = asyncio.run(pm.audit_order_intents({}))[0]

        assert first["boots_survived"] == 1
        assert second["boots_survived"] == 2
        assert third["boots_survived"] == 3

    def test_a_brand_new_intent_is_visibly_new_beside_an_old_one(self):
        store = _Store([_intent("old", "EURUSD")])
        pm = _pm(store)

        asyncio.run(pm.audit_order_intents({}))
        asyncio.run(pm.audit_order_intents({}))
        store.orders.append(_intent("new", "GBPUSD"))
        ages = {o["client_order_id"]: o["boots_survived"] for o in asyncio.run(pm.audit_order_intents({}))}

        assert ages["new"] == 1
        assert ages["old"] == 3

    def test_the_first_sighting_is_recorded(self):
        store = _Store([_intent("ord-2", "EURUSD")])
        pm = _pm(store)

        orphan = asyncio.run(pm.audit_order_intents({}))[0]

        assert orphan.get("first_seen_at"), "an operator needs to know when this started"


class TestItNeverTouchesTheBroker:
    def test_no_broker_call_is_made(self):
        """This clears journal records; it does not close or cancel anything."""
        broker = AsyncMock()
        store = _Store([_intent("ord-1", "XAUUSD"), _intent("ord-2", "EURUSD")])
        pm = _pm(store)
        pm._broker = broker

        asyncio.run(pm.audit_order_intents({"XAUUSD": object()}))

        broker.close_position.assert_not_called()
        broker.cancel_all_orders.assert_not_called()
        broker.place_order.assert_not_called()


class TestDegradation:
    def test_no_store_returns_empty(self):
        pm = _pm(None)
        pm._redis_store = None

        assert asyncio.run(pm.audit_order_intents({})) == []

    def test_a_failing_load_does_not_raise(self):
        class _Broken(_Store):
            async def load_orders(self):
                raise RuntimeError("redis down")

        assert asyncio.run(_pm(_Broken([])).audit_order_intents({})) == []

    def test_a_failing_remove_does_not_lose_the_audit(self):
        """A store that cannot clear must still report; it must not crash boot."""

        class _Broken(_Store):
            async def remove_order(self, order_id):
                raise RuntimeError("redis down")

        store = _Broken([_intent("ord-1", "XAUUSD")])

        asyncio.run(_pm(store).audit_order_intents({"XAUUSD": object()}))

    def test_non_intent_orders_are_ignored(self):
        store = _Store([_intent("ord-1", "XAUUSD", status="filled")])

        assert asyncio.run(_pm(store).audit_order_intents({"XAUUSD": object()})) == []
        assert store.removed == []

    def test_a_malformed_record_does_not_stop_the_audit(self):
        store = _Store([{"status": "intent"}, _intent("ord-2", "EURUSD")])

        orphans = asyncio.run(_pm(store).audit_order_intents({}))

        assert any(o.get("client_order_id") == "ord-2" for o in orphans)


class TestStartupSurfacesThem:
    def test_restore_from_redis_returns_the_audit_to_its_caller(self):
        """The list was computed and dropped, so nothing could act on it."""
        import inspect

        from execution.position_manager import PositionManager

        src = inspect.getsource(PositionManager.restore_from_redis)
        assert "audit_order_intents" in src
        assert "self._last_order_intent_audit" in src, "the audit result must be reachable after startup, not discarded"

    def test_the_result_is_readable_after_startup(self):
        store = _Store([_intent("ord-2", "EURUSD")])
        pm = _pm(store)

        asyncio.run(pm.restore_from_redis())

        assert [o["client_order_id"] for o in pm.last_order_intent_audit()] == ["ord-2"]
