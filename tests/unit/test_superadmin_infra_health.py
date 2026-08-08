# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_superadmin_infra_health.py
==========================================
The superadmin infrastructure page could not see the broker at all.

``api/superadmin/infrastructure.py`` did::

    from brokers.factory import get_broker
    broker = get_broker()
    if broker:
        results["broker"] = {"status": "ok", ...}

``brokers.factory`` defines exactly one public name, ``BrokerFactory``. There
is no ``get_broker``. So the import raised ``ImportError`` on every request,
the surrounding ``except Exception`` caught it, and the operations page that
exists to tell an operator whether the broker is alive reported

    broker: error — cannot import name 'get_broker' from 'brokers.factory'

for a broker that was connected and trading. The two checks above it (database,
Redis) work, which is why nobody noticed: the page renders, one tile is red,
and a red tile on an infrastructure page reads as "infrastructure problem"
rather than "this check is broken".

Two things are fixed here, and the second matters more than the first.

**The import.** The live broker is the one in ``app_state``, wired at startup —
the same object ``health_check_service._check_broker`` reads. ``BrokerFactory``
would have been the wrong answer even spelled correctly: it *constructs* a
broker, so a health page would have built a second connection as a side effect
of being viewed.

**The probe.** ``if broker:`` only asks whether the attribute is set. A broker
whose socket died an hour ago is still a truthy object, so the page reported
``ok`` for a broker that could not have filled an order. This is the same
silent-success shape the kill-switch and health-check fixes addressed: state
reported healthy because nothing checked it. The probe now calls the broker and
reports what came back.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _LiveBroker:
    async def get_account_info(self):
        return {"balance": 98_765.0}


class _DeadBroker:
    async def get_account_info(self):
        raise ConnectionError("socket closed")


class _SyncBroker:
    def get_account_info(self):
        return {"balance": 1234.0}


def test_brokers_factory_still_has_no_get_broker():
    """The premise. If someone adds ``get_broker`` later this test should fail
    loudly so the fix below can be reconsidered, rather than quietly diverging."""
    from brokers import factory

    assert not hasattr(factory, "get_broker"), (
        "brokers.factory now exports get_broker — re-check whether "
        "api/superadmin/infrastructure.py should use it instead of app_state"
    )


@pytest.mark.asyncio
async def test_a_connected_broker_is_reported_ok(monkeypatch):
    from api.superadmin import infrastructure
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", _LiveBroker(), raising=False)

    out = await infrastructure._probe_broker()
    assert out["status"] == "ok", (
        f"a live broker was reported {out['status']!r}: {out.get('detail')!r}. "
        "This was the ImportError — brokers.factory has no get_broker."
    )
    assert "98765" in str(out.get("detail", "")), "the probe reported ok without reading anything back from the broker"


@pytest.mark.asyncio
async def test_a_sync_broker_works_too(monkeypatch):
    """Not every adapter in this repo is async; the probe must not trade one
    shape for the other."""
    from api.superadmin import infrastructure
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", _SyncBroker(), raising=False)

    out = await infrastructure._probe_broker()
    assert out["status"] == "ok"
    assert "1234" in str(out.get("detail", ""))


@pytest.mark.asyncio
async def test_a_dead_broker_is_not_reported_ok(monkeypatch):
    """The point of the page. ``if broker:`` said ok for any non-None object,
    including one whose connection had dropped."""
    from api.superadmin import infrastructure
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", _DeadBroker(), raising=False)

    out = await infrastructure._probe_broker()
    assert out["status"] == "error", (
        "a broker that raises on every call was reported healthy — the probe "
        "is testing that the attribute is set, not that the broker answers"
    )


@pytest.mark.asyncio
async def test_no_broker_is_unavailable_not_error(monkeypatch):
    """Paper/backtest deployments run with no broker. That is a known state,
    not a fault, and must not light the page up red."""
    from api.superadmin import infrastructure
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", None, raising=False)

    out = await infrastructure._probe_broker()
    assert out["status"] == "unavailable"


@pytest.mark.asyncio
async def test_the_handler_itself_reports_a_live_broker_ok(monkeypatch):
    """The others exercise the extracted probe, so on the pre-fix code they
    failed with AttributeError rather than on the behaviour. This one calls the
    handler, which existed before and after, and fails on the old code for the
    real reason: ``broker: error — cannot import name 'get_broker'``."""
    from api.superadmin import infrastructure
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "broker", _LiveBroker(), raising=False)

    out = await infrastructure.get_infra_health(user=None)
    broker = out["components"]["broker"]
    assert broker["status"] == "ok", f"broker tile reported {broker!r} for a connected broker"
    assert "get_broker" not in str(broker.get("detail", "")), "the ImportError is still reaching the page's broker tile"


@pytest.mark.asyncio
async def test_the_probe_never_constructs_a_broker(monkeypatch):
    """Viewing a health page must not open a broker connection."""
    from api.superadmin import infrastructure
    from brokers.factory import BrokerFactory
    from core.app_state import app_state

    def _boom(*_a, **_k):
        raise AssertionError("the infra health probe constructed a broker")

    monkeypatch.setattr(BrokerFactory, "create_broker", _boom)
    monkeypatch.setattr(app_state, "broker", _LiveBroker(), raising=False)

    await infrastructure._probe_broker()
