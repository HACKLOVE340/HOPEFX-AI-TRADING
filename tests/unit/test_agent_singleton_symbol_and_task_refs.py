# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_agent_singleton_symbol_and_task_refs.py
=======================================================
Two singleton defects found while auditing my own earlier claim.

**The claim was wrong, and the real bug was one level up.** I had flagged
"``RegimeClassifier`` singleton shared across symbols". It is not: every
``NuclearStrategyAgent`` is constructed with a single ``symbol`` and owns its
own classifier, and the process-wide ``get_regime_classifier()`` is dead code
whose only reference anywhere is a comment in ``analysis/chart_analysis.py``
saying not to use it.

``get_nuclear_agent`` is the actual defect::

    def get_nuclear_agent(symbol="XAU_USD", reader=None):
        global _agent_instance
        if _agent_instance is None:
            _agent_instance = NuclearStrategyAgent(symbol=symbol, reader=reader)
        return _agent_instance      # symbol ignored on every later call

``api/nuclear_strategy.py`` passes a **request-supplied** symbol into it and
then reports success naming that symbol::

    agent = get_nuclear_agent(symbol=req.symbol)
    await agent.start()
    return {"status": "started", "symbol": req.symbol, ...}

So a POST of ``{"symbol": "EURUSD"}`` against a process that already built an
XAU_USD agent returns ``{"status": "started", "symbol": "EURUSD"}`` while the
agent runs XAU_USD. User-driven, in a trading path, and the response actively
confirms the wrong instrument.

The fix distinguishes two different questions that shared one signature:
"give me whatever agent is running" (``symbol=None``) from "give me the agent
for THIS symbol" (explicit), and refuses the second rather than answering it
wrongly.

**Second defect — a fire-and-forget task with no reference held.**
``MacroStoreBridge.force_refresh`` does::

    asyncio.ensure_future(self._load_fred_into_store(), loop=loop)

The event loop keeps only a weak reference to a task, so a task nobody holds
can be garbage-collected mid-await — the refresh silently never completes. It
has no callers today, which is why this is a footgun rather than an incident,
and why it is worth closing before the first one arrives. The ``except
RuntimeError`` branch additionally called ``asyncio.run()``, which blocks the
calling thread for the whole FRED fetch including retries.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_agent_singleton():
    import nuclear.nuclear_agent as na

    original = na._agent_instance
    na._agent_instance = None
    yield
    na._agent_instance = original


def _agent(symbol=None):
    from nuclear.nuclear_agent import get_nuclear_agent

    return get_nuclear_agent(symbol=symbol) if symbol is not None else get_nuclear_agent()


# ── The agent you asked for is the agent you get ─────────────────────────────


def test_the_first_call_builds_the_requested_symbol():
    agent = _agent("EUR_USD")
    assert agent._symbol == "EUR_USD"


def test_asking_for_a_different_symbol_is_refused_not_silently_wrong():
    """The deployed failure: the caller was handed another instrument's agent
    and told it was theirs."""
    _agent("XAU_USD")

    with pytest.raises(ValueError) as excinfo:
        _agent("EUR_USD")

    message = str(excinfo.value)
    assert "EUR_USD" in message and "XAU_USD" in message, (
        f"the error must name both the requested and the running symbol: {message}"
    )


def test_asking_for_the_same_symbol_returns_the_same_instance():
    """Control — the singleton must still be a singleton."""
    first = _agent("XAU_USD")
    second = _agent("XAU_USD")
    assert first is second


def test_asking_for_no_symbol_returns_whatever_is_running():
    """`_get_agent()` in api/nuclear_strategy.py means "the current agent", not
    "an XAU_USD agent" — it must not start raising because a different
    instrument happens to be running."""
    started = _agent("EUR_USD")
    assert _agent() is started


def test_no_symbol_on_a_cold_process_still_builds_a_default():
    agent = _agent()
    assert agent._symbol, "a bare call on a cold process must still yield a usable agent"


def test_the_endpoint_does_not_report_a_symbol_it_is_not_running():
    """The response said `symbol: req.symbol` regardless of reality."""
    import inspect

    import api.nuclear_strategy as ns

    src = inspect.getsource(ns.start_agent)
    assert "agent.symbol" in src or "agent._symbol" in src, (
        "start_agent still echoes the requested symbol rather than the agent's actual one"
    )


# ── A task nobody holds can vanish mid-flight ────────────────────────────────


def test_force_refresh_keeps_a_reference_to_its_task():
    """The event loop holds only a weak reference; an unreferenced task can be
    collected mid-await and the refresh silently never happens."""
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    bridge = MacroStoreBridge()
    calls: list[int] = []

    async def _fake_load():
        calls.append(1)
        await asyncio.sleep(0)

    bridge._load_fred_into_store = _fake_load  # type: ignore[method-assign]

    async def _run():
        bridge.force_refresh()
        assert getattr(bridge, "_refresh_tasks", None), "no reference retained to the scheduled task"
        # Let it run to completion.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return calls

    assert asyncio.run(_run()) == [1]


def test_the_task_reference_is_released_when_it_finishes():
    """Holding references forever is a leak in the other direction."""
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    bridge = MacroStoreBridge()

    async def _fake_load():
        await asyncio.sleep(0)

    bridge._load_fred_into_store = _fake_load  # type: ignore[method-assign]

    async def _run():
        bridge.force_refresh()
        for _ in range(5):
            await asyncio.sleep(0)
        return bridge._refresh_tasks

    assert asyncio.run(_run()) == set()


def test_force_refresh_outside_a_loop_does_not_block_on_asyncio_run():
    """`asyncio.run()` there blocked the calling thread for the entire FRED
    fetch, retries included."""
    import data_layer.feeds.macro.store_bridge as sb
    from tests.support.source_text import python_code_only

    # Prose-stripped, and scanned across the whole module rather than one
    # function: the docstring explains that asyncio.run() was removed and names
    # it, so a raw source scan matches the explanation instead of the code.
    # That is the "test matched my own comment" failure this helper exists for
    # — the fifth instance of it in this codebase.
    src = python_code_only(sb)
    assert "asyncio.run(" not in src, "MacroStoreBridge still blocks a caller with asyncio.run()"


def test_force_refresh_without_a_loop_is_a_no_op_that_says_so(caplog):
    """It must not raise, and it must not pretend it refreshed."""
    import logging

    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    bridge = MacroStoreBridge()
    with caplog.at_level(logging.WARNING):
        bridge.force_refresh()  # no running loop

    assert "no running event loop" in caplog.text.lower()
