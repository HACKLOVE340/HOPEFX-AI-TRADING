# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A walker finding becomes a candidate patch, and two humans decide.

Owner request, 2026-09-07: any improvement, any advancement, should be
approved.

## What the plan for this phase said, and what the code actually does

The plan said: finding → vault check → sandbox → **signed** queue entry → the
two-approver gate → `SelfHealer` applies it. Two of those were wrong, and
running the code is what showed it.

**`SelfHealer`'s auto-apply path is inert in every configuration.** Nothing in
this repository ever signs a patch entry — `_sign_patch` has no production
caller, only tests — and the three places that write to `fixes:approved`
(`api/security/fixes.py`, `api/superadmin/auto_healing.py`,
`security/global_fortress.py`) all push unsigned records. Measured:

    with HEAL_PATCH_SIGNING_KEY set   -> _patch_entry_is_trusted(...) is False  (no _sig)
    with it unset and no dev opt-out  -> False                                  (fail closed)

So the live route for an approved fix is a **GitHub pull request** a human
merges, and that is the safer architecture. This phase does not turn auto-apply
on. Making an AI able to write Python to disk is not a step toward "every
advancement approved"; it is the thing approval exists to prevent.

**"The existing two-approver gate" did not cover this queue.**
`ai/policy/roles.py` declares that a repair needs a quorum including a
superadmin, and `api/safe_agent_platform.py:decide_approval` enforces exactly
that — but `api/security/fixes.py:approve_fix`, which is the gate an
AI-authored code patch actually passes, required a single `admin`. One admin
could approve AI-written code into a pull request on their own. This phase
closes that, and does it by extracting the quorum into `ai/policy/roles.py` so
there is one definition of the rule rather than two that drift.

## The proposer cannot sign and cannot apply

`ai/improve/` does not import `security.self_healer`, never names the signing
key, and never writes to `fixes:approved`. It puts a `pending` record on
`fixes:queue` and stops. That is asserted by parsing the package, so it is a
property of the code rather than of anyone's intention.

These fail on the pre-fix tree: `ai.improve.proposal` and
`ai.policy.roles.quorum` do not exist there, and `approve_fix` approves on one
admin.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _finding(**over):
    from ai.improve.finding import Finding

    fields = {
        "check": "silent_except",
        "path": "ai/improve/walker.py",
        "line": 1,
        "claim": "an exception is swallowed with no log line",
    }
    fields.update(over)
    return Finding(**fields)


class _FakeRedis:
    """Only the four list operations the queue path uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start : end + 1]

    async def lrem(self, key, count, value):
        items = self.lists.get(key, [])
        if value in items:
            items.remove(value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:] if end == -1 else self.lists.get(key, [])

    async def llen(self, key):
        return len(self.lists.get(key, []))


# ── the proposer cannot sign and cannot apply ─────────────────────────────────


def test_the_proposer_cannot_reach_the_signing_key_or_the_applied_queue():
    """Parsed, not promised.

    A proposer that could sign could put an entry straight into the queue the
    healer drains, and the two humans would never see it.
    """
    source = (_ROOT / "ai" / "improve" / "proposal.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Parsed, not grepped. This module EXPLAINS at length why it never signs and
    # never touches the applied queue, so a substring search would flag the
    # paragraph that documents the property it is checking.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    forbidden = {"HEAL_PATCH_SIGNING_KEY", "_sign_patch", "fixes:approved", "_apply_patch"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            assert node.value not in forbidden, f"line {node.lineno} is the literal {node.value!r}"
        if isinstance(node, ast.Name):
            assert node.id not in forbidden, f"line {node.lineno} references {node.id}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, f"line {node.lineno} references {node.attr}"
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.startswith("security.self_healer"), f"the proposer imports {name}"


def test_a_queued_proposal_carries_no_signature_and_says_so():
    from ai.improve import proposal

    prepared = proposal.prepare(_finding(), new_source="x = 1\n", proposer="code-walker")
    assert prepared.accepted is True
    entry = prepared.as_queue_entry()
    assert "_sig" not in entry
    assert entry["signed"] is False
    assert "human" in entry["applies_by"].lower() or "pull request" in entry["applies_by"].lower()


# ── the gates, in order ───────────────────────────────────────────────────────


def test_a_finding_whose_evidence_does_not_resolve_is_refused():
    """An approver has to be able to go and look at the line."""
    from ai.improve import proposal

    prepared = proposal.prepare(
        _finding(path="ai/improve/does_not_exist.py"), new_source="x = 1\n", proposer="code-walker"
    )
    assert prepared.accepted is False
    assert "evidence" in prepared.refused_because


def test_a_protected_path_is_refused_before_the_sandbox_runs(monkeypatch):
    from ai.improve import proposal

    ran = []
    monkeypatch.setattr(proposal, "_validate", lambda *a, **k: ran.append(1))

    prepared = proposal.prepare(_finding(path="risk/manager.py", line=1), new_source="x = 1\n", proposer="code-walker")
    assert prepared.accepted is False
    assert "protected" in prepared.refused_because
    assert ran == [], "the sandbox ran on a path that should never have got that far"


def test_source_the_sandbox_refuses_is_refused_with_its_reason_codes():
    from ai.improve import proposal

    prepared = proposal.prepare(_finding(), new_source="import os\n", proposer="code-walker")
    assert prepared.accepted is False
    assert "banned_import" in prepared.refused_because


def test_a_patch_that_changes_nothing_is_refused():
    """A no-op proposal spends two humans' attention and moves nothing."""
    from ai.improve import proposal

    current = (_ROOT / "ai" / "improve" / "walker.py").read_text(encoding="utf-8")
    prepared = proposal.prepare(_finding(), new_source=current, proposer="code-walker")
    assert prepared.accepted is False
    assert "no change" in prepared.refused_because


