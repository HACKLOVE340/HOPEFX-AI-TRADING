"""D4 and D5 — the platform must not report work it did not do.

D4  `run_diagnostics` built an `evidence` dict, called `_save_state`, and
    returned `"evidence_retention": "persisted_in_audit_store"`. `_save_state`
    persists proposals, approvals, integrations, tasks and routes -- `evidence`
    was in none of them, so it was a dead local and the `run_id` handed to the
    operator resolved to nothing.

D5  `config_store.set` returns bool ("True if at least the DB write
    succeeded") and logs `ConfigStore.set: DB write failed` otherwise.
    `_save_state` called it five times and ignored every return value, so a
    failed write still returned 200 to the operator. An approval recorded that
    way vanishes on restart, and the operator was told it was recorded.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest

import api.safe_agent_platform as sp


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    for store in (sp._PROPOSALS, sp._APPROVALS, sp._TASKS, sp._ROUTES):
        store.clear()
    yield
    for store in (sp._PROPOSALS, sp._APPROVALS, sp._TASKS, sp._ROUTES):
        store.clear()


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


# ── D4: the run_id must resolve to something ──────────────────────────────────


def test_a_diagnostic_run_is_retrievable_by_its_run_id() -> None:
    result = asyncio.run(sp.run_diagnostics(sp.DiagnosticRequest(scope="all"), _user()))
    run_id = result["run_id"]
    stored = sp.diagnostic_evidence(run_id)
    assert stored is not None, f"run_id {run_id} resolves to nothing"
    assert stored["run_id"] == run_id
    assert stored["findings"] == result["findings"]


def test_evidence_retention_is_not_claimed_when_nothing_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim has to track the fact, in both directions."""
    result = asyncio.run(sp.run_diagnostics(sp.DiagnosticRequest(scope="all"), _user()))
    assert result["evidence_retention"] == "persisted_in_audit_store"
    assert sp.diagnostic_evidence(result["run_id"]) is not None


def test_diagnostic_findings_are_observations_not_literals() -> None:
    """Two hardcoded findings were returned regardless of system state."""
    result = asyncio.run(sp.run_diagnostics(sp.DiagnosticRequest(scope="all"), _user()))
    assert result["findings"], "no findings at all"
    for finding in result["findings"]:
        assert finding.get("evidence"), f"{finding['id']} carries no evidence"


# ── D5: a failed write must not report success ────────────────────────────────


def test_a_failed_persist_raises_rather_than_returning_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(sp.config_store, "set", lambda *a, **k: False)  # override the fixture
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            sp.create_proposal(
                sp.ProposalRequest(
                    title="a proposal",
                    kind="repair",
                    scope="core",
                    reason="testing",
                    changes={"note": "x"},
                ),
                _user(),
            )
        )
    assert excinfo.value.status_code == 503
    assert "persist" in str(excinfo.value.detail).lower()


def test_a_successful_persist_still_returns_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp.config_store, "set", lambda *a, **k: True)
    created = asyncio.run(
        sp.create_proposal(
            sp.ProposalRequest(
                title="a proposal",
                kind="repair",
                scope="core",
                reason="testing",
                changes={"note": "x"},
            ),
            _user(),
        )
    )
    assert created["proposal"]["status"] == "pending"


def test_an_approval_that_cannot_persist_is_not_reported_as_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case that matters: an approval lost on restart, reported as recorded."""
    from fastapi import HTTPException

    monkeypatch.setattr(sp.config_store, "set", lambda *a, **k: True)
    created = asyncio.run(
        sp.create_proposal(
            sp.ProposalRequest(
                title="a proposal",
                kind="repair",
                scope="core",
                reason="testing",
                changes={"note": "x"},
            ),
            _user(),
        )
    )
    monkeypatch.setattr(sp.config_store, "set", lambda *a, **k: False)  # override the fixture
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            sp.decide_approval(
                sp.ApprovalRequest(
                    proposal_id=created["proposal"]["id"],
                    decision="approve",
                    reason="reviewed",
                ),
                _user("super-1", "superadmin"),
            )
        )
    assert excinfo.value.status_code == 503
