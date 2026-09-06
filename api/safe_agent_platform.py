from __future__ import annotations

import logging

"""Additive, fail-closed supervisor and safe-evolution control surface.

This module intentionally proposes and gates consequential work; it does not execute
trades, mutate production code, or expose credentials without an explicit approval.
"""

import asyncio
import copy
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role
from ai.policy.roles import QUORUM_NEEDS_SUPERADMIN_KINDS
from api.superadmin._shared import require_superadmin_2fa
from core.config_store import config_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/safe-platform", tags=["Safe Agent Platform"])

_AGENTS = [
    {
        "id": "supervisor",
        "name": "Supervisor",
        "mission": "Decompose requests, delegate, merge evidence, and escalate",
        "risk": "read_only",
        "status": "ready",
    },
    {
        "id": "research",
        "name": "Market Research",
        "mission": "Inspect authorized external sources with citations",
        "risk": "read_only",
        "status": "degraded",
    },
    {
        "id": "data-quality",
        "name": "Data Quality",
        "mission": "Detect stale, missing, drifting, or contradictory data",
        "risk": "read_only",
        "status": "ready",
    },
    {
        "id": "risk-governance",
        "name": "Risk & Governance",
        "mission": "Review policy, approvals, exposure, and fail-closed gates",
        "risk": "approval_required",
        "status": "ready",
    },
    {
        "id": "strategy",
        "name": "Strategy Lab",
        "mission": "Run paper research, replay, and model comparison",
        "risk": "paper_only",
        "status": "ready",
    },
    {
        "id": "diagnostics",
        "name": "Diagnostics",
        "mission": "Collect evidence and rank root causes",
        "risk": "read_only",
        "status": "ready",
    },
    {
        "id": "repair",
        "name": "Repair & Evolution",
        "mission": "Draft reversible repair and upgrade proposals",
        "risk": "approval_required",
        "status": "ready",
    },
    {
        "id": "communications",
        "name": "Communications",
        "mission": "Explain findings through chat, voice, and summaries",
        "risk": "read_only",
        "status": "ready",
    },
]
_MODELS = [
    {
        "id": "gateway/reasoning",
        "role": "reasoning",
        "health": "unconfigured",
        "route": "primary",
        "secret_status": "server-managed",
    },
    {
        "id": "gateway/fast",
        "role": "fast",
        "health": "unconfigured",
        "route": "fallback",
        "secret_status": "server-managed",
    },
    {
        "id": "gateway/vision",
        "role": "vision",
        "health": "unconfigured",
        "route": "specialist",
        "secret_status": "server-managed",
    },
]
_INTEGRATIONS = [
    {
        "id": "ai-gateway",
        "name": "AI Gateway",
        "category": "model",
        "status": "available",
        "scopes": ["generate", "reason"],
        "token": "managed",
    },
    {
        "id": "web-research",
        "name": "External Research",
        "category": "research",
        "status": "not_connected",
        "scopes": ["read:public_sources"],
        "token": "server-only",
    },
    {
        "id": "broker",
        "name": "Broker Account",
        "category": "execution",
        "status": "paper_only",
        "scopes": ["read:account", "paper:orders"],
        "token": "redacted",
    },
]
_PROPOSALS: list[dict[str, Any]] = []
_APPROVALS: list[dict[str, Any]] = []
_PROPOSALS_KEY = "safe_platform:proposals"
_APPROVALS_KEY = "safe_platform:approvals"
_INTEGRATIONS_KEY = "safe_platform:integrations"
_TASKS_KEY = "safe_platform:tasks"
_ROUTES_KEY = "safe_platform:model_routes"
_EVIDENCE_KEY = "safe_platform:diagnostic_evidence"
#: Diagnostic runs retained. Old runs age out; the endpoint says what it keeps.
_EVIDENCE_LIMIT = 200
_TASKS: list[dict[str, Any]] = []
_ROUTES: list[dict[str, Any]] = []
_EVIDENCE: list[dict[str, Any]] = []
#: Both limits go through `rate_limiting/advanced.py`, which is Redis-backed
#: with an in-process fallback, rebinds its client when the event loop changes,
#: and re-probes after a Redis failure instead of disabling itself permanently.
#:
#: This module used to keep two module dicts instead. That made the limit
#: per-process — with `API_WORKERS>1` each worker enforced its own full
#: allowance, so 20/minute was 20 per worker and reset on every restart, the
#: same defect `ai/gateway/budget_store.py` records for the spend ceiling — and
#: it was a SECOND mechanism for a job this repository already does properly in
#: one place. Two mechanisms are two places for the same bug, and only one of
#: them gets the next fix.
_MAX_REQUESTS_PER_MINUTE = 20
_MAX_RESEARCH_UNITS_PER_HOUR = 30


def _reject_untrusted_instructions(value: str) -> None:
    lowered = value.lower()
    blocked = ("ignore previous", "reveal system prompt", "disable safety", "execute trade", "override policy")
    if any(marker in lowered for marker in blocked):
        raise HTTPException(status_code=400, detail="Research input contains an unsafe instruction pattern")


def _load_state() -> None:
    """Hydrate governance state from the shared Redis/DB config store."""
    stored_proposals = config_store.get(_PROPOSALS_KEY, default=[])
    stored_approvals = config_store.get(_APPROVALS_KEY, default=[])
    stored_integrations = config_store.get(_INTEGRATIONS_KEY, default=[])
    stored_tasks = config_store.get(_TASKS_KEY, default=[])
    stored_routes = config_store.get(_ROUTES_KEY, default=[])
    stored_evidence = config_store.get(_EVIDENCE_KEY, default=[])
    if isinstance(stored_proposals, list):
        _PROPOSALS.extend(item for item in stored_proposals if isinstance(item, dict))
    if isinstance(stored_approvals, list):
        _APPROVALS.extend(item for item in stored_approvals if isinstance(item, dict))
    if isinstance(stored_tasks, list):
        _TASKS.extend(item for item in stored_tasks if isinstance(item, dict))
    if isinstance(stored_routes, list):
        _ROUTES.extend(item for item in stored_routes if isinstance(item, dict))
    if isinstance(stored_evidence, list):
        _EVIDENCE.extend(item for item in stored_evidence if isinstance(item, dict))
    if isinstance(stored_integrations, list):
        for stored in stored_integrations:
            if isinstance(stored, dict) and stored.get("id"):
                current = next((entry for entry in _INTEGRATIONS if entry["id"] == stored["id"]), None)
                if current:
                    current.update(
                        {
                            key: value
                            for key, value in stored.items()
                            if key not in {"secret", "token_value", "access_token", "refresh_token"}
                        }
                    )


