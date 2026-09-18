# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A walker finding becomes a candidate patch that two humans decide on.

## What this deliberately does not do

**It cannot sign, and it cannot apply.** `security/self_healer.py` drains
`fixes:approved` and applies what it finds, gated on an HMAC signature. This
module never imports it, never names `HEAL_PATCH_SIGNING_KEY`, and never writes
to `fixes:approved` — asserted by parsing this file, so it is a property of the
code rather than of anyone's intention. What it does is put a `pending` record
on `fixes:queue` and stop.

That matters because of what the signature gate actually does today. Nothing in
this repository ever signs a patch entry: `_sign_patch` has no production
caller, and all three writers of `fixes:approved` push unsigned records. So the
auto-apply path is inert in every configuration — with a key it rejects the
entry for having no `_sig`, without one it fails closed. Measured, not assumed.

The live route for an approved fix is a **GitHub pull request** a human merges,
and that is the safer architecture. Making an AI able to write Python to disk
is not a step toward "every advancement approved"; it is the thing approval
exists to prevent.

## The gates, and their order

1. **Evidence resolves.** The finding's `path:line` must be a line that really
   exists. An approver has to be able to go and look; a claim they cannot check
   is a claim they can only take on trust.
2. **The vault.** `ai/vault/protected.py`, by path, before anything reads the
   source. No content can argue its way past a rule it is never read against.
3. **It changes something.** A patch identical to the file spends two people's
   attention and moves nothing.
4. **Size.** Bounded the same way `SelfHealer.MAX_PATCH_SIZE` is, so a proposal
   that could never be applied is refused where it is cheap to refuse.
5. **The sandbox.** `security/ai_repair_sandbox.py` validates in a disposable
   directory, and refuses banned imports and calls.

A refusal names the gate that refused and never becomes a silent drop: a
proposal that vanished looks, from the queue, exactly like one that was never
made.

## The AI's own code is proposable, and gets no shortcut

`ai/improve/` is deliberately outside the vault floor — the AI improving itself
is the point of this track. What it does not get is a shorter path: the same
gates, and the same two humans, one of whom must be a superadmin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Final

from ai.improve.finding import Finding

logger = logging.getLogger(__name__)

_ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]

#: Matches `SelfHealer.MAX_PATCH_SIZE`'s default. A proposal larger than what
#: could ever be applied is refused here, where refusing is free.
MAX_PATCH_BYTES: Final[int] = 64 * 1024

#: The queue humans read. The other one — the queue the healer drains — is not
#: reachable from this module, by construction.
PENDING_QUEUE: Final[str] = "fixes:queue"

#: Every proposal from this module is a repair, which is one of
#: `ai.policy.roles.QUORUM_NEEDS_SUPERADMIN_KINDS`. Two distinct approvers, at
#: least one of them a superadmin.
KIND: Final[str] = "repair"


@dataclass(frozen=True)
class Prepared:
    """A candidate patch that has passed every gate, or the reason it did not."""

    accepted: bool
    finding: Finding
    proposer: str
    new_source: str = ""
    refused_because: str = ""
    proposal_id: str = ""
    checks_passed: tuple[str, ...] = field(default_factory=tuple)

    def as_queue_entry(self) -> dict[str, Any]:
        """The record a human reviews.

        `endpoint` carries the file path because that is the key
        `api/security/fixes.py` matches on; renaming it would need the dashboard
        and the approve/decline endpoints changed in the same commit.
        """
        if not self.accepted:
            raise ValueError(f"a refused proposal has no queue entry: {self.refused_because}")
        return {
            "id": self.proposal_id,
            "endpoint": self.finding.path,
            "file": self.finding.path,
            "fix": self.new_source,
            "status": "pending",
            "origin": "ai",
            "kind": KIND,
            "requires_quorum": True,
            "check": self.finding.check,
            "claim": self.finding.claim,
            "evidence": self.finding.evidence,
            "severity": self.finding.severity,
            "proposed_by": self.proposer,
            "proposed_at": time.time(),
            "checks_passed": list(self.checks_passed),
            #: Stated rather than implied. An entry with neither a signature nor
            #: a word about it reads, to whoever finds it, as one that could be
            #: applied.
            "signed": False,
            "applies_by": (
                "a human merging the pull request this becomes on approval; nothing here "
                "writes to disk, and the auto-apply queue rejects unsigned entries"
            ),
            "approvals": [],
        }


def prepare(finding: Finding, *, new_source: str, proposer: str) -> Prepared:
    """Run every gate against a candidate patch for `finding`.

    Returns a `Prepared` either way — a refusal is a result, not an exception,
    because the caller is a loop that must record why it proposed nothing.
    """
    if not proposer or not proposer.strip():
        raise ValueError("a proposal names its proposer; an anonymous one cannot be traced to what produced it")

    passed: list[str] = []

    if not finding.resolves(_ROOT):
        return _refused(finding, proposer, f"evidence does not resolve: {finding.evidence} is not a line that exists")
    passed.append("evidence_resolves")

    from ai.vault import protected

    verdict = protected.review(finding.path, source="")
    if not verdict.allowed:
        return _refused(finding, proposer, verdict.reason)
    passed.append("vault")

    current = _read(finding.path)
    if current is None:
        return _refused(finding, proposer, f"unreadable: {finding.path}")
    if new_source == current:
        return _refused(finding, proposer, "proposes no change; the patch is identical to the file")
    passed.append("changes_something")

    size = len(new_source.encode("utf-8"))
    if size > MAX_PATCH_BYTES:
        return _refused(finding, proposer, f"too large: {size} bytes exceeds the {MAX_PATCH_BYTES}-byte ceiling")
    passed.append("size")

    validation = _validate(new_source, finding.path)
    if validation is not None and not validation.accepted:
        return _refused(finding, proposer, f"the repair sandbox refused it: {', '.join(validation.reason_codes)}")
    passed.append("sandbox")

    digest = hashlib.sha256(f"{finding.evidence}|{new_source}".encode()).hexdigest()[:16]
    return Prepared(
        accepted=True,
        finding=finding,
        proposer=proposer,
        new_source=new_source,
        proposal_id=f"prop-{digest}",
        checks_passed=tuple(passed),
    )


def _refused(finding: Finding, proposer: str, reason: str) -> Prepared:
    return Prepared(accepted=False, finding=finding, proposer=proposer, refused_because=reason)


def _read(relative: str) -> str | None:
    try:
        return (_ROOT / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _validate(new_source: str, target_path: str):
    """The sandbox leg, kept separate so a test can prove it did not run."""
    from security.ai_repair_sandbox import validate_repair_for_target

    return validate_repair_for_target(new_source, target_path=target_path)


async def queue(prepared: Prepared, *, redis: Any) -> dict[str, Any]:
    """Put a prepared proposal on the queue humans read.

    Never reports success it did not have: no Redis is `queued: False` with the
    reason, because a proposal silently dropped looks, from the queue, exactly
    like one that was never made.
    """
    if not prepared.accepted:
        return {"queued": False, "reason": prepared.refused_because}
    if redis is None:
        return {"queued": False, "reason": "redis is unavailable, so the proposal was not recorded anywhere"}

    entry = prepared.as_queue_entry()
    try:
        await redis.rpush(PENDING_QUEUE, json.dumps(entry))
    except Exception as exc:
        logger.warning("proposal: could not queue %s: %s", prepared.proposal_id, exc)
        return {"queued": False, "reason": f"the queue write failed: {type(exc).__name__}"}
    return {"queued": True, "id": prepared.proposal_id, "queue": PENDING_QUEUE, "evidence": entry["evidence"]}
