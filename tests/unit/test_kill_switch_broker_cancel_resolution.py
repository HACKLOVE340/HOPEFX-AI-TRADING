# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_kill_switch_broker_cancel_resolution.py
=======================================================
``KillSwitch._broker_cancel_all`` could never find a broker, so the kill
switch never cancelled anything at the broker.

The function resolved the active broker through exactly two paths:

    from execution.engine import get_active_broker      # does not exist
    from execution.smart_router import get_router       # does not exist

Neither symbol is defined in those modules. ``execution/engine.py`` defines
``ExecutionEngine`` and no module-level accessor; ``execution/smart_router.py``
defines ``SmartRouter`` and no module-level accessor. Both imports therefore
raised ``ImportError`` on every call, and both were caught by a bare
``except Exception: pass``. Resolution fell through to:

    if broker is None:
        logger.warning("... no active broker found — skipping broker cancel")
        return

So on every kill switch activation, with a fully connected broker, the
sequence was: set the halt flag, write the Redis latch, send the Sentry
alert, send the risk-halt email — then log one warning and return without
calling ``cancel_all_orders``. Resting orders and open positions stayed live
at the broker while the operator saw a successful kill switch activation.

The sibling method ``check_broker_cod`` resolves the same broker and
documents a three-step order:

    1. execution.engine.get_active_broker()
    2. execution.smart_router.get_router()._primary_broker
    3. core.app_state.app_state.broker

Step 3 is the one that actually works today, and ``check_broker_cod`` has it.
``_broker_cancel_all`` duplicated the chain and stopped at step 2 — the two
copies of the same resolution logic drifted, and the copy guarding the money
lost the only working path.

The fix resolves the broker through one shared helper so the chain cannot
drift again, and the dead first two steps stay in place as forward
compatibility rather than as the only hope.

Note the async/sync dispatch below the resolution was already correct
(S12-04e); this defect is purely that the dispatch was unreachable.
"""

from __future__ import annotations

import asyncio

import pytest

from kill_switch import KillSwitch

pytestmark = pytest.mark.unit


class _SyncBroker:
    """An IBKR-shaped broker: ``cancel_all_orders`` is a plain method."""

    name = "SyncSpyBroker"

    def __init__(self) -> None:
        self.cancelled = 0

    def cancel_all_orders(self):
        self.cancelled += 1
        return True


class _AsyncBroker:
    """An OANDA/MT5-shaped broker: everything is ``async def``."""

    name = "AsyncSpyBroker"

    def __init__(self) -> None:
        self.cancelled = 0

    async def cancel_all_orders(self):
        self.cancelled += 1
        return True


class _BrokerWithoutCancel:
    name = "NoCancelBroker"


@pytest.fixture
def ks() -> KillSwitch:
    """A KillSwitch instance without __init__ side effects (files, Redis, threads)."""
    return KillSwitch.__new__(KillSwitch)


@pytest.fixture
def app_state_broker(monkeypatch):
    """Install a broker on the app_state singleton and restore it afterwards."""
    from core.app_state import app_state

    def _install(broker):
        monkeypatch.setattr(app_state, "broker", broker, raising=False)
        return broker

    return _install


def test_cancel_all_resolves_broker_from_app_state(ks, app_state_broker):
    """The live broker lives on app_state — the kill switch must find it there."""
    broker = app_state_broker(_SyncBroker())

    ks._broker_cancel_all("drawdown breach")

    assert broker.cancelled == 1, (
        "kill switch activated with a connected broker on app_state but never "
        "called cancel_all_orders — resting orders stay live at the broker"
    )


def test_cancel_all_resolves_async_broker_from_app_state(ks, app_state_broker):
    """OANDA and MT5 are async; resolution must reach the async dispatch path."""
    broker = app_state_broker(_AsyncBroker())

    ks._broker_cancel_all("drawdown breach")

    assert broker.cancelled == 1, "async broker was resolved but cancel_all_orders never ran"


def test_cancel_all_awaits_async_broker_inside_a_running_loop(ks, app_state_broker):
    """A kill switch firing from async code must still complete the cancel."""
    broker = app_state_broker(_AsyncBroker())

    async def _fire():
        # Run the sync method off the event loop thread, as a real caller would,
        # so the run_coroutine_threadsafe branch is the one exercised.
        await asyncio.to_thread(ks._broker_cancel_all, "drawdown breach")

    asyncio.run(_fire())

    assert broker.cancelled == 1, "cancel_all_orders was not awaited to completion inside a running loop"


def test_cancel_all_is_silent_when_no_broker_is_registered(ks, app_state_broker):
    """No broker anywhere is a legitimate state — it must not raise."""
    app_state_broker(None)

    ks._broker_cancel_all("drawdown breach")  # must not raise


def test_cancel_all_survives_a_broker_without_cancel_all_orders(ks, app_state_broker):
    """A broker connector missing the method must not break activation."""
    app_state_broker(_BrokerWithoutCancel())

    ks._broker_cancel_all("drawdown breach")  # must not raise


def test_cancel_all_never_propagates_broker_failure(ks, app_state_broker):
    """Broker cancel is best-effort: the halt must never be undone by a raise."""

    class _ExplodingBroker:
        name = "ExplodingBroker"

        def cancel_all_orders(self):
            raise RuntimeError("broker connection reset")

    app_state_broker(_ExplodingBroker())

    ks._broker_cancel_all("drawdown breach")  # must not raise


def test_check_broker_cod_still_resolves_through_app_state(ks, app_state_broker):
    """Characterization: the sibling resolver's working path must be preserved."""
    checked: list[str] = []

    class _CodBroker:
        name = "CodBroker"

        def _check_cancel_on_disconnect(self):
            checked.append(self.name)

    app_state_broker(_CodBroker())

    asyncio.run(ks.check_broker_cod())

    assert checked == ["CodBroker"], "check_broker_cod lost its app_state resolution path"
