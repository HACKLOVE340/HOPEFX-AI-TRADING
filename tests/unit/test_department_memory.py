# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Departments declared a memory and had none.

`ai/departments/__init__.py` gives every department a `memory` field typed
`tuple[str, ...]` — "execution/fill history", "slippage per symbol", "drawdown
curve", "past violations". Those are labels on a dataclass. Grep the tree for a
store, a writer, or a recall and nothing comes back.

Spec §2's four-part anatomy is `agent/`, `actions/`, `memory/`, `awareness/`.
Only `actions/` was ever built, so what exists today is a permissioned
remote-procedure surface with four labelled groupings — it cannot remember a
conversation, notice anything on its own, or reason about what it observed.

**Structured recall, not semantic.** Every use the spec actually names is
"what happened, in this department, of this kind, most recently" — fill history,
a drawdown curve, past violations, model version history. None of that wants
vector search; it wants typed, time-ordered, filterable recall. `pgvector` is
not a dependency of this repo and adding one for a capability nothing asked for
would be the wrong trade. The interface leaves room for semantic recall later —
`GatewayClient.embed_sync` already exists for that half.

These tests fail on the pre-fix tree — `ai.memory` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.memory import store

    store.reset_for_testing()
    yield
    store.reset_for_testing()


# ── writing and reading ───────────────────────────────────────────────────────


def test_a_department_can_remember_and_recall():
    from ai.memory.store import recall, remember

    remember("risk_compliance", "violation", {"rule": "daily_drawdown", "pct": 5.4})
    out = recall("risk_compliance", kind="violation")

    assert len(out) == 1
    assert out[0]["value"]["rule"] == "daily_drawdown"


def test_recall_is_newest_first():
    """An agent asking "what happened" wants the latest, not the oldest."""
    from ai.memory.store import recall, remember

    for i in range(3):
        remember("markets_execution", "fill", {"seq": i})

    seqs = [row["value"]["seq"] for row in recall("markets_execution", kind="fill")]
    assert seqs == [2, 1, 0]


def test_departments_do_not_see_each_others_memory():
    """Scoping is the point: Risk must not read Platform's audit history."""
    from ai.memory.store import recall, remember

    remember("risk_compliance", "note", {"a": 1})
    remember("platform_engineering", "note", {"b": 2})

    assert len(recall("risk_compliance")) == 1
    assert recall("risk_compliance")[0]["value"] == {"a": 1}


def test_recall_can_filter_by_kind():
    from ai.memory.store import recall, remember

    remember("research_intelligence", "regime", {"r": "high_vol"})
    remember("research_intelligence", "oos_accuracy", {"acc": 0.599})

    assert len(recall("research_intelligence")) == 2
    assert len(recall("research_intelligence", kind="regime")) == 1


def test_recall_respects_a_limit():
    from ai.memory.store import recall, remember

    for i in range(20):
        remember("markets_execution", "fill", {"seq": i})
    assert len(recall("markets_execution", kind="fill", limit=5)) == 5


def test_an_unknown_department_is_refused_rather_than_silently_created():
    """A typo must not open a new memory nobody ever reads."""
    from ai.memory.store import remember

    with pytest.raises(ValueError):
        remember("markets_excution", "fill", {"seq": 1})  # deliberate typo


def test_recall_of_an_empty_memory_is_empty_not_an_error():
    from ai.memory.store import recall

    assert recall("platform_engineering", kind="never_written") == []


# ── retention ─────────────────────────────────────────────────────────────────


def test_memory_is_capped_per_kind():
    """Memory that only grows becomes a cost and a liability."""
    from ai.memory.store import MAX_PER_KIND, recall, remember

    for i in range(MAX_PER_KIND + 50):
        remember("markets_execution", "fill", {"seq": i})

    rows = recall("markets_execution", kind="fill", limit=MAX_PER_KIND + 100)
    assert len(rows) <= MAX_PER_KIND


def test_the_cap_drops_the_oldest_not_the_newest():
    from ai.memory.store import MAX_PER_KIND, recall, remember

    for i in range(MAX_PER_KIND + 10):
        remember("markets_execution", "fill", {"seq": i})

    rows = recall("markets_execution", kind="fill", limit=MAX_PER_KIND + 100)
    seqs = [r["value"]["seq"] for r in rows]
    assert max(seqs) == MAX_PER_KIND + 9, "the newest entry was dropped"
    assert min(seqs) > 0, "the oldest entries were not trimmed"


def test_one_kind_filling_up_does_not_evict_another():
    from ai.memory.store import MAX_PER_KIND, recall, remember

    remember("markets_execution", "heartbeat", {"ok": True})
    for i in range(MAX_PER_KIND + 20):
        remember("markets_execution", "fill", {"seq": i})

    assert len(recall("markets_execution", kind="heartbeat")) == 1


# ── safety ────────────────────────────────────────────────────────────────────


def test_remembered_text_is_screened_for_credentials():
    """Memory is durable. A credential written here outlives the conversation."""
    from ai.guardrails.output import GuardrailViolation
    from ai.memory.store import remember

    with pytest.raises(GuardrailViolation):
        remember("platform_engineering", "note", {"found": "sk-ant-api03-" + "A" * 32})


def test_a_value_that_is_not_json_serialisable_is_refused():
    from ai.memory.store import remember

    with pytest.raises(ValueError):
        remember("risk_compliance", "note", {"when": object()})


# ── the bus ───────────────────────────────────────────────────────────────────