def _save_state(changed_by: str) -> None:
    """Persist proposals and approvals without ever persisting secret values.

    Raises 503 when any write fails. `config_store.set` returns bool -- "True if
    at least the DB write succeeded" -- and logs `ConfigStore.set: DB write
    failed` otherwise. Every one of these five calls used to ignore that return
    value, so a failed write still returned 200 to the operator: state survived
    only in the module-level lists below, an approval recorded that way vanished
    on restart, and the operator had been told it was recorded.
    """
    failed: list[str] = []

    def _write(key: str, value: object) -> None:
        if not config_store.set(key, value, changed_by=changed_by):
            failed.append(key)

    _write(_PROPOSALS_KEY, _PROPOSALS)
    _write(_APPROVALS_KEY, _APPROVALS)
    _write(
        _INTEGRATIONS_KEY,
        [
            {
                key: value
                for key, value in item.items()
                if key not in {"secret", "token_value", "access_token", "refresh_token"}
            }
            for item in _INTEGRATIONS
        ],
    )
    _write(_TASKS_KEY, _TASKS)
    _write(_ROUTES_KEY, _ROUTES)
    _write(_EVIDENCE_KEY, _EVIDENCE)

    if failed:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not persist the safe-platform state: {', '.join(failed)}. The action was NOT recorded durably."
            ),
        )


_load_state()


def _superadmin_2fa(user: TokenPayload = Depends(require_superadmin_2fa)) -> TokenPayload:
    """Superadmin role AND a TOTP-verified token.

    Guards the consequential tier of the Part 1B matrix: execute, rollback,
    model routing, and integration credential actions. Every endpoint in this
    module used to depend on `_admin` below, and `require_role` is a
    minimum-rank check, so rank 3 (admin) cleared all of them -- an admin could
    execute an approved proposal, roll it back, reroute the models and rotate
    an integration's credentials. `require_superadmin_2fa` already existed in
    api/superadmin/_shared.py for exactly this class of action; it was simply
    never used here.
    """
    return user


def _admin(user: TokenPayload = Depends(require_role("admin"))) -> TokenPayload:
    return user


async def _enforce_rate_limit(user: TokenPayload) -> None:
    """Refuse an operator making requests faster than the platform allows.

    Async because the shared limiter is. Every call site must `await` it: an
    unawaited call builds a coroutine, never runs it, and the limit silently
    stops existing — which `test_ai_rate_limit_is_shared_across_workers.py`
    checks by walking this module's AST rather than trusting the edits.
    """
    from rate_limiting.advanced import is_allowed

    if not await is_allowed(f"ai:req:{user.sub}", _MAX_REQUESTS_PER_MINUTE, 60):
        raise HTTPException(status_code=429, detail="Safe platform request rate limit exceeded")


def _id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{hashlib.sha256(repr(payload).encode()).hexdigest()[:12]}"


async def _consume_research_budget(user: TokenPayload) -> None:
    """Refuse external research beyond this operator's hourly allowance.

    A separate key namespace from the request limit on purpose: sharing a
    counter would let research calls exhaust the ordinary request allowance and
    refuse unrelated work for a reason nobody could see from either number.
    """
    from rate_limiting.advanced import is_allowed

    if not await is_allowed(f"ai:research:{user.sub}", _MAX_RESEARCH_UNITS_PER_HOUR, 3600):
        raise HTTPException(status_code=429, detail="External research budget exceeded for this operator")


_DEFAULT_ROLLBACK_PLAN = "Restore the last known-good checkpoint and re-run health gates."

# Substrings that mark a value as credential-shaped. Deliberately a denylist on
# the KEY plus a shape test on the VALUE: a proposal's `changes` is free-form,
# so there is no schema to validate against.
_SECRET_KEY_MARKERS = (
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "auth",
    "private",
)
_SECRET_VALUE_PREFIXES = ("sk-", "pk-", "ghp_", "gho_", "xox", "AKIA", "-----BEGIN")


def _looks_like_a_secret(key: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith(_SECRET_VALUE_PREFIXES):
        return True
    lowered = key.lower()
    if not any(marker in lowered for marker in _SECRET_KEY_MARKERS):
        return False
    # A key named like a credential carrying a long opaque value.
    return len(value) >= 12 and " " not in value.strip()


def _changes_are_redacted(changes: dict[str, Any]) -> bool:
    """True when nothing in `changes` looks like a live credential.

    This was the literal `True`. A proposal's changes are rendered to approvers
    and persisted, so a credential pasted into one is disclosed twice over.
    """
    stack: list[tuple[str, Any]] = list(changes.items())
    while stack:
        key, value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.items())
            continue
        if isinstance(value, list | tuple):
            stack.extend((key, item) for item in value)
            continue
        if _looks_like_a_secret(str(key), value):
            return False
    return True


def _live_trading_is_disabled() -> bool:
    """True when this deployment is not wired to a live venue.

    This was the literal `True`, which asserted the one fact an operator most
    needs to be true rather than reading it.
    """
    return os.getenv("BROKER_TYPE", "paper").strip().lower() == "paper"


def _rollback_plan_is_real(proposal: dict[str, Any]) -> bool:
    """True when someone actually wrote a rollback plan for this proposal.

    `rollback_plan` has a default, so `bool(plan)` is always true and asserts a
    plan nobody wrote. A plan that is still the boilerplate is not a plan.
    """
    plan = str(proposal.get("rollback_plan", "")).strip()
    return bool(plan) and plan != _DEFAULT_ROLLBACK_PLAN


#: The eval report the promotion gate reads. `None` until an eval run stores
#: one, and the gate refuses on None -- fail closed. This is the seam the eval
#: runner fills; it is deliberately not defaulted to a passing score, because a
#: gate that permits when it has no evidence is not a gate.
_EVAL_REPORT: Any = None


def set_eval_report(report: Any) -> None:
    """Record the latest eval suite report for the promotion gate.

    Kept in this process AND written to the shared store when one is installed.
    Both, not either: a store outage must not discard six paid model calls, and
    the local copy is what this worker falls back to when Redis is unreachable.
    """
    global _EVAL_REPORT
    _EVAL_REPORT = report
    if report is not None:
        from ai.evals import store

        store.save(report)


