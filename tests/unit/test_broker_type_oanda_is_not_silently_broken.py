# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
BROKER_TYPE=oanda must fail where someone can see it.

``brokers/oanda.py:681`` is ``AsyncOANDAConnector = OANDABroker`` — a bare alias.
``OANDABroker`` has ``place_order(order_request: dict)``; it does **not** have
``place_market_order``, which is what ``execution/trade_executor.py:409`` calls.
So the first live order raises ``AttributeError`` before an order is even
constructed (F61/F107), after the deployment has booted and reported the broker
connected.

``deployments/k8s/k8s-configmap.yaml:33-34`` already sets ``BROKER_TYPE=oanda``
with ``OANDA_PRACTICE=false``.

**Scope.** Making OANDA work is a feature; making it stop pretending is this
test's subject. The two methods are not interchangeable — ``place_order`` takes
a dict keyed ``direction`` ("long"/"short") and returns a dict, while the caller
passes ``side`` as an ``_OrderSide`` and expects a ``MarketOrderResult``. An
adapter guessed at without a venue to test against could place the opposite side
of an intended trade, so the connector is left unimplemented and loud rather
than quietly wrong.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

#: What execution/trade_executor.py actually calls on a broker.
REQUIRED = ("place_market_order", "get_account_info", "get_positions")


def test_the_oanda_connector_satisfies_the_interface_trade_executor_calls():
    """This was xfail(strict=True) while the connector had no place_market_order.

    It flipped to a failure the moment the adapter was written, which is what
    strict is for — nobody had to remember to un-skip it. Now an ordinary
    assertion: the interface is satisfied and must stay satisfied.
    """
    from brokers.oanda import AsyncOANDAConnector

    missing = [m for m in REQUIRED if not hasattr(AsyncOANDAConnector, m)]
    assert not missing, f"AsyncOANDAConnector is missing {missing}; BROKER_TYPE=oanda cannot place an order"


def test_the_underlying_order_method_is_still_there():
    """place_market_order is an adapter over place_order. Losing the latter
    would break the former silently."""
    from brokers.oanda import AsyncOANDAConnector

    assert hasattr(AsyncOANDAConnector, "place_order")


@pytest.mark.asyncio
async def test_connecting_refuses_a_broker_that_cannot_place_an_order(monkeypatch):
    """The deployment must refuse at startup rather than discover it on the
    first signal, with real money and a live account."""
    from core import startup_factories

    class _Unusable:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            return True

        async def get_account_info(self):
            return {}

        async def get_positions(self):
            return []

    monkeypatch.setattr("brokers.oanda.AsyncOANDAConnector", _Unusable, raising=False)

    with pytest.raises(RuntimeError, match="cannot place an order"):
        await startup_factories._try_connect_oanda("tok", "acct", True, lambda _m: None)


@pytest.mark.asyncio
async def test_a_usable_broker_still_connects(monkeypatch):
    """The guard must not reject a connector that does satisfy the interface —
    otherwise implementing OANDA would be blocked by the check meant to
    describe it."""
    from core import startup_factories

    class _Usable:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            return True

        async def place_market_order(self, **kw):
            return {}

        async def get_account_info(self):
            return {}

        async def get_positions(self):
            return []

    monkeypatch.setattr("brokers.oanda.AsyncOANDAConnector", _Usable, raising=False)
    monkeypatch.setattr(startup_factories, "_start_oanda_paper_clock", lambda *a, **k: None, raising=False)

    broker = await startup_factories._try_connect_oanda("tok", "acct", True, lambda _m: None)
    assert isinstance(broker, _Usable)
