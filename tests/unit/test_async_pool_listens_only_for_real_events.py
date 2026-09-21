# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The async DB pool must not register listeners for events SQLAlchemy does not have.

`database/async_connection.py` registered two:

    @event.listens_for(sync_engine.pool, "overflow")
    @event.listens_for(sync_engine.pool, "timeout")

guarded by a comment asserting they "only exist on QueuePool, not NullPool or
StaticPool". Neither exists on any pool. SQLAlchemy 2.x `PoolEvents` is exactly:
connect, first_connect, checkout, checkin, reset, invalidate, soft_invalidate,
close, detach, close_detached.

The guard was therefore backwards. It excluded NullPool and StaticPool — the two
pools where the block would not have run anyway — and then registered on
QueuePool and AsyncAdaptedQueuePool, where `event.listens_for` raises
`InvalidRequestError: No such event 'overflow'`.

Consequences, in order of how they surfaced:

* async pool initialisation raised on **every deployment using the default
  pool**, which is every Postgres deployment;
* the caller catches that and logs `Async DB pool init failed` at WARNING, so
  the process continues;
* the `db_pool` component reports critical-down forever, and
  `/api/health/ready` returns 503 while any critical component is down;
* under Kubernetes the pod never becomes ready.

It was found because the docker smoke test polled `/api/health/ready` 24 times
and got `failed_critical: ["db_pool"]` on every attempt. SQLite deployments were
unaffected and hid it: `:memory:` uses StaticPool/NullPool, which the guard
excluded, so the listeners were never reached in the test suite.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.pool import AsyncAdaptedQueuePool, QueuePool
from sqlalchemy.pool.events import PoolEvents

pytestmark = pytest.mark.unit

# A DSN that produces AsyncAdaptedQueuePool. Creating an engine does not open a
# connection, so no server is needed to reach the listener registration.
_QUEUEPOOL_DSN = "postgresql+asyncpg://u:p@127.0.0.1:59999/nonexistent"


def _valid_pool_events() -> set[str]:
    return {name for name in dir(PoolEvents) if not name.startswith("_")}


def test_overflow_and_timeout_are_not_sqlalchemy_pool_events():
    """The premise, pinned. If SQLAlchemy ever adds them, this fails and the
    listeners can be reinstated deliberately."""
    valid = _valid_pool_events()
    assert "overflow" not in valid
    assert "timeout" not in valid
    # Sanity: the events the pool really does emit.
    assert {"connect", "checkout", "checkin", "invalidate"} <= valid


@pytest.mark.parametrize("pool_cls", [QueuePool, AsyncAdaptedQueuePool])
def test_registering_the_missing_events_raises(pool_cls):
    """Not a hypothetical: this is the exception the old code produced, on the
    two pool classes its guard specifically allowed through."""
    from sqlalchemy.exc import InvalidRequestError

    with pytest.raises(InvalidRequestError, match="No such event 'overflow'"):
        event.listen(pool_cls, "overflow", lambda *a: None)


def test_the_pool_connects_on_a_queuepool_engine():
    """The regression. Before the fix this raised InvalidRequestError; SQLite
    could not catch it because :memory: never uses a QueuePool."""
    from database.async_connection import AsyncConnectionPool, AsyncPoolConfig

    async def _run() -> None:
        pool = AsyncConnectionPool(AsyncPoolConfig(database_url=_QUEUEPOOL_DSN, use_null_pool=False))
        await pool.connect()
        await pool.close()

    asyncio.run(_run())


def test_the_source_registers_no_unknown_pool_events():
    """Guards the whole module rather than the two names that were wrong, so a
    third invented event cannot be added the same way."""
    import ast
    import inspect
    import textwrap

    import database.async_connection as mod

    tree = ast.parse(textwrap.dedent(inspect.getsource(mod)))
    valid = _valid_pool_events()
    registered: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in ("listens_for", "listen"):
            continue
        # listens_for(target, "event") / listen(target, "event", fn)
        for arg in node.args[1:2]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                registered.append(arg.value)

    unknown = [e for e in registered if e not in valid]
    assert not unknown, (
        f"listeners registered for events SQLAlchemy does not define: {unknown}. Valid pool events are: {sorted(valid)}"
    )


def test_the_counters_are_still_present_but_documented_as_unfed():
    """`overflow_count` and `timeout_count` have no event source, so they stay
    at 0. They are kept because callers read them; the point is that nobody
    should believe a listener is feeding them."""
    from database.async_connection import AsyncPoolMetrics

    m = AsyncPoolMetrics()
    assert m.overflow_count == 0
    assert m.timeout_count == 0

    import inspect

    import database.async_connection as mod

    # Comment markers and line breaks are stripped before searching. Asserting
    # on raw source makes the test depend on where a wrapped comment happens to
    # break and on the `#` that continues it -- which is how the first two
    # versions of this assertion failed against source that said exactly the
    # right thing.
    src = " ".join(inspect.getsource(mod).replace("#", " ").split())
    assert "no event source" in src, "the reason these counters stay at zero is no longer written down next to them"