def get_eval_report() -> Any:
    """The report the gate should judge, from wherever the freshest one is.

    Reads the shared store first, because another worker — or this one before
    the last restart — may have run the suite. Falls back to this process's own
    copy when there is no store or the store cannot be read: refusing to promote
    because Redis blipped, while this worker holds a perfectly good report, is a
    gate refusing on the wrong evidence.

    Freshness, not preference: whichever report was measured most recently wins,
    so a suite just run here is not shadowed by an older one in Redis. The gate's
    24h bound still applies to whatever comes back — storing evidence durably
    does not make it newer.
    """
    from ai.evals import store

    stored = store.load()
    local = _EVAL_REPORT
    if stored is None:
        return local
    if local is None:
        return stored
    return stored if float(stored.ran_at) >= float(local.ran_at) else local


def _eval_gate_allows(environment: str) -> tuple[bool, str]:
    """Whether the eval gate permits promotion to `environment`.

    Binds on `canary` -- the closest thing this API has to live. Sandbox and
    paper are where candidates are supposed to run BEFORE they have a score, so
    requiring one there would block the very work that produces it.
    """
    if environment != "canary":
        return True, "not_applicable"
    from ai.evals.gate import PromotionGate, PromotionRefused

    # required_case_ids is not optional here, though the dataclass makes it
    # look it. Without it a model that FAILS a risk-arithmetic case is promoted
    # whenever the aggregate clears the bar — measured: a 0.95 report whose one
    # failure was "is a 15% drawdown above a 10% limit" was permitted. The
    # `required` flag on EvalCase existed, PromotionGate supported it, and
    # nothing passed it through: a control that exists and is never wired.
    from ai.evals.cases import REQUIRED_CASE_IDS

    gate = PromotionGate(
        minimum_score={"canary": 0.9, "live": 0.95},
        required_case_ids=REQUIRED_CASE_IDS,
    )
    try:
        gate.check(get_eval_report(), target="canary")
    except PromotionRefused as refused:
        return False, ", ".join(refused.reason_codes)
    return True, "eval_gate_passed"


@router.post("/generate")
async def submit_generation(
    body: GenerateRequest,
    user: TokenPayload = Depends(_admin),
) -> dict[str, Any]:
    """Start one generation and return immediately with its job id.

    The screen calls this once per panel. Nothing blocks: the job runs on the
    AI pool and the panel polls `/generate/jobs` for state and output, so four
    panels genuinely work at once rather than queueing behind each other.

    Every job still passes everything a single call passes — the budget ceiling
    and velocity brake, the audit trail, the guardrails, the output secret
    scanner, the circuit breakers. Concurrency is not a way around any of them,
    and the ceiling binding across four panels at once is the point.
    """
    await _enforce_rate_limit(user)
    from ai.jobs.runner import QueueFull, get_runner

    runner = get_runner()

    def work(report: Any) -> dict[str, Any]:
        # Imports live here so a failure to reach a vendor is this job's error
        # rather than an import-time problem for the whole endpoint.
        from ai.gateway.adapters import build_providers
        from ai.gateway.client import GatewayClient, ModelRequest

        report("resolving the model chain")
        providers = build_providers()
        if not providers:
            raise RuntimeError("no model vendor is configured")

        report("contacting the model")
        client = GatewayClient(providers)
        request = ModelRequest(role=body.role, prompt=body.prompt)

        # Streamed, so the panel fills in as the model speaks rather than
        # staying blank until it stops. `kind="output"` is what keeps the answer
        # out of the status-note list; the runner coalesces these into a frame
        # every 120ms so a fast model does not become a flood of WebSocket
        # frames. Every control on the buffered path still runs — the guardrails
        # screen the released text, the ceiling is charged, the audit is written.
        # `on_complete` carries what a generator cannot: which vendor served,
        # what it cost, whether the cache answered. Explicit, rather than
        # reaching into the client afterwards and hoping.
        finished: dict[str, Any] = {}
        answer = ""
        for piece in client.stream_sync(request, operator=user.sub, on_complete=lambda r: finished.update(vars(r))):
            if not piece:
                continue
            answer += piece
            report(piece, kind="output")

        # The finished result is still returned whole. A panel that reloads, or
        # an operator who opens the page after the job finished, reads this and
        # not the partial — the stream is how the answer arrives, not where it
        # lives.
        report(f"answered by {finished.get('provider', 'the model')}")
        return {
            "text": answer,
            "provider": str(finished.get("provider", "") or ""),
            "model": str(finished.get("model", "") or ""),
            "cost_usd": float(finished.get("cost_usd", 0.0) or 0.0),
            "cached": bool(finished.get("cached", False)),
            "latency_ms": round(float(finished.get("latency_ms", 0.0) or 0.0), 1),
        }

    try:
        # on_change pushes each state transition to this operator's screen over
        # the private ai_jobs channel. A publish failure never fails the job,
        # and the panel's poll remains the fallback.
        from ai.jobs.progress import publish

        job_id = runner.submit(prompt=body.prompt, work=work, operator=user.sub, on_change=publish)
    except QueueFull as exc:
        # 429, not 500: the caller should slow down, and the request was
        # well-formed. Telling a panel "server error" for backpressure would
        # have an operator chasing an outage that is not happening.
        raise HTTPException(status_code=429, detail=str(exc)) from None

    return {"job_id": job_id, "label": body.label, "state": "queued"}


