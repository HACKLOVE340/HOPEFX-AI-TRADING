# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_dynamic_registry_is_memory_only.py
==================================================
`DynamicStrategyRegistry` reads as if it persists registered strategies. It does
not, and it never has — the database path is dead for three independent reasons:

1. **No model.** `_load_from_database` and `_persist_version` both did
   `from database.models import DynamicStrategy`. There is no such class in
   `database/models.py`, which defines nineteen models and not that one.
2. **No table.** Nothing under `alembic/` references a dynamic-strategy table,
   so even a correct model would have nowhere to write.
3. **No session factory.** `_db_session_factory` is only assigned by
   `DynamicStrategyRegistry.start()`, and **`start()` is called from nowhere** —
   in production or in tests. `api/dynamic_strategies.py` reaches the registry
   through `get_dynamic_registry()`, which constructs the singleton lazily and
   never starts it. Both persistence methods therefore return at their first
   guard, before the missing import is ever reached.

`_redis` is set by the same unused `start()`, so cross-pod sync is inert too.
Registered strategies live in `self._versions` and `self._active` and are lost
on restart, while `POST /api/dynamic-strategies/register` reports success.

**Why this is not simply "add the model and a migration".**
`/register` accepts `source_code: str` — Python source, which the registry
compiles via `_compile_strategy` after `_validate_safety`. Turning persistence
on means user-supplied Python is stored in the database and **re-compiled on
every startup**: `_load_from_database` does exactly that, calling
`_compile_strategy` on each record whose state is ACTIVE. That converts any
future gap in `_validate_safety` from a live-process problem into a persistent
one that survives restarts. Whether this product wants that is a decision for
its owner, not a repair to be made silently while fixing an import.

So the dead database code is removed and the memory-only behaviour is stated
plainly. The methods and their call sites stay, so wiring persistence later is
a matter of filling them in rather than rediscovering where they belong. See
S-51 in docs/HARDENING_BACKLOG.md.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

pytestmark = pytest.mark.unit


def test_there_is_still_no_dynamic_strategy_model():
    """If a model is ever added this fails, which is the signal to wire persistence."""
    from database import models

    assert not hasattr(models, "DynamicStrategy"), (
        "a DynamicStrategy model now exists — revisit S-51 before enabling the "
        "database path, because loading it re-compiles stored Python at startup"
    )


def test_the_registry_singleton_has_no_persistence_wired():
    """get_dynamic_registry() never calls start(), so both backends are None."""
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()

    assert registry._db_session_factory is None
    assert registry._redis is None


def test_persistence_methods_no_longer_import_a_missing_model():
    """Regression: both bodies imported database.models.DynamicStrategy."""
    from strategies.dynamic_registry import DynamicStrategyRegistry

    for method in (
        DynamicStrategyRegistry._load_from_database,
        DynamicStrategyRegistry._persist_version,
    ):
        source = inspect.getsource(method)
        assert "from database.models import DynamicStrategy" not in source, (
            f"{method.__name__} still imports a model that does not exist"
        )


def test_load_from_database_is_a_safe_no_op():
    """It runs on every registry start and on every cross-pod sync event."""
    from strategies.dynamic_registry import DynamicStrategyRegistry

    registry = DynamicStrategyRegistry()
    asyncio.run(registry._load_from_database())  # must not raise

    assert registry._versions == {}
    assert registry._active == {}


def test_persist_version_is_a_safe_no_op():
    """It runs on register, activate and deactivate — four call sites."""
    from strategies.dynamic_registry import DynamicStrategyRegistry, StrategyState, StrategyVersion

    registry = DynamicStrategyRegistry()
    version = StrategyVersion(
        version_id="v-test",
        name="test_strategy",
        source_code="# noop\n",
        source_hash="deadbeef",
        symbol="XAU_USD",
        timeframe="M15",
        author_id="tester",
        state=StrategyState.DRAFT,
    )

    asyncio.run(registry._persist_version(version))  # must not raise


def test_a_registered_strategy_is_held_in_memory_only():
    """The behaviour the API actually delivers, pinned so it cannot drift silently."""
    from strategies.dynamic_registry import DynamicStrategyRegistry

    first = DynamicStrategyRegistry()
    second = DynamicStrategyRegistry()

    first._versions["v-1"] = object()

    assert second._versions == {}, (
        "state leaked between instances — registered strategies are per-process "
        "memory and a second process must not see the first's"
    )
