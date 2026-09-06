# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Risk & Compliance — the second department, and where it stops.

Spec §4 Cluster A. Two of its four actions are implemented and two are
deliberately not, and the line between them is the point of this module.

**Implemented, because they only ask questions.** `check_drawdown` and
`validate_position_size` delegate to `RiskManager.check_drawdown` and
`RiskManager.check_position_size` — real methods returning a real
`RiskCheckResult`. An agent may read the risk state all day; reading changes
nothing.

**Not implemented, because there is nothing honest to call yet.**
`block_deploy` and `propose_derisk` are declared with their risk tiers and have
no handler. `block_deploy` would have to actually stop a rollout, and this
repository has no deploy-block mechanism to call — so a handler would either
invent one under time pressure or, far worse, return success for a deploy it did
not block. That is the exact defect this audit keeps finding, and a declared
action the bus refuses with `tool_not_implemented` is the honest alternative.

The read handlers never fabricate. A risk manager that is absent, or a check
that raises, returns `available: False` with the reason — never a drawdown
figure nobody measured. An agent told "drawdown is 2%" by a handler that could
not reach the risk manager would be reasoning from fiction.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai import departments
from ai.departments import risk_compliance
from core.ai_tool_permissions import ToolRisk

pytestmark = pytest.mark.unit


# ── what is implemented, and what deliberately is not ────────────────────────


def test_the_read_only_actions_are_implemented():
    for name in ("risk_compliance.check_drawdown", "risk_compliance.validate_position_size"):
        assert departments.action_by_name(name).handler is not None, name


def test_the_acting_actions_are_still_unimplemented():
    """Declared, tiered, and refused by the bus until there is something real to call."""
    for name in ("risk_compliance.block_deploy", "risk_compliance.propose_derisk"):
        assert departments.action_by_name(name).handler is None, name


def test_block_deploy_is_irreversible_and_needs_approval():
    action = departments.action_by_name("risk_compliance.block_deploy")
    assert action.risk is ToolRisk.IRREVERSIBLE
    assert action.requires_approval is True


def test_the_bus_now_carries_two_departments():
    bus = departments.build_tool_bus()
    registered = set(bus._tools)
    assert "research_intelligence.score_regime" in registered
    assert "risk_compliance.check_drawdown" in registered
    assert "risk_compliance.block_deploy" not in registered


# ── the handlers delegate, and refuse honestly ───────────────────────────────


def test_check_drawdown_reports_what_the_risk_manager_returned():
    manager = MagicMock()
    manager.check_drawdown.return_value = MagicMock(passed=True, reason="within limits")
    result = risk_compliance.check_drawdown(risk_manager=manager)
    assert result["available"] is True
    assert result["passed"] is True
    manager.check_drawdown.assert_called_once()


def test_check_drawdown_without_a_risk_manager_says_so(monkeypatch):
    """No risk manager is not "no drawdown".

    `risk_manager=None` means "resolve the process-wide one", which is the
    right production behaviour — an agent should not have to carry a manager
    around. So the no-manager path is forced here by making resolution fail,
    rather than by passing None and assuming that means absent. The first
    version of this test conflated the two and failed against correct code.
    """
    monkeypatch.setattr(risk_compliance, "_resolve_manager", lambda _rm: None)
    result = risk_compliance.check_drawdown(risk_manager=None)
    assert result["available"] is False
    assert "risk_manager" in result["reason"]
    assert "passed" not in result, "an unavailable check must not answer the question"


def test_a_check_that_raises_is_reported_not_swallowed():
    manager = MagicMock()
    manager.check_drawdown.side_effect = RuntimeError("state lock timeout")
    result = risk_compliance.check_drawdown(risk_manager=manager)
    assert result["available"] is False
    assert "state lock timeout" in result["reason"]


def test_validate_position_size_refuses_without_a_trade():
    """Validating a trade nobody supplied would answer about nothing."""
    result = risk_compliance.validate_position_size(risk_manager=MagicMock(), trade=None)
    assert result["available"] is False
    assert "trade_required" in result["reason"]


def test_validate_position_size_passes_the_trade_through():
    manager = MagicMock()
    manager.check_position_size.return_value = MagicMock(passed=False, reason="size_too_large")
    trade = {"symbol": "XAUUSD", "quantity": 500.0}
    result = risk_compliance.validate_position_size(risk_manager=manager, trade=trade)
    assert result["available"] is True
    assert result["passed"] is False
    assert result["reason"] == "size_too_large"
    assert (
        manager.check_position_size.call_args.args[0] is trade
        or manager.check_position_size.call_args.kwargs.get("trade") is trade
    )


def test_a_refusal_never_reads_as_a_pass(monkeypatch):
    """The failure mode that matters: unavailable must not look like approved."""
    monkeypatch.setattr(risk_compliance, "_resolve_manager", lambda _rm: None)
    for result in (
        risk_compliance.check_drawdown(risk_manager=None),
        risk_compliance.validate_position_size(risk_manager=None, trade={"a": 1}),
        risk_compliance.validate_position_size(risk_manager=None, trade=None),
    ):
        assert result.get("passed") is not True
        assert result["available"] is False


# ── through the bus, end to end ──────────────────────────────────────────────


def test_check_drawdown_runs_through_the_bus_and_is_audited():
    """The end-to-end path: registry -> scope gate -> handler -> audit."""
    bus = departments.build_tool_bus()
    result = bus.invoke(
        "risk_compliance.check_drawdown",
        operator="tester",
        allowed_actions={"risk_compliance.check_drawdown"},
    )
    assert result.allowed is True
    # Whatever the resolved manager answered, the shape is honest: either a
    # real verdict or an explicit unavailability. Never a bare number.
    assert "available" in result.value
    if result.value["available"]:
        assert isinstance(result.value["passed"], bool)
    assert any(row["tool"] == "risk_compliance.check_drawdown" for row in bus.audit())


def test_block_deploy_is_refused_by_the_bus():
    from ai.tools.bus import ToolDenied

    bus = departments.build_tool_bus()
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke(
            "risk_compliance.block_deploy",
            operator="tester",
            allowed_actions={"risk_compliance.block_deploy"},
        )
    # Approval is demanded before implementation is even consulted.
    assert excinfo.value.reason_codes
