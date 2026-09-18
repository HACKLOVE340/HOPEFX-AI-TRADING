"""D3 — `validate_proposal` must derive its verdict from checks it actually ran.

The status was an expression over the environment *name*:

    "status": "passed" if request.environment in {"sandbox", "paper"} else ...

and three of its five "checks" were the literals True. Nothing was inspected.
`execute_proposal` requires "a passed validation in the selected environment",
so the gate that guards execution was satisfiable by calling an endpoint that
could not say no. That is TODO item 12's defect (F104, a gate that cannot fail)
reproduced inside the AI Core.

These tests pin the inverse: a proposal that should not validate, does not.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest

import api.safe_agent_platform as sp


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    """Module-level state is shared; keep each test independent."""
    sp._PROPOSALS.clear()
    sp._APPROVALS.clear()
    yield
    sp._PROPOSALS.clear()
    sp._APPROVALS.clear()


@pytest.fixture(autouse=True)
def _working_config_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Give these tests a config store whose writes succeed.

    `_save_state` now raises 503 when a write fails (D5), and this environment
    has no database, so every endpoint that persists would 503 for a reason
    that has nothing to do with what is under test. The DB-failure path itself
    is covered deliberately in
    tests/unit/test_safe_platform_evidence_and_persistence.py.
    """
    written: dict[str, Any] = {}

    def _set(key: str, value: Any, changed_by: str = "system") -> bool:
        written[key] = value
        return True

    monkeypatch.setattr(sp.config_store, "set", _set)
    return written


def _user(sub: str = "operator-1", role: str = "admin") -> Any:
    return types.SimpleNamespace(sub=sub, role=role)


def _make_proposal(**overrides: Any) -> dict[str, Any]:
    body = {
        "title": "a proposal",
        "kind": "repair",
        "scope": "core",
        "reason": "testing",
        "changes": {"note": "nothing sensitive"},
    }
    body.update(overrides)
    created = asyncio.run(sp.create_proposal(sp.ProposalRequest(**body), _user()))
    return created["proposal"]


def _validate(proposal_id: str, environment: str = "sandbox") -> dict[str, Any]:
    return asyncio.run(
        sp.validate_proposal(
            sp.ValidationRequest(proposal_id=proposal_id, environment=environment),
            _user(),
        )
    )["validation"]


# ── the gate must be able to say no ───────────────────────────────────────────


def test_validation_fails_without_a_checkpoint_or_approval() -> None:
    proposal = _make_proposal()
    result = _validate(proposal["id"])
    assert result["status"] != "passed", "a proposal with no checkpoint and no approval validated as passed"


def test_the_environment_name_does_not_decide_the_verdict() -> None:
    """sandbox and paper both returned 'passed' regardless of the proposal."""
    proposal = _make_proposal(changes={"delete": "everything"})
    for environment in ("sandbox", "paper"):
        result = _validate(proposal["id"], environment)
        assert result["status"] != "passed", f"{environment} passed on its name alone"


def test_secret_shaped_changes_fail_the_redaction_check() -> None:
    proposal = _make_proposal(changes={"api_key": "sk-live-0123456789abcdef", "note": "rotate this"})
    result = _validate(proposal["id"])
    assert result["checks"]["secrets_redacted"] is False
    assert result["status"] != "passed"


def test_a_default_rollback_plan_is_not_a_rollback_plan() -> None:
    """The field defaults to boilerplate; accepting it asserts a plan nobody wrote."""
    proposal = _make_proposal()
    result = _validate(proposal["id"])
    assert result["checks"]["rollback_checkpoint_planned"] is False


# ── and it must still be able to say yes ──────────────────────────────────────


def test_a_sound_proposal_still_validates() -> None:
    """A gate that can never pass is as useless as one that can never fail."""
    proposal = _make_proposal(
        rollback_plan="Restore checkpoint ckpt-17 and re-run the risk gate suite.",
    )
    asyncio.run(sp.create_proposal_checkpoint(proposal["id"], _user()))
    # A repair's quorum must include a superadmin (plan Part 1B.2), so two
    # admins between them no longer complete it -- see
    # tests/unit/test_ai_control_plane_authorization.py.
    for approver, role in (("operator-1", "admin"), ("super-1", "superadmin")):
        asyncio.run(
            sp.decide_approval(
                sp.ApprovalRequest(proposal_id=proposal["id"], decision="approve", reason="reviewed"),
                _user(approver, role),
            )
        )
    result = _validate(proposal["id"])
    assert result["checks"]["checkpoint_present"] is True
    assert result["checks"]["human_approval_present"] is True
    assert result["checks"]["secrets_redacted"] is True
    assert result["checks"]["rollback_checkpoint_planned"] is True
    assert result["status"] == "passed"


def test_every_reported_check_is_a_real_observation() -> None:
    """No check may be a constant: each must vary with the proposal."""
    bare = _validate(_make_proposal()["id"])
    assert not all(bare["checks"].values()), (
        "every check reported True for a proposal with no checkpoint and no approval"
    )
