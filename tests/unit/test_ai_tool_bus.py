"""Task 9 — the MCP tool bus: the typed surface an agent acts through.

This is the task that gives two existing controls something to gate.

`invariants/enforcement.enforce_agent_action` holds sixteen CONSTITUTIONAL
predicates covering scoped actions, scoped tools, no self-escalation, hard
capital limits, no uncontrolled spawning and no strategy reaching production
without a human. Before this bus it had **no production caller at all** -- only
its own tests (audit F260). Its own docstring names the spec sentence it exists
to satisfy: "per agent permission scoping enforced at the tool layer, not just
prompted".

`core.ai_tool_permissions.ToolPermissionRegistry` had one importer and no bus.

Every tool call must pass BOTH. A tool that executes having passed only one of
them is the defect these tests exist to prevent.
"""

from __future__ import annotations

import pytest

from ai.tools.bus import ToolBus, ToolDenied, ToolResult
from core.ai_tool_permissions import ToolPermission, ToolPermissionRegistry, ToolRisk


def _registry() -> ToolPermissionRegistry:
    return ToolPermissionRegistry(
        [
            ToolPermission("read_positions", "v1", ToolRisk.READ_ONLY),
            ToolPermission("paper_order", "v1", ToolRisk.PAPER_TRADING),
            ToolPermission("place_order", "v1", ToolRisk.LIVE_TRADING, requires_approval=True),
            ToolPermission("rotate_key", "v1", ToolRisk.IRREVERSIBLE, requires_approval=True),
            ToolPermission("disabled_tool", "v1", ToolRisk.READ_ONLY, enabled=False),
        ],
        version="test-v1",
    )


def _bus(**kw: object) -> ToolBus:
    calls: list[str] = []

    def _read_positions(**_: object) -> dict:
        calls.append("read_positions")
        return {"positions": []}

    bus = ToolBus(registry=_registry(), **kw)  # type: ignore[arg-type]
    bus.register("read_positions", _read_positions, allowed_actions={"read_positions"})
    bus.register("paper_order", lambda **_: {"ok": True}, allowed_actions={"paper_order"})
    bus.register("place_order", lambda **_: {"ok": True}, allowed_actions={"place_order"})
    bus.register("rotate_key", lambda **_: {"ok": True}, allowed_actions={"rotate_key"})
    bus.register("disabled_tool", lambda **_: {"ok": True}, allowed_actions={"disabled_tool"})
    bus._calls = calls  # type: ignore[attr-defined]
    return bus


# ── both gates, always ────────────────────────────────────────────────────────


def test_a_read_only_tool_runs() -> None:
    result = _bus().invoke("read_positions", operator="op-1", allowed_actions={"read_positions"})
    assert isinstance(result, ToolResult)
    assert result.allowed is True


def test_an_unregistered_tool_is_refused() -> None:
    with pytest.raises(ToolDenied, match="tool_not_registered|not_registered"):
        _bus().invoke("no_such_tool", operator="op-1", allowed_actions={"no_such_tool"})


def test_a_disabled_tool_is_refused() -> None:
    with pytest.raises(ToolDenied):
        _bus().invoke("disabled_tool", operator="op-1", allowed_actions={"disabled_tool"})


def test_a_live_tool_without_approval_is_refused() -> None:
    with pytest.raises(ToolDenied):
        _bus().invoke("place_order", operator="op-1", allowed_actions={"place_order"})


def test_an_irreversible_tool_without_approval_is_refused() -> None:
    with pytest.raises(ToolDenied):
        _bus().invoke("rotate_key", operator="op-1", allowed_actions={"rotate_key"})


# ── the invariant layer must actually be consulted ────────────────────────────


def test_an_action_outside_the_agents_scope_is_refused() -> None:
    """The registry would allow this; enforce_agent_action must not."""
    with pytest.raises(ToolDenied):
        _bus().invoke("read_positions", operator="op-1", allowed_actions={"something_else"})


def test_an_agent_that_modified_its_own_permissions_is_refused() -> None:
    with pytest.raises(ToolDenied):
        _bus().invoke(
            "read_positions",
            operator="op-1",
            allowed_actions={"read_positions"},
            modified_own_permissions=True,
        )


def test_capital_beyond_the_agents_limit_is_refused() -> None:
    with pytest.raises(ToolDenied):
        _bus().invoke(
            "paper_order",
            operator="op-1",
            allowed_actions={"paper_order"},
            approved=True,
            capital_allocated=50_000.0,
            capital_limit=10_000.0,
        )


def test_the_invariant_layer_is_not_optional() -> None:
    """A bus that can skip enforcement is a bus that will."""
    import inspect

    from ai.tools import bus as bus_mod

    source = inspect.getsource(bus_mod.ToolBus.invoke)
    assert "enforce_agent_action" in source
    assert "review(" in source


def test_a_refusal_never_runs_the_tool() -> None:
    bus = _bus()
    with pytest.raises(ToolDenied):
        bus.invoke("read_positions", operator="op-1", allowed_actions={"nope"})
    assert bus._calls == [], "the tool ran despite being refused"  # type: ignore[attr-defined]


# ── audit ─────────────────────────────────────────────────────────────────────


def test_every_invocation_is_audited_including_refusals() -> None:
    bus = _bus()
    bus.invoke("read_positions", operator="op-1", allowed_actions={"read_positions"})
    with pytest.raises(ToolDenied):
        bus.invoke("place_order", operator="op-1", allowed_actions={"place_order"})
    kinds = [entry["allowed"] for entry in bus.audit()]
    assert kinds == [True, False], "a refusal left no trace"


def test_the_audit_records_which_gate_refused() -> None:
    bus = _bus()
    with pytest.raises(ToolDenied):
        bus.invoke("place_order", operator="op-1", allowed_actions={"place_order"})
    assert bus.audit()[-1]["reason_codes"], "no reason recorded for the refusal"


def test_the_bus_refuses_even_in_monitor_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """The global invariant default is MONITOR, where `allowed` stays True.

    Honouring `allowed` would make the invariant gate advisory on a default
    deployment -- a control that exists and does not fire, which is precisely
    what this bus was built to stop. The staged-rollout rationale for monitor
    mode is to avoid breaking EXISTING trading paths while checks are proven;
    this bus is new and has none to protect.
    """
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    from invariants.enforcement import current_mode

    assert current_mode() == "monitor"
    with pytest.raises(ToolDenied):
        _bus().invoke("read_positions", operator="op-1", allowed_actions={"not_this_one"})


def test_a_permitted_but_unimplemented_tool_is_refused() -> None:
    """A permitted-but-absent tool must not read as a successful no-op."""
    bus = ToolBus(registry=_registry())  # nothing registered
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke("read_positions", operator="op-1", allowed_actions={"read_positions"})
    assert "tool_not_implemented" in excinfo.value.reason_codes


def test_enforce_agent_action_now_has_a_production_caller() -> None:
    """F260: sixteen constitutional predicates with no production call site."""
    import subprocess

    out = subprocess.run(
        ["git", "grep", "-l", "enforce_agent_action", "--", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    production = [p for p in out if not p.startswith("tests/") and "invariants/" not in p]
    assert production, "enforce_agent_action still has no production caller"
