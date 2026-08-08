# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_remaining_unawaited_broker_calls.py
====================================================
S12-04f/g — the tail of the never-awaited-broker-call family.

The backlog carried "~333 un-awaited broker call sites still need triage". That
number was a raw grep and it was wrong. An AST pass that filters properly gives:

    266   name matches anywhere            — mostly redis.ping / db.connect,
                                             which share method names with the
                                             broker surface and are unrelated
     37   broker-shaped receiver, inside async
      6   after excluding wait_for / gather / create_task / iscoroutine guards
      3   real, after reading every one

The three that survived reading:

* ``trader_full.py:186`` — ``order = self._broker.place_order(...)`` inside
  ``OrderGateway.place_market_order``, no await.
* ``trader_full.py:207`` — ``return self._broker.cancel_order(id)`` from an
  ``async def`` annotated ``-> bool``. It returns a coroutine, so the caller's
  ``if success:`` is true whatever the broker did.
* ``health_check_service.py:240`` — ``run_in_executor(None, _get_info)`` where
  ``_get_info`` returns ``broker.get_account_info()``. Against an async broker
  the executor hands back a coroutine, ``getattr(info, "balance", None)`` is
  ``None``, and the health check reports the broker **ok** having read nothing.

Verified NOT bugs, and left alone rather than churned:

* ``execution/fix_router.py:483`` — ``run_in_executor(..., lambda: broker.place_order(...))``
  with the comment "PaperTradingBroker.place_order is synchronous". Checked:
  ``PaperTradingBroker.place_order`` is indeed ``def``, not ``async def``. The
  comment is accurate and the executor is the right call.
* ``brain/brain.py:444,461`` — bind then ``await asyncio.wait_for(self._await_or_return(raw), …)``.
  Handles both shapes already.
* The five other ``brain/brain.py`` action sites — all inside ``asyncio.wait_for``.

``execution/broker_call.call_broker`` awaits a coroutine function and runs a sync
one in an executor, so one call site is correct against either shape.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _AsyncBroker:
    def __init__(self):
        self.orders: list[dict] = []
        self.cancelled: list[str] = []

    async def place_order(self, **kw):
        self.orders.append(kw)
        return {"status": "filled", "id": "o-1"}

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return True

    async def get_account_info(self):
        return {"balance": 12345.0}


class _SyncBroker(_AsyncBroker):
    def place_order(self, **kw):  # type: ignore[override]
        self.orders.append(kw)
        return {"status": "filled", "id": "o-1"}

    def cancel_order(self, order_id):  # type: ignore[override]
        self.cancelled.append(order_id)
        return True

    def get_account_info(self):  # type: ignore[override]
        return {"balance": 12345.0}


def _gateway(broker):
    from trader_full import OrderGateway

    g = OrderGateway.__new__(OrderGateway)
    g._broker = broker
    return g


@pytest.mark.parametrize("broker_cls", [_AsyncBroker, _SyncBroker])
@pytest.mark.asyncio
async def test_place_order_reaches_the_broker(broker_cls):
    broker = broker_cls()
    await _gateway(broker).place_market_order("XAUUSD", "BUY", 0.1)
    assert broker.orders, (
        "place_order built a coroutine and dropped it — the order never reached "
        "the broker and the caller was handed a truthy coroutine object (S12-04f)"
    )


@pytest.mark.parametrize("broker_cls", [_AsyncBroker, _SyncBroker])
@pytest.mark.asyncio
async def test_cancel_order_returns_a_bool_not_a_coroutine(broker_cls):
    broker = broker_cls()
    out = await _gateway(broker).cancel_order("o-1")
    assert out is True or out is False, f"cancel_order returned {type(out).__name__}, not a bool"
    assert broker.cancelled == ["o-1"]


@pytest.mark.asyncio
async def test_a_failed_cancel_is_reported_as_false():
    class _Broken(_AsyncBroker):
        async def cancel_order(self, order_id):
            raise RuntimeError("rejected")

    assert await _gateway(_Broken()).cancel_order("o-1") is False


# ── The health check must actually read the account ──────────────────────────


@pytest.mark.parametrize("broker_cls", [_AsyncBroker, _SyncBroker])
@pytest.mark.asyncio
async def test_the_health_check_reads_a_real_balance(broker_cls, monkeypatch):
    import health_check_service as hcs
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", broker_cls(), raising=False)

    status = await hcs._check_broker()
    assert status.status == "ok"
    assert "12345" in str(status.detail), (
        "the health check reported the broker healthy having read a coroutine "
        "object instead of the account — balance came back None (S12-04g). "
        f"detail was: {status.detail!r}"
    )