def test_an_oversized_patch_is_refused():
    from ai.improve import proposal

    prepared = proposal.prepare(_finding(), new_source="x = 1\n" * 200_000, proposer="code-walker")
    assert prepared.accepted is False
    assert "too large" in prepared.refused_because


def test_a_proposal_with_no_proposer_is_refused():
    """An anonymous proposal cannot be traced back to what produced it."""
    from ai.improve import proposal

    with pytest.raises(ValueError):
        proposal.prepare(_finding(), new_source="x = 1\n", proposer="  ")


def test_an_accepted_proposal_carries_the_finding_it_came_from():
    from ai.improve import proposal

    prepared = proposal.prepare(_finding(), new_source="x = 1\n", proposer="code-walker")
    entry = prepared.as_queue_entry()
    assert entry["evidence"] == "ai/improve/walker.py:1"
    assert entry["check"] == "silent_except"
    assert entry["proposed_by"] == "code-walker"
    assert entry["status"] == "pending"
    assert entry["origin"] == "ai"


# ── the AI's own code is proposable, and not exempt ───────────────────────────


def test_the_ai_can_propose_a_change_to_its_own_module():
    """Deliberately not in the vault: the AI improving itself is the point.

    What it does not get is a shorter path — the same gates, the same two
    humans.
    """
    from ai.improve import proposal
    from ai.vault import protected

    assert protected.is_protected("ai/improve/walker.py") is False
    prepared = proposal.prepare(_finding(), new_source="x = 1\n", proposer="code-walker")
    assert prepared.accepted is True
    assert prepared.as_queue_entry()["requires_quorum"] is True


def test_the_vault_itself_is_not_proposable_even_by_the_ai_improving_itself():
    from ai.improve import proposal

    prepared = proposal.prepare(
        _finding(path="ai/vault/protected.py", line=1), new_source="x = 1\n", proposer="code-walker"
    )
    assert prepared.accepted is False
    assert "protected" in prepared.refused_because


