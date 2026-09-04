# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The data-layer safety gate must not skip itself when the data layer is down.

``execution/engine.py:687``:

    if orchestrator._started and not orchestrator.is_safe_to_trade():

The ``_started`` conjunct makes the whole gate a no-op whenever the data layer
is not running — which is not a rare state. ``core/startup_helpers.py:95-116``
starts the orchestrator "(non-fatal)": it wraps ``start()`` in a 60s
``wait_for`` and catches both ``TimeoutError`` and bare ``Exception``, logs at
**warning**, and returns normally. The app then serves and executes orders.
``_started = True`` is set at the very end of ``start()``, so a failure in any
of the ten feed-startup steps leaves it False permanently, with no retry.

So ``is_safe_to_trade()`` correctly reports unsafe and the caller discards the
answer (F84, proven by execution). Every check the gate exists for is bypassed:
the macro-event blackout window, no live tick at all, tick confidence below
0.30, and a gold feed with zero active sources for 30s.

Every sibling call site fails closed, and one says so in a comment:

* ``ml/inference_engine.py:1391-1407`` — on any failure to reach the
  orchestrator, logs "failing CLOSED (not safe)" and returns False.
* ``execution/hopefx_engine.py:392`` — ``if not self._orch.is_safe_to_trade():``
  with no ``_started`` guard at all.
* ``data_layer/orchestrator.py:1089-1093`` — "No tick means no live price —
  fail CLOSED: a missing tick must NOT be treated as safe to trade."

This test file pins the gate to that same behaviour.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Orchestrator:
    def __init__(self, started: bool, safe: bool):
        self._started = started
        self._safe = safe
        self.asked = False

    def is_safe_to_trade(self) -> bool:
        self.asked = True
        return self._safe

    def get_latest_tick(self, symbol):
        return None


def _engine():
    from execution.engine import ExecutionEngine

    return ExecutionEngine.__new__(ExecutionEngine)


async def _run(monkeypatch, orch):
    """Drive _enrich_price_from_data_layer against a stand-in orchestrator.

    The patch target is ``sys.modules["data_layer.orchestrator"]``, not
    ``data_layer.orchestrator``. ``data_layer/__init__.py`` binds the name
    ``orchestrator`` on the *package* to a MarketDataOrchestrator **instance**,
    shadowing its own submodule — so ``import data_layer.orchestrator as dl``
    hands back the instance and patching it reaches nothing. The engine's
    ``from data_layer.orchestrator import orchestrator`` resolves through
    sys.modules, which is the real module.
    """
    import sys

    import data_layer.orchestrator  # noqa: F401  — ensure sys.modules is populated

    from execution.engine import ExecutionRequest

    monkeypatch.setattr(sys.modules["data_layer.orchestrator"], "orchestrator", orch, raising=False)

    engine = _engine()
    blocks = []

    async def _inc():
        blocks.append(1)

    monkeypatch.setattr(engine, "_inc_blocks", _inc, raising=False)
    monkeypatch.setattr(
        engine,
        "_blocked_report",
        lambda request, reason, t0: ("BLOCKED", reason),
        raising=False,
    )

    request = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="MARKET")
    result = await engine._enrich_price_from_data_layer(request, 0.0)
    return result, blocks


@pytest.mark.asyncio
async def test_an_unsafe_data_layer_blocks_even_when_it_never_started(monkeypatch):
    """The case F84 is about: not started, and unsafe. The gate used to let this
    through — and 'not started' is the normal degraded state."""
    orch = _Orchestrator(started=False, safe=False)

    result, blocks = await _run(monkeypatch, orch)

    assert orch.asked, "the gate did not even ask whether it was safe to trade"
    assert isinstance(result, tuple) and result[0] == "BLOCKED", (
        "an order executed while the data layer reported unsafe conditions"
    )
    assert blocks == [1], "the block was not counted"


@pytest.mark.asyncio
async def test_an_unsafe_data_layer_blocks_when_it_did_start(monkeypatch):
    """Regression guard: the case that already worked must keep working."""
    result, blocks = await _run(monkeypatch, _Orchestrator(started=True, safe=False))

    assert isinstance(result, tuple) and result[0] == "BLOCKED"
    assert blocks == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [True, False])
async def test_a_safe_data_layer_does_not_block(monkeypatch, started):
    """The gate must refuse unsafe conditions, not refuse everything."""
    result, blocks = await _run(monkeypatch, _Orchestrator(started=started, safe=True))

    assert not (isinstance(result, tuple) and result[0] == "BLOCKED")
    assert blocks == []


@pytest.mark.asyncio
async def test_an_orchestrator_that_raises_fails_closed(monkeypatch):
    """Matching ml/inference_engine.py, which logs 'failing CLOSED (not safe)'.
    An orchestrator that cannot answer has not said yes."""

    class _Broken(_Orchestrator):
        def is_safe_to_trade(self):
            self.asked = True
            raise RuntimeError("feed registry unavailable")

    result, blocks = await _run(monkeypatch, _Broken(started=True, safe=False))

    assert isinstance(result, tuple) and result[0] == "BLOCKED", (
        "an orchestrator that raised was treated as safe to trade"
    )
