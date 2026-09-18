# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Let the agent decide, and let nothing happen.

`place_order` and `cancel_order` are the only two actions in Cluster A that can
lose money, and they are deliberately unimplemented — the build order put them
last, after the permission tiers and the audit trail had been exercised by
departments that cannot.

That leaves a gap. Nobody can see whether the agent's *decisions* are any good
until the handlers exist, and by then the first evidence arrives attached to a
real order. Shadow mode closes it: the agent proposes exactly what it would do,
against live market conditions, and nothing is sent.

**Shadow is a different tool, not a mode on the real one.** A `dry_run=True`
parameter is one config edit, one default flip, or one forgotten argument away
from a live order. `shadow_place_order` is its own action with its own handler
that does not import a broker, so "shadow accidentally went live" is not a
thing that can happen — it is the same reasoning as `ai/awareness` not importing
the tool bus.

These tests fail on the pre-fix tree — `ai.execution_shadow` does not exist.
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


ORDER = {"symbol": "XAUUSD", "side": "buy", "quantity": 0.5, "order_type": "market"}


# ── it cannot reach a broker ──────────────────────────────────────────────────


def test_the_shadow_module_does_not_import_a_broker():
    """Structural, not a promise.

    Checks the module's import graph rather than grepping for substrings — an
    earlier version of this test scanned for "place_order(" and flagged the
    module's own `def shadow_place_order(`. What matters is not whether the
    words appear but whether anything that can SEND is reachable from here.
    """
    import ast
    import pathlib

    import ai.execution_shadow as m

    tree = ast.parse(pathlib.Path(m.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden = ("brokers", "execution.oms", "execution.smart_router", "execution.fix_adapter")
    for name in imported:
        for bad in forbidden:
            assert not name.startswith(bad), f"the shadow module imports {name!r}, which can send an order"


def test_shadow_is_a_separate_action_from_the_real_one():
    """A dry_run flag would be one default flip away from a live order."""
    from ai.departments import all_actions

    names = {a.name for a in all_actions()}
    assert "markets_execution.shadow_place_order" in names
    assert "markets_execution.place_order" in names, "the real action must still exist and stay unimplemented"


def test_the_real_write_actions_are_still_unimplemented():
    """Shadow mode must not have quietly filled them in."""
    from ai.departments import action_by_name

    for name in ("markets_execution.place_order", "markets_execution.cancel_order"):
        assert action_by_name(name).handler is None, f"{name} gained a handler"


def test_shadow_actions_are_read_only():
    """They touch nothing, so they are not LIVE_TRADING and need no approval."""
    from ai.departments import all_actions
    from core.ai_tool_permissions import ToolRisk

    for action in all_actions():
        if ".shadow_" in action.name:
            assert action.risk == ToolRisk.READ_ONLY, f"{action.name} is not read-only"
            assert action.requires_approval is False


# ── what it produces ──────────────────────────────────────────────────────────


def test_a_shadow_order_reports_what_it_would_have_done():
    from ai.execution_shadow import shadow_place_order

    result = shadow_place_order(**ORDER)

    assert result["shadow"] is True
    assert result["would_have"]["symbol"] == "XAUUSD"
    assert result["would_have"]["quantity"] == 0.5
    assert result["sent"] is False


def test_the_result_says_plainly_that_nothing_was_sent():
    """An operator skimming a log must not mistake this for a fill."""
    from ai.execution_shadow import shadow_place_order

    result = shadow_place_order(**ORDER)
    assert "no order was sent" in result["note"].lower()


def test_a_shadow_order_never_returns_an_order_id():
    """An id is what downstream code keys a real position on."""
    from ai.execution_shadow import shadow_place_order

    result = shadow_place_order(**ORDER)
    for key in ("order_id", "id", "ticket", "fill_id"):
        assert key not in result, f"a shadow result carries {key!r}, which reads as a real order"


def test_a_shadow_order_is_recorded_in_department_memory():
    """The whole point: an evidence trail of decisions."""
    from ai.execution_shadow import shadow_place_order
    from ai.memory.store import recall

    shadow_place_order(**ORDER)
    entries = recall("markets_execution", kind="shadow_order")

    assert len(entries) == 1
    assert entries[0]["value"]["would_have"]["side"] == "buy"


def test_the_risk_gate_verdict_is_recorded_alongside_the_intent():
    """The question shadow mode exists to answer is not "what did it want" but
    "would the platform have allowed it". Without the verdict, the trail says
    nothing about whether the decision was safe."""
    from ai.execution_shadow import shadow_place_order

    result = shadow_place_order(**ORDER)
    assert "risk_verdict" in result
    assert "allowed" in result["risk_verdict"]


def test_a_shadow_cancel_reports_the_same_way():
    from ai.execution_shadow import shadow_cancel_order

    result = shadow_cancel_order(order_id="88213")
    assert result["shadow"] is True
    assert result["sent"] is False
    assert result["would_have"]["order_id"] == "88213"


# ── validation ────────────────────────────────────────────────────────────────


def test_an_invalid_side_is_refused_rather_than_recorded():
    """A shadow trail full of impossible orders is worthless as evidence."""
    from ai.execution_shadow import shadow_place_order

    with pytest.raises(ValueError):
        shadow_place_order(symbol="XAUUSD", side="sideways", quantity=1.0)


def test_a_non_positive_quantity_is_refused():
    from ai.execution_shadow import shadow_place_order

    with pytest.raises(ValueError):
        shadow_place_order(symbol="XAUUSD", side="buy", quantity=0.0)


def test_a_missing_symbol_is_refused():
    from ai.execution_shadow import shadow_place_order

    with pytest.raises(ValueError):
        shadow_place_order(symbol="", side="buy", quantity=1.0)


def test_a_refused_shadow_order_is_not_written_to_memory():
    from ai.execution_shadow import shadow_place_order
    from ai.memory.store import recall

    with pytest.raises(ValueError):
        shadow_place_order(symbol="XAUUSD", side="sideways", quantity=1.0)
    assert recall("markets_execution", kind="shadow_order") == []


# ── through the bus ───────────────────────────────────────────────────────────


def test_the_agent_can_run_a_shadow_order_through_the_bus():
    from ai.departments import build_tool_bus

    bus = build_tool_bus(live_mode=False)
    result = bus.invoke(
        "markets_execution.shadow_place_order",
        operator="owner",
        allowed_actions={"markets_execution.shadow_place_order"},
        **ORDER,
    )
    assert result.value["shadow"] is True
    assert result.value["sent"] is False


def test_the_agentic_loop_may_choose_a_shadow_order():
    """Read-only, so it is inside the loop's computed allowlist — which is the
    point: the agent gets to make execution decisions with nothing at stake."""
    from ai.agent.loop import permitted_actions

    assert "markets_execution.shadow_place_order" in permitted_actions("markets_execution")


def test_the_loop_still_cannot_choose_the_real_order():
    from ai.agent.loop import permitted_actions

    permitted = permitted_actions("markets_execution")
    assert "markets_execution.place_order" not in permitted
    assert "markets_execution.cancel_order" not in permitted