# ── queueing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_writes_a_pending_record_and_never_touches_the_applied_queue():
    from ai.improve import proposal

    redis = _FakeRedis()
    prepared = proposal.prepare(_finding(), new_source="x = 1\n", proposer="code-walker")
    result = await proposal.queue(prepared, redis=redis)

    assert result["queued"] is True
    assert "fixes:approved" not in redis.lists
    records = [json.loads(r) for r in redis.lists["fixes:queue"]]
    assert len(records) == 1
    assert records[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_queueing_a_refused_proposal_is_itself_refused():
    from ai.improve import proposal

    redis = _FakeRedis()
    prepared = proposal.prepare(_finding(path="risk/manager.py", line=1), new_source="x=1\n", proposer="w")
    result = await proposal.queue(prepared, redis=redis)

    assert result["queued"] is False
    assert redis.lists == {}
    assert "protected" in result["reason"]


@pytest.mark.asyncio
async def test_no_redis_is_reported_as_unavailable_rather_than_as_queued():
    from ai.improve import proposal

    prepared = proposal.prepare(_finding(), new_source="x = 1\n", proposer="code-walker")
    result = await proposal.queue(prepared, redis=None)

    assert result["queued"] is False
    assert "redis" in result["reason"].lower()


# ── the quorum, in one place ──────────────────────────────────────────────────


def test_one_admin_is_not_a_quorum_for_a_repair():
    from ai.policy.roles import quorum

    verdict = quorum([{"approver": "ann", "approver_role": "admin", "decision": "approve"}], kind="repair")
    assert verdict.met is False
    assert verdict.distinct_approvers == 1


def test_two_admins_without_a_superadmin_are_not_a_quorum_for_a_repair():
    """The overtake case: two admins approving AI-written code between them."""
    from ai.policy.roles import quorum

    verdict = quorum(
        [
            {"approver": "ann", "approver_role": "admin", "decision": "approve"},
            {"approver": "bo", "approver_role": "admin", "decision": "approve"},
        ],
        kind="repair",
    )
    assert verdict.met is False
    assert verdict.needs_superadmin is True
    assert "superadmin" in verdict.reason


def test_an_admin_and_a_superadmin_are_a_quorum():
    from ai.policy.roles import quorum

    verdict = quorum(
        [
            {"approver": "ann", "approver_role": "admin", "decision": "approve"},
            {"approver": "sue", "approver_role": "superadmin", "decision": "approve"},
        ],
        kind="repair",
    )
    assert verdict.met is True


def test_the_same_person_twice_is_one_approver():
    from ai.policy.roles import quorum

    verdict = quorum(
        [
            {"approver": "sue", "approver_role": "superadmin", "decision": "approve"},
            {"approver": "sue", "approver_role": "superadmin", "decision": "approve"},
        ],
        kind="repair",
    )
    assert verdict.met is False
    assert verdict.distinct_approvers == 1


def test_a_rejection_never_counts_toward_the_quorum():
    from ai.policy.roles import quorum

    verdict = quorum(
        [
            {"approver": "ann", "approver_role": "admin", "decision": "approve"},
            {"approver": "sue", "approver_role": "superadmin", "decision": "reject"},
        ],
        kind="repair",
    )
    assert verdict.met is False


def test_a_kind_outside_the_superadmin_list_needs_two_approvers_and_no_more():
    from ai.policy.roles import quorum

    verdict = quorum(
        [
            {"approver": "ann", "approver_role": "admin", "decision": "approve"},
            {"approver": "bo", "approver_role": "admin", "decision": "approve"},
        ],
        kind="observation",
    )
    assert verdict.met is True
    assert verdict.needs_superadmin is False


def test_the_existing_control_plane_still_uses_the_same_rule():
    """One definition, not two. `decide_approval` had the rule inline."""
    import inspect

    import api.safe_agent_platform as sp

    source = inspect.getsource(sp.decide_approval)
    assert "quorum(" in source, "the control plane keeps its own copy of the rule"


# ── the fix queue's approval honours it ───────────────────────────────────────


def _payload(sub: str, role: str) -> dict:
    return {"sub": sub, "role": role}


@pytest.mark.asyncio
async def test_one_admin_no_longer_approves_an_ai_authored_fix(monkeypatch):
    """The gate an AI-authored code patch actually passes took a single admin."""
    from api.security import fixes

    redis = _FakeRedis()
    record = {"endpoint": "/api/x", "fix": "x = 1\n", "status": "pending", "origin": "ai"}
    await redis.rpush("fixes:queue", json.dumps(record))

    monkeypatch.setattr(fixes, "_get_redis", lambda: _async(redis))
    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("ann", "admin"))

    result = await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    assert result["status"] == "awaiting_approval"
    assert "fixes:approved" not in redis.lists
    still_pending = [json.loads(r) for r in redis.lists["fixes:queue"]]
    assert len(still_pending) == 1
    assert still_pending[0]["status"] == "pending"
    assert [a["approver"] for a in still_pending[0]["approvals"]] == ["ann"]


