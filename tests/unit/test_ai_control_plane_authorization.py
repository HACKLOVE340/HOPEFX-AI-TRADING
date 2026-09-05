"""D7 — an admin must not be able to overtake a superadmin in the AI control plane.

All 24 endpoints in `api/safe_agent_platform.py` depended on
`require_role("admin")`. That is a **minimum-rank** check against
`starter 0, user 1, trader 2, admin 3, superadmin 4`, so rank 3 cleared every
gate: an admin could approve a proposal, execute it, roll it back, change the
model route, and authorize, revoke or rotate an integration's credentials.

Two rules close it (plan Part 1B): a repair's approval quorum must include a
superadmin, and approval and execution are different privileges with execution
behind 2FA.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from ai.policy import roles as policy

_MODULE = pathlib.Path("api/safe_agent_platform.py")

CONSEQUENTIAL = [
    "execute_proposal",
    "rollback_proposal",
    "route_model",
    "integration_action",
    "execute_supervisor_task",
]


def _endpoint_dependencies(name: str) -> set[str]:
    """The dependency callables an endpoint resolves, by name.

    Read from source rather than the live signature so the assertion is about
    what the module declares, not about what a patched import happens to be.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name != name:
            continue
        found: set[str] = set()
        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
        for default in defaults:
            src = ast.unparse(default)
            if src.startswith("Depends("):
                found.add(src[len("Depends(") : -1].strip())
        return found
    raise AssertionError(f"endpoint {name} not found in {_MODULE}")


# ── the matrix is complete and drift-proof ────────────────────────────────────


def test_every_endpoint_is_classified() -> None:
    """An unclassified endpoint has no declared authorization."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    endpoints = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
            for d in node.decorator_list
        )
    }
    unclassified = sorted(endpoints - set(policy.CAPABILITIES))
    assert not unclassified, f"endpoints with no capability row: {unclassified}"


# ── consequential actions are superadmin-only ─────────────────────────────────


@pytest.mark.parametrize("name", CONSEQUENTIAL)
def test_consequential_endpoints_are_not_reachable_by_admin(name: str) -> None:
    capability = policy.capability_for(name)
    assert capability is not None, f"{name} is unclassified"
    assert capability.min_role == "superadmin", f"{name} admits {capability.min_role}"
    assert capability.requires_2fa, f"{name} does not require 2FA"

    deps = _endpoint_dependencies(name)
    assert "_admin" not in deps, f"{name} still depends on _admin, which require_role('admin') admits at rank 3"
    assert deps, f"{name} declares no auth dependency at all"


@pytest.mark.parametrize("name", CONSEQUENTIAL)
def test_consequential_endpoints_use_the_2fa_dependency(name: str) -> None:
    """require_superadmin_2fa already exists; a stolen token must not reach these."""
    assert "_superadmin_2fa" in _endpoint_dependencies(name)


def test_execute_tier_admits_superadmin_only() -> None:
    """Asserted as an exact set: a future role above admin must not inherit this."""
    assert policy.ROLES_ADMITTED[policy.EXECUTE] == frozenset({"superadmin"})


# ── the quorum rule ───────────────────────────────────────────────────────────


def test_repair_quorum_requires_at_least_one_superadmin() -> None:
    assert policy.CAPABILITIES["decide_approval"].quorum_needs_superadmin is True
    assert "repair" in policy.QUORUM_NEEDS_SUPERADMIN_KINDS
    assert "upgrade" in policy.QUORUM_NEEDS_SUPERADMIN_KINDS


def test_two_admins_cannot_approve_a_repair_between_them() -> None:
    """The overtake case, end to end."""
    import asyncio
    import types

    import api.safe_agent_platform as sp

    sp._PROPOSALS.clear()
    sp._APPROVALS.clear()
    # _save_state raises 503 when a write fails (D5) and this environment has no
    # database; the DB-failure path is covered in
    # tests/unit/test_safe_platform_evidence_and_persistence.py.
    original_set = sp.config_store.set
    sp.config_store.set = lambda *a, **k: True
    try:
        admin_a = types.SimpleNamespace(sub="admin-a", role="admin")
        admin_b = types.SimpleNamespace(sub="admin-b", role="admin")
        created = asyncio.run(
            sp.create_proposal(
                sp.ProposalRequest(
                    title="a repair",
                    kind="repair",
                    scope="core",
                    reason="testing",
                    changes={"note": "x"},
                ),
                admin_a,
            )
        )
        pid = created["proposal"]["id"]
        for approver in (admin_a, admin_b):
            asyncio.run(
                sp.decide_approval(
                    sp.ApprovalRequest(proposal_id=pid, decision="approve", reason="reviewed"),
                    approver,
                )
            )
        proposal = next(p for p in sp._PROPOSALS if p["id"] == pid)
        assert proposal["status"] != "approved_pending_execution", (
            "two admins approved a repair between them with no superadmin"
        )
    finally:
        sp.config_store.set = original_set
        sp._PROPOSALS.clear()
        sp._APPROVALS.clear()


def test_a_superadmin_in_the_quorum_completes_the_approval() -> None:
    """The rule must still let a legitimate approval through."""
    import asyncio
    import types

    import api.safe_agent_platform as sp

    sp._PROPOSALS.clear()
    sp._APPROVALS.clear()
    # _save_state raises 503 when a write fails (D5) and this environment has no
    # database; the DB-failure path is covered in
    # tests/unit/test_safe_platform_evidence_and_persistence.py.
    original_set = sp.config_store.set
    sp.config_store.set = lambda *a, **k: True
    try:
        admin = types.SimpleNamespace(sub="admin-a", role="admin")
        superadmin = types.SimpleNamespace(sub="super-1", role="superadmin")
        created = asyncio.run(
            sp.create_proposal(
                sp.ProposalRequest(
                    title="a repair",
                    kind="repair",
                    scope="core",
                    reason="testing",
                    changes={"note": "x"},
                ),
                admin,
            )
        )
        pid = created["proposal"]["id"]
        for approver in (admin, superadmin):
            asyncio.run(
                sp.decide_approval(
                    sp.ApprovalRequest(proposal_id=pid, decision="approve", reason="reviewed"),
                    approver,
                )
            )
        proposal = next(p for p in sp._PROPOSALS if p["id"] == pid)
        assert proposal["status"] == "approved_pending_execution"
    finally:
        sp.config_store.set = original_set
        sp._PROPOSALS.clear()
        sp._APPROVALS.clear()


# ── read and propose tiers stay reachable by admins ───────────────────────────


def test_admins_keep_the_read_and_propose_tiers() -> None:
    """Gating must not lock operators out of the work they are meant to do."""
    for name in ("overview", "proposals", "create_proposal", "run_diagnostics"):
        capability = policy.capability_for(name)
        assert capability is not None and capability.min_role == "admin", name