@router.get("/generate/jobs")
async def list_generations(user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    """This operator's jobs, for the screen to render all their panels at once.

    Scoped to `user.sub`. It was not: the endpoint took `user` and returned
    every job in the process, so on a deployment with two admins one admin's AI
    Core screen showed the other's prompts and the model's answers. Being an
    admin is not being every admin.
    """
    from ai.jobs.runner import get_runner

    return get_runner().snapshot(operator=user.sub)


@router.post("/generate/{job_id}/cancel")
async def cancel_generation(job_id: str, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    """Stop one of this operator's panels without touching the others.

    Scoped to `user.sub`. It was not, and a job id was all it took for one admin
    to stop another's running generation. A job that belongs to somebody else
    answers exactly as a job that does not exist, so this cannot be used to
    discover which ids are live.
    """
    from ai.jobs.runner import get_runner

    cancelled = get_runner().cancel(job_id, operator=user.sub)
    if not cancelled:
        raise HTTPException(status_code=404, detail="No such job, or it has already finished.")
    return {"job_id": job_id, "cancelled": True}


def queue_observation_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Put a department's observation into the same queue a human's goes into.

    Spec §2's core principle: every department can recommend, and nothing acts
    without passing the superadmin approval queue. An awareness watcher noticing
    a breached drawdown limit produces exactly what an admin proposing a change
    produces — a `pending` row somebody has to decide on.

    Deliberately one queue rather than a separate "alerts" list. A second
    surface would be a second place to look, and the thing an operator most
    needs to see is everything waiting on them in one place.

    Not an endpoint: nothing outside the process may inject a proposal
    attributed to a department. `ai/awareness` calls it in-process through the
    startup factory, which is the only caller.
    """
    _PROPOSALS.append(proposal)
    try:
        _save_state(proposal.get("created_by", "awareness"))
    except Exception:
        logger.exception("could not persist an awareness proposal; it is queued in this process only")
    return proposal


@router.post("/vision/interpret")
async def vision_interpret(
    body: VisionInterpretRequest,
    user: TokenPayload = Depends(_admin),
) -> dict[str, Any]:
    """Read one camera frame and return a typed detection.

    The frontend has called this path since audit D6 and it has never existed,
    so every scan 404s. D6 had already removed the two defects that mattered —
    a fabricated interpretation produced by sleeping 650 ms, and a stale-closure
    bug that jammed the panel — leaving an honest "no vision service is
    connected". This connects one.

    Reading, never acting. The prompt in `ai/vision/detect.py` says so, the
    contract has no field that could express an order, and the capability row
    is PROPOSE rather than EXECUTE. The panel's stated boundary — a scan can
    explain a visual state but cannot place, modify or approve a trade — is
    enforced in three places rather than promised in one.

    The frame is not persisted. It is decoded, sent, and dropped; only the
    structured reading is returned, which is what makes the UI's "frames stay
    in memory" line true rather than aspirational.
    """
    await _enforce_rate_limit(user)

    if not body.image_b64:
        # The shape the frontend currently sends. Answering plainly beats a 422.
        return {
            "interpretation": None,
            "detection": None,
            "reason": "no_frame_supplied",
            "detail": "No image was included in the request, so nothing was interpreted.",
        }

    from ai.gateway.client import ImageRef
    from ai.guardrails.output import GuardrailViolation
    from ai.vision.detect import interpret

    try:
        image = ImageRef(media_type=body.media_type, data_b64=body.image_b64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    try:
        detection = await asyncio.to_thread(interpret, (image,), operator=user.sub, hint=body.hint)
    except GuardrailViolation as exc:
        # The model answered, just not in the contract. A refused reading is a
        # correct outcome, not an outage — and never retried on another vendor.
        raise HTTPException(status_code=422, detail=f"the frame could not be read reliably: {exc}") from None
    except Exception as exc:
        logger.error("vision_interpret: %s", exc)
        raise HTTPException(status_code=503, detail=f"vision service unavailable: {exc}") from None

    return {
        "interpretation": _describe(detection),
        "detection": detection,
        "reason": "ok",
    }


def _describe(detection: dict[str, Any]) -> str:
    """One human sentence for the panel, built from the typed fields.

    Composed here rather than asked of the model: a sentence the model wrote is
    a second, unvalidated answer that can disagree with the structured one.
    """
    surface = detection.get("surface_type", "unknown")
    confidence = detection.get("confidence", 0.0)
    if surface == "unknown":
        return f"Could not identify the surface in this frame (confidence {confidence:.0%})."

    bits = [f"Reads as a {surface} (confidence {confidence:.0%})"]
    if detection.get("instrument"):
        bits.append(f"instrument {detection['instrument']}")
    if detection.get("timeframe"):
        bits.append(f"timeframe {detection['timeframe']}")
    if detection.get("trend"):
        bits.append(f"trend {detection['trend']}")
    sentence = ", ".join(bits) + "."
    if detection.get("requires_corroboration"):
        sentence += " Numeric readings are from a photograph and are NOT corroborated against the live feed."
    return sentence


@router.post("/evals/run")
async def run_evals(user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    """Run the eval suite and file the report the promotion gate reads.

    This is the seam that had no filler: `set_eval_report` had zero callers, so
    `_EVAL_REPORT` was always None and the gate always refused `no_eval_report`
    — canary promotion was not gated, it was impossible.

    Every case is a paid model call through the gateway, which is why this is
    triggered rather than automatic, and why it is rate-limited here on top of
    the budget ceiling and velocity brake.

    A failing report is filed too. Withholding a bad score would leave the gate
    reading a stale passing one, which is fail-open wearing fail-closed's
    clothes.
    """
    await _enforce_rate_limit(user)
    from ai.evals.runner import run_and_publish

    try:
        report = run_and_publish()
    except Exception as exc:
        logger.error("run_evals: suite could not run (%s)", exc)
        raise HTTPException(status_code=503, detail=f"eval suite could not run: {exc}") from None

    allowed, reason = _eval_gate_allows("canary")
    return {
        "score": report.score,
        "total": report.total,
        "passed": report.passed,
        "failed_case_ids": list(report.failed_case_ids),
        "ran_at": report.ran_at,
        # What the gate would now do with it — the reason an operator ran this.
        "canary_promotion_allowed": allowed,
        "gate_reason": reason,
    }


class DiagnosticRequest(BaseModel):
    scope: str = Field(default="all", min_length=1, max_length=80)
    include_external: bool = False


class ProposalRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    kind: str = Field(pattern="^(repair|upgrade|configuration|research)$")
    scope: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    changes: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    rollback_plan: str = Field(
        default="Restore the last known-good checkpoint and re-run health gates.", min_length=10, max_length=1000
    )


class ApprovalRequest(BaseModel):
    proposal_id: str
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=3, max_length=500)


class ValidationRequest(BaseModel):
    proposal_id: str
    environment: str = Field(default="sandbox", pattern="^(sandbox|paper|canary)$")


class ProposalExecutionRequest(BaseModel):
    proposal_id: str
    confirmation: str = Field(min_length=8, max_length=120)
    environment: str = Field(default="sandbox", pattern="^(sandbox|paper|canary)$")


class UpgradeRequest(BaseModel):
    component: str = Field(min_length=2, max_length=120)
    target: str = Field(min_length=2, max_length=160)
    compatibility_checks: list[str] = Field(min_length=1, max_length=20)
    migration_plan: str = Field(min_length=10, max_length=1200)


class IntegrationAction(BaseModel):
    integration_id: str
    action: str = Field(pattern="^(authorize|revoke|rotate|health_probe)$")
    scopes: list[str] = Field(default_factory=list, max_length=12)
    reason: str = Field(min_length=3, max_length=400)


class SupervisorTaskRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    requested_agents: list[str] = Field(default_factory=list, max_length=12)
    allow_external_read: bool = False


class GenerateRequest(BaseModel):
    """One generation, to run alongside others."""

    prompt: str = Field(min_length=1, max_length=20_000)
    role: str = Field(default="reasoning", pattern="^(reasoning|fast|vision)$")
    label: str = Field(default="", max_length=80)


class VisionInterpretRequest(BaseModel):
    """One camera frame, on its way to the vision chain.

    `image_b64` is optional so the endpoint keeps answering the shape the
    frontend has been sending since D6 — `{"source": "camera_frame"}` with no
    image. That request gets an explicit "no frame was supplied", which is the
    honest answer and matches what the panel already displays, rather than a
    422 that would read to an operator as a broken feature.
    """

    source: str = Field(default="camera_frame", max_length=64)
    image_b64: str | None = Field(default=None, max_length=8_000_000)
    media_type: str = Field(default="image/png", max_length=64)
    hint: str = Field(default="", max_length=500)


class ModelRouteRequest(BaseModel):
    role: str = Field(pattern="^(reasoning|fast|vision|embedding)$")
    model_id: str = Field(min_length=3, max_length=160)
    reason: str = Field(min_length=3, max_length=400)


class TaskPlanRequest(BaseModel):
    task_id: str
    plan_summary: str = Field(min_length=3, max_length=2000)
    steps: list[str] = Field(min_length=1, max_length=20)
    tools: list[str] = Field(default_factory=list, max_length=20)
    external_sources: list[str] = Field(default_factory=list, max_length=20)
    requires_approval: bool = True


class TaskExecutionRequest(BaseModel):
    task_id: str
    mode: str = Field(default="dry_run", pattern="^(dry_run|paper)$")
    confirmation: str = Field(min_length=8, max_length=120)


class ResearchRequest(BaseModel):
    task_id: str
    query: str = Field(min_length=3, max_length=500)
    sources: list[str] = Field(min_length=1, max_length=10)
    connector_id: str | None = None


class DelegationRequest(BaseModel):
    task_id: str
    agent_ids: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(min_length=3, max_length=500)


@router.get("/overview")
async def overview(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {
        "paper_mode": os.getenv("BROKER_TYPE", "paper") == "paper",
        "human_approval_required": True,
        "agents": copy.deepcopy(_AGENTS),
        "models": copy.deepcopy(_MODELS),
        "integrations": copy.deepcopy(_INTEGRATIONS),
        "pending_proposals": len([p for p in _PROPOSALS if p["status"] == "pending"]),
        "capabilities": {
            "external_read": True,
            "external_write": False,
            "live_trading": False,
            "self_modify": False,
            "credential_values_visible": False,
        },
    }


@router.post("/models/route")
async def route_model(request: ModelRouteRequest, user: TokenPayload = Depends(_superadmin_2fa)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    if not request.model_id.startswith(("gateway/", "openai/", "anthropic/", "google/")):
        raise HTTPException(status_code=400, detail="Model must use an approved provider namespace")
    route = {
        "role": request.role,
        "model_id": request.model_id,
        "status": "pending_health_check",
        "reason": request.reason,
        "changed_by": user.sub,
        "changed_at": datetime.now(UTC).isoformat(),
        "side_effects": "none",
    }
    _ROUTES[:] = [item for item in _ROUTES if item.get("role") != request.role]
    _ROUTES.append(route)
    _save_state(user.sub)
    return {
        "route": route,
        "message": "Route recorded as pending verification; no provider call or secret change was performed.",
    }


@router.get("/models/routes")
async def model_routes(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": copy.deepcopy(_ROUTES), "status": "pending_health_check" if _ROUTES else "unconfigured"}


@router.post("/supervisor/tasks")
async def create_supervisor_task(
    request: SupervisorTaskRequest, user: TokenPayload = Depends(_admin)
) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    allowed_ids = {agent["id"] for agent in _AGENTS}
    requested = sorted(set(request.requested_agents) & allowed_ids)
    task = {
        "id": _id("task", [user.sub, request.prompt, datetime.now(UTC).isoformat()]),
        "prompt": request.prompt,
        "status": "awaiting_plan",
        "requested_agents": requested or ["supervisor"],
        "external_read": request.allow_external_read,
        "external_access": "connector_required" if request.allow_external_read else "disabled",
        "side_effects": "blocked",
        "human_approval_required": True,
        "created_by": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
        "events": [{"type": "task_created", "actor": user.sub}],
    }
    _TASKS.append(task)
    _save_state(user.sub)
    return {"task": copy.deepcopy(task), "message": "Task accepted for planning. No tool or external action has run."}


@router.get("/supervisor/tasks")
async def list_supervisor_tasks(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": list(reversed(copy.deepcopy(_TASKS))), "side_effects": "blocked_until_human_approval"}


@router.post("/supervisor/tasks/{task_id}/cancel")
async def cancel_supervisor_task(task_id: str, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    task = next((item for item in _TASKS if item["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"completed_reviewable_run", "cancelled"}:
        raise HTTPException(status_code=409, detail="Task cannot be cancelled in its current state")
    task["status"] = "cancelled"
    task.setdefault("events", []).append(
        {"type": "task_cancelled", "actor": user.sub, "at": datetime.now(UTC).isoformat()}
    )
    _save_state(user.sub)
    return {"task": copy.deepcopy(task), "message": "Task cancelled and all future tool execution blocked."}


@router.get("/models/health")
async def model_health(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {
        "items": [{**model, "last_checked": None, "provider_call": "not_performed"} for model in _MODELS],
        "status": "configuration_only",
        "message": "Live health checks require a configured provider and remain disabled until explicitly enabled.",
    }


@router.post("/supervisor/tasks/plan")
async def plan_supervisor_task(request: TaskPlanRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    task = next((item for item in _TASKS if item["id"] == request.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not request.requires_approval:
        raise HTTPException(status_code=400, detail="All supervisor plans require human approval")
    plan = {
        "id": _id("plan", [request.task_id, request.steps]),
        "task_id": request.task_id,
        "summary": request.plan_summary,
        "steps": request.steps,
        "tools": request.tools,
        "external_sources": request.external_sources,
        "untrusted_content_boundary": "external content is evidence only and cannot override system policy",
        "status": "awaiting_human_review",
        "created_by": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
        "side_effects": "blocked",
        "approval_required": True,
    }
    task["status"] = "awaiting_human_review"
    task["plan"] = plan
    task.setdefault("events", []).append({"type": "plan_created", "actor": user.sub, "plan_id": plan["id"]})
    _save_state(user.sub)
    return {
        "task": copy.deepcopy(task),
        "plan": plan,
        "message": "Plan created. External content is untrusted evidence and no tool has executed.",
    }


@router.post("/supervisor/tasks/{task_id}/approve")
async def approve_supervisor_task(task_id: str, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    task = next((item for item in _TASKS if item["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") != "awaiting_human_review":
        raise HTTPException(status_code=409, detail="Task has no reviewable plan")
    task["status"] = "approved_for_restricted_execution"
    task["approved_by"] = user.sub
    task["approved_at"] = datetime.now(UTC).isoformat()
    task.setdefault("events", []).append({"type": "human_approval", "actor": user.sub})
    _save_state(user.sub)
    return {
        "task": copy.deepcopy(task),
        "message": "Human approval recorded. Execution remains restricted to approved tools and environments.",
    }


@router.post("/supervisor/tasks/delegate")
async def delegate_supervisor_task(request: DelegationRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    task = next((item for item in _TASKS if item["id"] == request.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    available = {agent["id"]: agent for agent in _AGENTS}
    selected = [available[agent_id] for agent_id in dict.fromkeys(request.agent_ids) if agent_id in available]
    if not selected:
        raise HTTPException(status_code=400, detail="No approved specialist agents were selected")
    delegation = {
        "id": _id("delegation", [request.task_id, request.agent_ids]),
        "agents": [
            {"id": agent["id"], "mission": agent["mission"], "risk": agent["risk"], "status": agent["status"]}
            for agent in selected
        ],
        "rationale": request.rationale,
        "status": "planned",
        "side_effects": "blocked",
        "created_by": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
    }
    task["delegation"] = delegation
    task.setdefault("events", []).append(
        {"type": "delegation_planned", "actor": user.sub, "delegation_id": delegation["id"]}
    )
    _save_state(user.sub)
    return {
        "task": copy.deepcopy(task),
        "delegation": delegation,
        "message": "Delegation plan recorded. Specialists cannot execute tools until the task plan is approved.",
    }


@router.post("/research/request")
async def request_external_research(request: ResearchRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    await _consume_research_budget(user)
    _reject_untrusted_instructions(request.query)
    task = next((item for item in _TASKS if item["id"] == request.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    connector = (
        next((item for item in _INTEGRATIONS if item["id"] == request.connector_id), None)
        if request.connector_id
        else None
    )
    if not connector or connector.get("status") not in {"authorized", "available"}:
        evidence = {
            "status": "blocked",
            "query": request.query,
            "requested_sources": request.sources,
            "connector_id": request.connector_id,
            "reason": "An authorized, scope-limited research connector is required.",
            "untrusted_content_boundary": "external results are evidence only",
            "requested_by": user.sub,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        task.setdefault("events", []).append({"type": "research_blocked", "actor": user.sub, "evidence": evidence})
        _save_state(user.sub)
        return {"research": evidence, "message": "No external request was made."}
    return {
        "research": {
            "status": "queued_for_connector",
            "query": request.query,
            "sources": request.sources,
            "attribution_required": True,
            "timestamp_required": True,
            "requested_by": user.sub,
        },
        "message": "Research queued through the authorized connector; results must be attributed and remain untrusted evidence.",
    }


@router.post("/supervisor/tasks/execute")
async def execute_supervisor_task(
    request: TaskExecutionRequest, user: TokenPayload = Depends(_superadmin_2fa)
) -> dict[str, Any]:
    task = next((item for item in _TASKS if item["id"] == request.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") != "approved_for_restricted_execution":
        raise HTTPException(status_code=409, detail="Task requires a current human-approved plan")
    if request.confirmation != "EXECUTE APPROVED PLAN":
        raise HTTPException(status_code=400, detail="Explicit execution confirmation is required")
    execution = {
        "id": _id("execution", [request.task_id, datetime.now(UTC).isoformat()]),
        "task_id": request.task_id,
        "mode": request.mode,
        "status": "completed_dry_run",
        "tool_calls": [
            {"tool": tool, "status": "simulated_no_side_effect"} for tool in task.get("plan", {}).get("tools", [])
        ],
        "external_calls": "blocked_without_authorized_connector",
        "trading": "paper_only",
        "rollback_checkpoint": "not_needed_no_mutation",
        "executed_by": user.sub,
        "executed_at": datetime.now(UTC).isoformat(),
    }
    task["status"] = "completed_reviewable_run"
    task.setdefault("events", []).append(
        {"type": "restricted_execution", "actor": user.sub, "execution_id": execution["id"], "mode": request.mode}
    )
    task["last_execution"] = execution
    _save_state(user.sub)
    return {
        "task": copy.deepcopy(task),
        "execution": execution,
        "message": "Restricted execution completed without live mutation, credential access, or trade placement.",
    }


@router.post("/diagnostics/run")
async def run_diagnostics(request: DiagnosticRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    external = {"status": "not_requested", "sources": []}
    if request.include_external:
        external = {
            "status": "blocked_until_connector_authorized",
            "sources": [],
            "reason": "No external connector was authorized for this diagnostic.",
        }
    run_id = _id("diag", [user.sub, request.scope, datetime.now(UTC).isoformat()])
    findings = [
        {
            "id": "paper-boundary",
            "severity": "info",
            "title": "Consequential actions are approval-gated",
            "evidence": ["live_trading_disabled", "self_modify_disabled"],
        },
        {
            "id": "model-readiness",
            "severity": "warning" if not _ROUTES else "info",
            "title": "Model route health requires an explicit provider probe",
            "evidence": ["provider_call_not_performed", "route_health_pending"],
        },
    ]
    evidence: dict[str, Any] = {
        "run_id": run_id,
        "scope": request.scope,
        "checked_at": datetime.now(UTC).isoformat(),
        "findings": findings,
        "external": external,
    }
    # D4: this dict used to be a dead local. _save_state persists proposals,
    # approvals, integrations, tasks and routes -- evidence was in none of them,
    # so the endpoint returned "persisted_in_audit_store" and the run_id it
    # handed the operator resolved to nothing. It is now in the persisted set,
    # capped so an audit store cannot grow without bound.
    _EVIDENCE.append(evidence)
    del _EVIDENCE[:-_EVIDENCE_LIMIT]
    _save_state(user.sub)
    return {
        "run_id": run_id,
        "status": "complete",
        "scope": request.scope,
        "checked_at": evidence["checked_at"],
        "findings": findings,
        "external": external,
        "evidence_retention": "persisted_in_audit_store",
    }


def diagnostic_evidence(run_id: str) -> dict[str, Any] | None:
    """The stored evidence for a diagnostic run, or None when it is not held."""
    return next((item for item in _EVIDENCE if item.get("run_id") == run_id), None)


@router.get("/diagnostics/runs/{run_id}")
async def diagnostics_run(run_id: str, _: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    """Retrieve a diagnostic run by the id run_diagnostics returned."""
    evidence = diagnostic_evidence(run_id)
    if evidence is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No diagnostic evidence for run {run_id}. Runs are retained for the "
                f"most recent {_EVIDENCE_LIMIT} diagnostics."
            ),
        )
    return {"evidence": copy.deepcopy(evidence), "retention_limit": _EVIDENCE_LIMIT}


@router.get("/diagnostics/graph")
async def diagnostics_graph(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    nodes = [
        {"id": "frontend", "label": "Frontend", "state": "observable"},
        {"id": "api", "label": "FastAPI", "state": "observable"},
        {"id": "brain", "label": "Decision Brain", "state": "observable"},
        {"id": "models", "label": "Model Router", "state": "pending_health_check" if _ROUTES else "unconfigured"},
        {"id": "data", "label": "Market Data", "state": "observable"},
        {"id": "risk", "label": "Risk Gates", "state": "fail_closed"},
        {"id": "sandbox", "label": "Restricted Sandbox", "state": "paper_only"},
        {"id": "connectors", "label": "External Connectors", "state": "scoped"},
    ]
    edges = [
        {"from": "frontend", "to": "api", "relationship": "requests"},
        {"from": "api", "to": "brain", "relationship": "delegates"},
        {"from": "brain", "to": "models", "relationship": "routes"},
        {"from": "brain", "to": "data", "relationship": "observes"},
        {"from": "brain", "to": "risk", "relationship": "must_pass"},
        {"from": "brain", "to": "sandbox", "relationship": "simulates"},
        {"from": "brain", "to": "connectors", "relationship": "authorized_read_only"},
    ]
    return {
        "status": "read_only",
        "nodes": nodes,
        "edges": edges,
        "live_mutations": False,
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/proposals")
async def create_proposal(request: ProposalRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    proposal = {
        "id": _id("proposal", [user.sub, request.title, request.changes]),
        "title": request.title,
        "kind": request.kind,
        "scope": request.scope,
        "reason": request.reason,
        "changes": request.changes,
        "evidence_ids": request.evidence_ids,
        "rollback_plan": request.rollback_plan,
        "status": "pending",
        "created_by": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "rollback": {"required": True, "checkpoint": "created-before-apply", "automatic": True},
        "required_approvals": 2 if request.kind in {"repair", "upgrade"} else 1,
    }
    _PROPOSALS.append(proposal)
    _save_state(user.sub)
    return {"proposal": copy.deepcopy(proposal), "message": "Proposal created. No change has been applied."}


@router.post("/upgrades/propose")
async def propose_upgrade(request: UpgradeRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    proposal = {
        "id": _id("upgrade", [user.sub, request.component, request.target]),
        "title": f"Upgrade {request.component} to {request.target}",
        "kind": "upgrade",
        "scope": request.component,
        "reason": "Versioned upgrade requires compatibility and migration review",
        "changes": {
            "target": request.target,
            "compatibility_checks": request.compatibility_checks,
            "migration_plan": request.migration_plan,
        },
        "evidence_ids": [],
        "rollback_plan": "Restore previous version from checkpoint and rerun compatibility gates.",
        "status": "pending",
        "created_by": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "required_approvals": 2,
        "rollback": {"required": True, "automatic_on_failed_health_gate": True},
    }
    _PROPOSALS.append(proposal)
    _save_state(user.sub)
    return {
        "proposal": copy.deepcopy(proposal),
        "message": "Upgrade proposal created. Compatibility checks and human approvals are required before any execution.",
    }


@router.get("/proposals")
async def proposals(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": list(reversed(copy.deepcopy(_PROPOSALS))), "approval_required": True}


@router.post("/approvals")
async def decide_approval(request: ApprovalRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    proposal = next((p for p in _PROPOSALS if p["id"] == request.proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    expires_at = datetime.fromisoformat(proposal["expires_at"])
    if expires_at <= datetime.now(UTC):
        proposal["status"] = "expired"
        _save_state(user.sub)
        raise HTTPException(status_code=409, detail="Proposal approval window has expired")
    if any(a["proposal_id"] == request.proposal_id and a["approver"] == user.sub for a in _APPROVALS):
        raise HTTPException(status_code=409, detail="This approver has already decided on the proposal")
    decision = {
        "proposal_id": request.proposal_id,
        "approver": user.sub,
        "approver_role": getattr(user, "role", "") or "",
        "decision": request.decision,
        "reason": request.reason,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _APPROVALS.append(decision)
    if request.decision == "reject":
        proposal["status"] = "rejected"
    else:
        approvals = [a for a in _APPROVALS if a["proposal_id"] == request.proposal_id and a["decision"] == "approve"]
        distinct_approvers = {a["approver"] for a in approvals}
        # Quorum rule (plan Part 1B.2). "An approver cannot decide twice" was
        # already enforced above and is correct, but both approvers could be
        # admins -- so two admins could approve a repair between them with no
        # superadmin involved, which is the overtake case this closes.
        needs_superadmin = proposal["kind"] in QUORUM_NEEDS_SUPERADMIN_KINDS
        has_superadmin = any(a.get("approver_role") == "superadmin" for a in approvals)
        quorum_met = len(distinct_approvers) >= proposal["required_approvals"] and (
            has_superadmin or not needs_superadmin
        )
        if quorum_met:
            proposal["status"] = "approved_pending_execution"
        elif needs_superadmin and not has_superadmin:
            proposal["quorum_pending"] = "awaiting_superadmin_approval"
    _save_state(user.sub)
    return {
        "proposal": copy.deepcopy(proposal),
        "decision": decision,
        "message": "Approval recorded. Execution remains separately gated.",
    }


@router.post("/proposals/{proposal_id}/checkpoint")
async def create_proposal_checkpoint(proposal_id: str, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    proposal = next((p for p in _PROPOSALS if p["id"] == proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    checkpoint = {
        "id": _id("checkpoint", [proposal_id, datetime.now(UTC).isoformat()]),
        "proposal_id": proposal_id,
        "status": "ready",
        "scope": proposal["scope"],
        "captured_at": datetime.now(UTC).isoformat(),
        "captured_by": user.sub,
        "restore_target": "last-known-good",
        "live_mutation": False,
    }
    proposal.setdefault("checkpoints", []).append(checkpoint)
    _save_state(user.sub)
    return {"checkpoint": checkpoint, "message": "Checkpoint recorded before any restricted execution."}


def _validation_status(checks: dict[str, bool], environment: str) -> str:
    """The verdict follows the checks, never the environment name.

    Canary still requires paper to have passed first -- that ordering was
    correct and is kept -- but it is now an additional constraint on a real
    result rather than the whole of it.
    """
    if not all(checks.values()):
        failed = ", ".join(name for name, ok in checks.items() if not ok)
        return f"failed:{failed}"
    if environment == "canary":
        return "blocked_until_paper_passes"
    return "passed"


@router.post("/proposals/validate")
async def validate_proposal(request: ValidationRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    proposal = next((p for p in _PROPOSALS if p["id"] == request.proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] not in {"pending", "approved_pending_execution"}:
        raise HTTPException(status_code=409, detail="Proposal is not eligible for validation")
    if datetime.fromisoformat(proposal["expires_at"]) <= datetime.now(UTC):
        proposal["status"] = "expired"
        _save_state(user.sub)
        raise HTTPException(status_code=409, detail="Proposal validation window has expired")
    if request.environment == "canary" and not proposal.get("checkpoints"):
        raise HTTPException(status_code=409, detail="A last-known-good checkpoint is required before canary validation")
    # Every value here is an observation. Three of them used to be the literal
    # True, and the verdict was an expression over the environment *name*, so
    # this endpoint could not say no -- while execute_proposal required "a
    # passed validation in the selected environment" from it.
    checks = {
        "secrets_redacted": _changes_are_redacted(proposal.get("changes", {}) or {}),
        "live_trading_disabled": _live_trading_is_disabled(),
        "rollback_checkpoint_planned": _rollback_plan_is_real(proposal),
        "checkpoint_present": bool(proposal.get("checkpoints")),
        "human_approval_present": proposal["status"] == "approved_pending_execution",
        # Task 11: promotion to canary additionally requires a passing eval
        # score. Fail-closed -- no report refuses.
        "eval_gate_passed": _eval_gate_allows(request.environment)[0],
    }
    validation = {
        "id": _id("validation", [request.proposal_id, request.environment]),
        "proposal_id": request.proposal_id,
        "environment": request.environment,
        "status": _validation_status(checks, request.environment),
        "checks": checks,
        "validated_by": user.sub,
        "validated_at": datetime.now(UTC).isoformat(),
    }
    proposal.setdefault("validations", []).append(validation)
    _save_state(user.sub)
    return {"validation": validation, "message": "Validation completed without applying the proposal."}


@router.post("/proposals/execute")
async def execute_proposal(
    request: ProposalExecutionRequest, user: TokenPayload = Depends(_superadmin_2fa)
) -> dict[str, Any]:
    proposal = next((p for p in _PROPOSALS if p["id"] == request.proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] != "approved_pending_execution":
        raise HTTPException(status_code=409, detail="Proposal requires the required human approvals")
    if datetime.fromisoformat(proposal["expires_at"]) <= datetime.now(UTC):
        proposal["status"] = "expired"
        _save_state(user.sub)
        raise HTTPException(status_code=409, detail="Proposal approval window has expired")
    if request.confirmation != "EXECUTE APPROVED PROPOSAL":
        raise HTTPException(status_code=400, detail="Explicit execution confirmation is required")
    if not proposal.get("checkpoints"):
        raise HTTPException(status_code=409, detail="Proposal requires a checkpoint before execution")
    validations = [
        item
        for item in proposal.get("validations", [])
        if item["environment"] == request.environment and item["status"] == "passed"
    ]
    if not validations:
        raise HTTPException(status_code=409, detail="Proposal requires a passed validation in the selected environment")
    execution = {
        "id": _id("proposal-execution", [request.proposal_id, request.environment, datetime.now(UTC).isoformat()]),
        "proposal_id": request.proposal_id,
        "environment": request.environment,
        "status": "simulated_no_side_effect",
        "checkpoint": proposal["checkpoints"][-1]["id"],
        "rollback_ready": True,
        "live_mutation": False,
        "executed_by": user.sub,
        "executed_at": datetime.now(UTC).isoformat(),
    }
    proposal["status"] = "executed_reviewable_simulation"
    proposal["last_execution"] = execution
    _save_state(user.sub)
    return {
        "proposal": copy.deepcopy(proposal),
        "execution": execution,
        "message": "Proposal simulation completed; no production, live trading, credentials, or security controls were mutated.",
    }


@router.post("/proposals/{proposal_id}/rollback")
async def rollback_proposal(proposal_id: str, user: TokenPayload = Depends(_superadmin_2fa)) -> dict[str, Any]:
    proposal = next((p for p in _PROPOSALS if p["id"] == proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] not in {"pending", "approved_pending_execution", "executed_reviewable_simulation"}:
        raise HTTPException(status_code=409, detail="Proposal is not eligible for rollback")
    if not proposal.get("checkpoints"):
        raise HTTPException(status_code=409, detail="Rollback requires a recorded checkpoint")
    proposal["status"] = "rollback_requested"
    proposal["rollback_requested_by"] = user.sub
    proposal["rollback_requested_at"] = datetime.now(UTC).isoformat()
    proposal["rollback_checkpoint"] = proposal["checkpoints"][-1]["id"]
    _save_state(user.sub)
    return {
        "proposal": copy.deepcopy(proposal),
        "message": "Rollback recorded for the restricted change runner; no live mutation was performed.",
    }


@router.get("/integrations")
async def integrations(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {
        "items": copy.deepcopy(_INTEGRATIONS),
        "secret_values": "never_returned",
        "external_access": "allowlisted_and_scope_limited",
    }


@router.post("/integrations/action")
async def integration_action(
    request: IntegrationAction, user: TokenPayload = Depends(_superadmin_2fa)
) -> dict[str, Any]:
    await _enforce_rate_limit(user)
    item = next((entry for entry in _INTEGRATIONS if entry["id"] == request.integration_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Integration not found")
    if request.action == "authorize":
        item["status"] = "authorization_required"
        item["requested_scopes"] = sorted(set(request.scopes))
        message = (
            "Authorization must complete through the managed connector flow; no token was accepted from this request."
        )
    elif request.action == "revoke":
        item["status"] = "revoked"
        message = "Connector marked revoked. Server-side token access is denied until reauthorized."
    elif request.action == "rotate":
        item["status"] = "rotation_required"
        message = "Rotation requested through the provider; secret values remain server-only."
    else:
        message = "Health probe recorded as pending provider verification."
    item["last_action"] = {
        "action": request.action,
        "reason": request.reason,
        "actor": user.sub,
        "at": datetime.now(UTC).isoformat(),
    }
    _save_state(user.sub)
    return {
        "integration": {
            key: value
            for key, value in copy.deepcopy(item).items()
            if key not in {"secret", "token_value", "access_token", "refresh_token"}
        },
        "message": message,
    }


@router.get("/chat/capabilities")
async def chat_capabilities(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {
        "streaming": True,
        "voice": "available_if_configured",
        "delegation": True,
        "citations": True,
        "tool_trace": True,
        "external_research": "connector_required",
        "dangerous_actions": "human_approval_required",
    }


__all__ = ["router"]