@pytest.mark.asyncio
async def test_the_same_admin_cannot_approve_twice(monkeypatch):
    from api.security import fixes
    from fastapi import HTTPException

    redis = _FakeRedis()
    record = {"endpoint": "/api/x", "fix": "x = 1\n", "status": "pending", "origin": "ai"}
    await redis.rpush("fixes:queue", json.dumps(record))
    monkeypatch.setattr(fixes, "_get_redis", lambda: _async(redis))
    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("ann", "admin"))

    await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)
    with pytest.raises(HTTPException) as exc:
        await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_second_admin_is_still_not_enough_without_a_superadmin(monkeypatch):
    from api.security import fixes

    redis = _FakeRedis()
    record = {"endpoint": "/api/x", "fix": "x = 1\n", "status": "pending", "origin": "ai"}
    await redis.rpush("fixes:queue", json.dumps(record))
    monkeypatch.setattr(fixes, "_get_redis", lambda: _async(redis))

    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("ann", "admin"))
    await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("bo", "admin"))
    result = await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    assert result["status"] == "awaiting_approval"
    assert "superadmin" in result["reason"]
    assert "fixes:approved" not in redis.lists


@pytest.mark.asyncio
async def test_an_admin_then_a_superadmin_completes_the_approval(monkeypatch):
    from api.security import fixes

    redis = _FakeRedis()
    record = {"endpoint": "/api/x", "fix": "x = 1\n", "status": "pending", "origin": "ai"}
    await redis.rpush("fixes:queue", json.dumps(record))
    monkeypatch.setattr(fixes, "_get_redis", lambda: _async(redis))

    published = {}

    class _Publisher:
        async def publish(self, **kwargs):
            published.update(kwargs)
            return {"status": "created", "pr_url": "https://example.invalid/pr/1", "pr_number": 1}

    monkeypatch.setattr("security.github_pr_publisher.get_pr_publisher", lambda: _Publisher())

    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("ann", "admin"))
    await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("sue", "superadmin"))
    result = await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    assert result["status"] == "approved"
    assert redis.lists["fixes:queue"] == []
    approved = [json.loads(r) for r in redis.lists["fixes:approved"]]
    assert len(approved) == 1
    assert sorted(a["approver"] for a in approved[0]["approvals"]) == ["ann", "sue"]
    assert published["endpoint"] == "/api/x"


@pytest.mark.asyncio
async def test_the_record_that_reaches_the_applied_queue_is_still_unsigned(monkeypatch):
    """A completed approval produces a pull request, not a patch on disk.

    `SelfHealer._drain_approved_patches` reads this queue and rejects every
    unsigned entry — with a key because there is no `_sig`, without one because
    it fails closed. Turning that on is not this phase's job and is not what
    "approved" is meant to unlock.
    """
    from api.security import fixes
    import security.self_healer as healer

    redis = _FakeRedis()
    record = {"endpoint": "/api/x", "fix": "x = 1\n", "status": "pending", "origin": "ai"}
    await redis.rpush("fixes:queue", json.dumps(record))
    monkeypatch.setattr(fixes, "_get_redis", lambda: _async(redis))

    class _Publisher:
        async def publish(self, **_kwargs):
            return {"status": "created"}

    monkeypatch.setattr("security.github_pr_publisher.get_pr_publisher", lambda: _Publisher())

    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("ann", "admin"))
    await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)
    monkeypatch.setattr(fixes, "_require_admin", lambda _r: _payload("sue", "superadmin"))
    await fixes.approve_fix(fixes.ApproveFixRequest(endpoint="/api/x"), request=object(), user=None)

    raw = redis.lists["fixes:approved"][0]
    entry = json.loads(raw)
    assert "_sig" not in entry
    assert healer._patch_entry_is_trusted(raw, entry) is False


async def _async(value):
    return value


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_proposal_row_is_live_and_its_evidence_resolves():
    from ai.hub import capabilities

    assert capabilities.verify().discrepancies == ()
    rows = {c.id: c for c in capabilities.by_section("S")}
    assert rows["improve.finding_to_proposal"].state == "live"
