# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A transient data-layer startup failure must not disable trading permanently.

``start_data_layer_orchestrator`` is documented "(non-fatal)": it wraps
``orchestrator.start()`` in a ``wait_for`` and catches both ``TimeoutError`` and
bare ``Exception``, logs at warning, and returns. ``_started = True`` is the last
line of ``start()``, so a failure in any of its ten feed-startup steps leaves the
orchestrator down **with no retry, for the life of the process**.

That was survivable while the safety gate ignored ``_started`` (F84): the app
traded blind. Now that the gate fails closed, the same transient failure stops
trading entirely and nothing ever tries again — a worse operational outcome, and
one this fix created. So the retry is part of the fix, not an extra.

The retry is bounded and backs off: an orchestrator that cannot start because a
credential is wrong should not be reconnected to for ever at full speed.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


class _State:
    data_layer_orchestrator = None


class _Orchestrator:
    """Fails ``fail_times`` times, then starts."""

    def __init__(self, fail_times: int = 0, exc=RuntimeError("feed registry down")):
        self.attempts = 0
        self._fail_times = fail_times
        self._exc = exc
        self._started = False

    async def start(self):
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise self._exc
        self._started = True


def _install(monkeypatch, orch):
    import sys

    import data_layer.orchestrator  # noqa: F401 — populate sys.modules

    # sys.modules, not the package attribute (F245).
    monkeypatch.setattr(sys.modules["data_layer.orchestrator"], "orchestrator", orch, raising=False)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Keep the tests about retry behaviour, not about wall-clock time."""
    monkeypatch.setenv("ORCHESTRATOR_RETRY_BASE_S", "0")
    monkeypatch.setenv("ORCHESTRATOR_STARTUP_TIMEOUT_S", "5")


@pytest.mark.asyncio
async def test_a_first_time_success_does_not_retry(monkeypatch):
    from core.startup_helpers import start_data_layer_orchestrator

    orch = _Orchestrator(fail_times=0)
    _install(monkeypatch, orch)
    state = _State()

    await start_data_layer_orchestrator(state)

    assert orch.attempts == 1
    assert state.data_layer_orchestrator is orch


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_and_succeeds(monkeypatch):
    """The case that matters: one bad attempt used to disable the data layer,
    and therefore trading, for the life of the process."""
    from core.startup_helpers import start_data_layer_orchestrator

    orch = _Orchestrator(fail_times=2)
    _install(monkeypatch, orch)
    state = _State()

    await start_data_layer_orchestrator(state)

    assert orch.attempts == 3, f"gave up after {orch.attempts} attempt(s)"
    assert state.data_layer_orchestrator is orch, "the data layer started but was never recorded on state"


@pytest.mark.asyncio
async def test_retries_are_bounded(monkeypatch):
    """An orchestrator that cannot start because a credential is wrong must not
    be retried for ever."""
    from core.startup_helpers import start_data_layer_orchestrator

    monkeypatch.setenv("ORCHESTRATOR_STARTUP_ATTEMPTS", "3")
    orch = _Orchestrator(fail_times=99)
    _install(monkeypatch, orch)
    state = _State()

    await start_data_layer_orchestrator(state)

    assert orch.attempts == 3
    assert state.data_layer_orchestrator is None


@pytest.mark.asyncio
async def test_startup_is_still_non_fatal(monkeypatch):
    """Exhausting the retries must not take the whole app down -- the rest of
    startup still has to run."""
    from core.startup_helpers import start_data_layer_orchestrator

    monkeypatch.setenv("ORCHESTRATOR_STARTUP_ATTEMPTS", "2")
    _install(monkeypatch, _Orchestrator(fail_times=99))

    await start_data_layer_orchestrator(_State())  # must not raise


@pytest.mark.asyncio
async def test_exhausting_retries_says_trading_is_blocked(monkeypatch, caplog):
    """The operator has to be told the consequence, not just the cause. With the
    F84 gate failing closed, no data layer means no trading."""
    from core.startup_helpers import start_data_layer_orchestrator

    monkeypatch.setenv("ORCHESTRATOR_STARTUP_ATTEMPTS", "1")
    _install(monkeypatch, _Orchestrator(fail_times=99))

    with caplog.at_level("ERROR"):
        await start_data_layer_orchestrator(_State())

    text = " ".join(r.message for r in caplog.records).lower()
    assert "trading" in text, "the log does not say that orders will be blocked"


@pytest.mark.asyncio
async def test_a_timeout_is_retried_too(monkeypatch):
    """A slow feed on one attempt is the most likely transient failure of all."""
    from core.startup_helpers import start_data_layer_orchestrator

    class _Slow(_Orchestrator):
        async def start(self):
            self.attempts += 1
            if self.attempts <= 1:
                raise TimeoutError
            self._started = True

    orch = _Slow()
    _install(monkeypatch, orch)
    state = _State()

    await start_data_layer_orchestrator(state)

    assert orch.attempts == 2
    assert state.data_layer_orchestrator is orch


@pytest.mark.asyncio
async def test_backoff_grows_between_attempts(monkeypatch):
    """Retrying a wrong credential at full speed is a busy loop against whatever
    is refusing the connection."""
    from core import startup_helpers

    monkeypatch.setenv("ORCHESTRATOR_RETRY_BASE_S", "2")
    monkeypatch.setenv("ORCHESTRATOR_STARTUP_ATTEMPTS", "4")
    slept: list[float] = []

    async def _record(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record)
    _install(monkeypatch, _Orchestrator(fail_times=99))

    await startup_helpers.start_data_layer_orchestrator(_State())

    assert slept == sorted(slept), f"backoff did not grow: {slept}"
    assert len(set(slept)) > 1, f"every wait was identical: {slept}"
