# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
BROKER_TYPE=oanda must fail where someone can see it.

**The adapter now exists.** ``brokers/oanda.py:422`` implements
``place_market_order`` over ``place_order``, and ``_normalise_side`` maps
``OrderSide.BUY``/``"long"`` to ``buy`` and ``OrderSide.SELL``/``"short"`` to
``sell``, *raising* on anything it does not recognise rather than defaulting —
because ``_units()`` treats an unrecognised direction as a SELL, so a guess
there places the opposite of the intended trade.

This docstring previously said the opposite: that ``OANDABroker`` has no
``place_market_order`` and "the connector is left unimplemented and loud rather
than quietly wrong". That stopped being true when the adapter landed, and the
test bodies below were updated while this text was not — one of them says in as
many words that it "flipped to a failure the moment the adapter was written".
A file whose prose contradicts its own assertions teaches the next reader the
wrong thing twice.

What is still true, and is this file's subject:

* ``deployments/k8s/k8s-configmap.yaml:33-34`` sets ``BROKER_TYPE=oanda`` with
  ``OANDA_PRACTICE=false``, so a deployment that cannot place an order must
  refuse at startup rather than on the first live signal.
* Nothing here has spoken to OANDA. Every test runs against a stubbed
  ``place_order``; the adapter's own docstring says so. Venue verification on a
  practice account is the remaining work and it needs credentials, not code.
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


# ── the claim that had no check ───────────────────────────────────────────────
#
# `_try_connect_oanda` verifies the connector can place an order before
# reporting the broker ready — an explicit `hasattr` gate, and the reason
# BROKER_TYPE=oanda now refuses at startup instead of on the first signal.
#
# `_try_connect_factory_broker`, which handles every OTHER broker type, asserts
# the same property in prose and checks nothing:
#
#     "These connectors implement BrokerConnector and inherit place_market_order
#      from the base adapter, so the live order router drives them uniformly."
#
# Measured across the 22 registered names, 21 do exactly that. One does not:
# `oanda` -> `OANDAConnector`, whose base is `object`. Nothing reaches it by a
# path that calls `place_market_order` today — startup dispatches oanda to the
# guarded branch, hopefx_engine routes oanda to paper, and SmartRouter drives
# `place_order`, which it has. So this is a latent trap rather than a live
# defect, and it is one deletion away from being live: remove the oanda branch
# at startup_factories.py:1552, or register one new connector that forgets the
# base, and a deployment boots, logs "connected", and raises AttributeError on
# the first order.
#
# A docstring is not a control. These make it one.


def test_every_factory_registered_connector_satisfies_the_router_contract():
    """The property `_try_connect_factory_broker` states in prose.

    Exempting `oanda` by name rather than skipping the assertion: the exemption
    is visible, and the test fails the day a SECOND connector drifts — which is
    the case this exists to catch. It also fails if oanda is fixed, so the
    exemption cannot outlive its reason.
    """
    from brokers.factory import BrokerFactory

    known_gap = {"oanda"}
    registered = {n: BrokerFactory._brokers.get(n) for n in BrokerFactory.list_brokers()}
    assert len(registered) > 5, "the factory registered almost nothing; this assertion would be vacuous"

    missing = {n for n, cls in registered.items() if cls is not None and not hasattr(cls, "place_market_order")}
    unexpected = missing - known_gap
    assert not unexpected, (
        f"{sorted(unexpected)} are registered but cannot be driven by the live order router — "
        "_try_connect_factory_broker would connect them and report ready"
    )
    fixed = known_gap - missing
    assert not fixed, f"{sorted(fixed)} now satisfies the contract; delete it from known_gap and from the guard's note"


@pytest.mark.asyncio
async def test_the_factory_path_refuses_a_connector_that_cannot_place_an_order(monkeypatch):
    """The same refusal `_try_connect_oanda` already performs, for every other type.

    Without this, the gap above is caught only by a test nobody runs at deploy
    time. `_connect_oanda` proves the shape is right; this carries it across.
    """
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

        # No place_market_order — exactly OANDAConnector's shape.

    class _Factory:
        @staticmethod
        def create_broker(name, config=None):
            return _Unusable()

    monkeypatch.setitem(__import__("sys").modules, "brokers.factory", type("m", (), {"BrokerFactory": _Factory}))
    broker = await startup_factories._try_connect_factory_broker("alpaca", lambda *_a, **_k: None)
    assert broker is None, (
        "a connector with no place_market_order was reported ready; "
        "the live order router will raise AttributeError on the first signal"
    )