def test_recall_is_reachable_as_a_department_action():
    """Recall must inherit the two gates, not become a second door.

    Every other capability an agent has goes through ToolBus.invoke — the
    permission registry, then `enforce_agent_action`. A recall function callable
    directly from anywhere would be a way around both.
    """
    from ai.departments import all_actions

    names = {a.name for a in all_actions()}
    assert "risk_compliance.recall_memory" in names, "recall is not registered as a department action"


def test_every_department_gets_a_recall_action():
    from ai.departments import DEPARTMENTS, all_actions

    names = {a.name for a in all_actions()}
    for key in DEPARTMENTS:
        assert f"{key}.recall_memory" in names, f"{key} has no recall action"


def test_recall_actions_are_read_only():
    from ai.departments import all_actions
    from core.ai_tool_permissions import ToolRisk

    for action in all_actions():
        if action.name.endswith(".recall_memory"):
            assert action.risk == ToolRisk.READ_ONLY
            assert action.requires_approval is False


def test_recall_through_the_bus_returns_that_departments_memory_only():
    from ai.departments import build_tool_bus
    from ai.memory.store import remember

    remember("risk_compliance", "violation", {"rule": "daily_drawdown"})
    remember("platform_engineering", "note", {"unrelated": True})

    bus = build_tool_bus(live_mode=False)
    result = bus.invoke(
        "risk_compliance.recall_memory",
        operator="owner",
        allowed_actions={"risk_compliance.recall_memory"},
    )
    rows = result.value["entries"]
    assert len(rows) == 1
    assert rows[0]["value"]["rule"] == "daily_drawdown"


# ── the durable backend ───────────────────────────────────────────────────────
# Everything above proves the contract against the in-process deque. These drive
# the real SqlMemoryBackend against SQLite, so the implementation is not shipped
# on the strength of a stand-in that shares none of its code.


@pytest.fixture
def sql_backed():
    """A real session factory over an in-memory SQLite database."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from ai.memory import store
    from ai.memory.sql_backend import SqlMemoryBackend
    from database.models import Base, DepartmentMemoryEntry

    engine = sa.create_engine("sqlite://")
    DepartmentMemoryEntry.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    store.set_backend(SqlMemoryBackend(factory))
    assert Base  # the model is registered on the shared metadata
    yield
    store.set_backend(None)
    engine.dispose()


def test_the_sql_backend_round_trips_an_entry(sql_backed):
    from ai.memory.store import recall, remember

    remember("risk_compliance", "violation", {"rule": "daily_drawdown", "pct": 5.4})
    rows = recall("risk_compliance", kind="violation")

    assert len(rows) == 1
    assert rows[0]["value"]["pct"] == 5.4
    assert rows[0]["at"], "the stored row has no timestamp"


def test_sql_recall_is_newest_first(sql_backed):
    from ai.memory.store import recall, remember

    for i in range(4):
        remember("markets_execution", "fill", {"seq": i})
    assert [r["value"]["seq"] for r in recall("markets_execution", kind="fill")] == [3, 2, 1, 0]


def test_sql_recall_is_scoped_to_one_department(sql_backed):
    from ai.memory.store import recall, remember

    remember("risk_compliance", "note", {"a": 1})
    remember("platform_engineering", "note", {"b": 2})

    rows = recall("risk_compliance")
    assert len(rows) == 1 and rows[0]["value"] == {"a": 1}


def test_sql_recall_can_filter_by_kind(sql_backed):
    from ai.memory.store import recall, remember

    remember("research_intelligence", "regime", {"r": "high_vol"})
    remember("research_intelligence", "oos_accuracy", {"acc": 0.599})

    assert len(recall("research_intelligence")) == 2
    assert len(recall("research_intelligence", kind="regime")) == 1


def test_survives_a_restart_of_the_process(sql_backed):
    """The whole point of the backend."""
    from ai.memory import store

    store.remember("risk_compliance", "violation", {"rule": "daily_drawdown"})

    # A restart: the in-process deques are gone, the table is not.
    backend = store._BACKEND
    store._ENTRIES.clear()
    store.set_backend(backend)

    rows = store.recall("risk_compliance", kind="violation")
    assert len(rows) == 1, "memory did not survive the restart"


def test_a_backend_write_failure_does_not_fail_the_caller(caplog):
    """Memory is not on the trading path — but the failure is not silent."""
    import logging

    from ai.memory import store

    class _Broken:
        def write(self, entry):
            raise RuntimeError("database is gone")

        def read(self, department, *, kind=None, limit=50):
            raise RuntimeError("database is gone")

    store.set_backend(_Broken())
    with caplog.at_level(logging.ERROR):
        entry = store.remember("risk_compliance", "note", {"a": 1})

    assert entry["value"] == {"a": 1}, "a backend fault failed the caller"
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_a_backend_read_failure_falls_back_to_the_process(caplog):
    import logging

    from ai.memory import store

    class _WriteOnly:
        def write(self, entry):
            return None

        def read(self, department, *, kind=None, limit=50):
            raise RuntimeError("database is gone")

    store.set_backend(_WriteOnly())
    store.remember("risk_compliance", "note", {"a": 1})

    with caplog.at_level(logging.ERROR):
        rows = store.recall("risk_compliance", kind="note")

    assert len(rows) == 1, "a read failure lost the in-process copy too"


def test_the_health_surface_can_tell_whether_memory_is_durable(sql_backed):
    from ai.memory.store import backend_is_durable

    assert backend_is_durable() is True


# ── the wiring ────────────────────────────────────────────────────────────────


def test_a_startup_factory_exists_and_is_registered():
    import pathlib

    import core.startup_factories as F

    assert hasattr(F, "init_ai_memory"), "no startup factory for department memory"
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_memory" in src, "the factory is defined but never registered"
