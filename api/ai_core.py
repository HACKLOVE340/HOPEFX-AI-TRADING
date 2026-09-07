# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Read surface for the AI Core page (plan Task 13, item 18).

Every panel on that page reads one of these endpoints. That is the whole point:
the page the audit replaced rendered its state from constants, so a control
plane that had degraded looked identical to one that had not. Nothing here
computes a status from a literal — each field is read from the module that owns
it at the moment of the request.

Three rules shape the whole module:

* **Read-only.** Nothing here mutates. Every consequential action already lives
  in `api/safe_agent_platform.py` behind the Part 1B matrix and 2FA; a
  reporting surface that could also act would be a second, weaker door to the
  same room.
* **Admin is gated below superadmin.** `require_role` is a minimum-rank check,
  so an "admin" gate admits superadmins too — the reverse must not hold. An
  admin sees their own spend and their own call history; the per-operator
  breakdown and the platform total are superadmin-only, because knowing who is
  spending what is reconnaissance for the overtake case D7 closed.
* **No prompt and no credential ever leaves.** Call records carry the SHA-256
  the gateway's audit already keeps, never the text. Provider reachability is a
  boolean; the key that makes it true is never read into a response.
"""

from __future__ import annotations

from typing import Any

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ai.cache.store import shared_cache
from ai.evals import schedule as eval_schedule
from ai.evals import store as eval_store
from ai.gateway import audit, budget, providers
from ai.gateway.chain import DEFAULT_CHAINS, LOCAL_PROVIDER, resolve_chain, resolve_embedding_model
from ai.policy import roles as policy
from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-core", tags=["AI Core"])

#: The page starts at admin. Below that the AI control plane is not visible at
#: all — there is nothing on it a trader has a reason to read.
_VIEWER_ROLE = "admin"

#: How many call records a single request may return. The audit ring holds 500;
#: returning all of them on every page render is a payload nobody reads.
_DEFAULT_CALL_LIMIT = 50
_MAX_CALL_LIMIT = 200


def _viewer(user: TokenPayload = Depends(require_role(_VIEWER_ROLE))) -> TokenPayload:
    return user


def _is_superadmin(user: TokenPayload) -> bool:
    """Exact match, not rank.

    Everything superadmin-only in this module is a widening of scope — another
    operator's spend, the platform total, every operator's call history — so it
    is granted to the role that owns it and to nothing that merely outranks
    admin. A rank comparison here would re-open D7 the moment a role is added
    between the two.
    """
    return user.role == "superadmin"


def _capability_rows(role: str) -> list[dict[str, Any]]:
    """The Part 1B matrix, resolved for one role.

    The UI gates its controls on `permitted`. A button the server would refuse
    is a decorative control — the D6 defect — so the page is told what this
    caller may actually do rather than guessing from the role name.
    """
    rank = {"starter": 0, "user": 1, "trader": 2, "admin": 3, "superadmin": 4}
    caller = rank.get(role, -1)
    rows: list[dict[str, Any]] = []
    for name, capability in sorted(policy.CAPABILITIES.items()):
        admitted = policy.ROLES_ADMITTED.get(capability.tier, frozenset())
        rows.append(
            {
                "name": name,
                "tier": capability.tier,
                "min_role": capability.min_role,
                "requires_2fa": capability.requires_2fa,
                "quorum_needs_superadmin": capability.quorum_needs_superadmin,
                # Both conditions, because they are not the same question:
                # rank is what `require_role` enforces, and `ROLES_ADMITTED` is
                # the exact set the tier is meant to admit.
                "permitted": caller >= rank.get(capability.min_role, 99) and role in admitted,
            }
        )
    return rows


def _chain_rows() -> list[dict[str, Any]]:
    reachable = providers.reachability()
    rows: list[dict[str, Any]] = []
    for role in DEFAULT_CHAINS:
        legs = [
            {
                "position": index,
                "provider": leg.provider,
                "model": leg.model,
                "reachable": reachable.get(leg.provider, False),
                "local": leg.provider == LOCAL_PROVIDER,
            }
            for index, leg in enumerate(resolve_chain(role))
        ]
        usable = [leg for leg in legs if leg["reachable"]]
        rows.append(
            {
                "role": role,
                "legs": legs,
                # A chain whose later legs have no credentials has a fallback on
                # paper and one leg in practice. Reported as its own field so
                # the page can say so instead of showing three rows and implying
                # three attempts.
                "usable_legs": len(usable),
                "fallback_available": len(usable) > 1,
                "primary_reachable": bool(legs) and legs[0]["reachable"],
            }
        )
    return rows


@router.get("/capabilities")
async def ai_core_capabilities(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What this caller may do, as the server would decide it."""
    return {
        "role": user.role,
        "is_superadmin": _is_superadmin(user),
        "capabilities": _capability_rows(user.role),
        "tiers": {tier: sorted(admitted) for tier, admitted in policy.ROLES_ADMITTED.items()},
        "quorum_needs_superadmin_kinds": sorted(policy.QUORUM_NEEDS_SUPERADMIN_KINDS),
    }


def _local_runtime_status() -> dict[str, Any]:
    """What the on-hardware runtime reported, or why there is nothing to report.

    Deliberately reads the recorded status rather than probing: this is a
    page-load endpoint, and a live probe would put a network timeout in front of
    every render of the AI Core page.
    """
    try:
        from ai.local_model import autostart_enabled, get_local_model_runtime

        status = get_local_model_runtime().status()
        return {"autostart_enabled": autostart_enabled(), **status.as_dict()}
    except Exception as exc:  # reporting must never take the page down
        logger.warning("ai_core: local runtime status unavailable (%s)", exc)
        return {"autostart_enabled": False, "started": False, "refusal": "status_unavailable"}


@router.get("/chain")
async def ai_core_chain(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """The resolved chain per role, and which legs this deployment can reach."""
    embedding = resolve_embedding_model()
    rows = _chain_rows()
    routed_local = any(leg["local"] for row in rows for leg in row["legs"])
    return {
        "roles": rows,
        "providers": providers.reachability(),
        "embedding": {"provider": embedding.provider, "model": embedding.model},
        "local_provider": LOCAL_PROVIDER,
        # Optional by design and never a primary: capability drops sharply, and
        # the page has to say so rather than presenting it as an equal choice.
        "local_inference_enabled": providers.local_inference_enabled(),
        # Three separate facts, deliberately not collapsed into one flag:
        # whether a credential exists (above), whether a resolved chain actually
        # routes to it, and whether the privacy mode has made it the only leg.
        # An operator who sees "local: enabled" cannot tell from that alone
        # whether prompts are still leaving the building.
        "local_in_chain": routed_local,
        "local_only": bool(rows) and all(all(leg["local"] for leg in row["legs"]) for row in rows if row["legs"]),
        # A FOURTH fact, and the one the other three cannot supply:
        # `local_inference_enabled` above is true because OLLAMA_BASE_URL is
        # SET, which is not evidence that anything is listening on the other end
        # of it. This is what the runtime actually measured at startup, so an
        # operator can tell "configured" from "running" -- the difference
        # between a leg that is offered and a leg that can answer.
        "local_runtime": _local_runtime_status(),
    }


@router.get("/budget")
async def ai_core_budget(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Spend against the ceilings. Scope depends on the caller's role."""
    per_operator, global_ceiling = budget.limits()
    own = budget.spent(user.sub)
    body: dict[str, Any] = {
        "scope": "platform" if _is_superadmin(user) else "self",
        "operator": user.sub,
        "spent_usd": round(own, 6),
        "per_operator_ceiling_usd": per_operator,
        "headroom_usd": round(max(0.0, per_operator - own), 6),
    }
    if not _is_superadmin(user):
        return body
    body["operators"] = {operator: round(spent, 6) for operator, spent in budget._spend.items()}
    body["global_spent_usd"] = round(budget.total_spent(), 6)
    body["global_ceiling_usd"] = global_ceiling
    body["global_headroom_usd"] = round(max(0.0, global_ceiling - budget.total_spent()), 6)
    return body


# ── §5: what the Core knows about itself ──────────────────────────────────────
#
# Both GET. This router is asserted read-only by
# `test_the_page_reads_no_endpoint_that_can_mutate`, and recording a prediction
# or noting a task is a write that belongs on its own surface — the mistake this
# module already made once with the §19 notification settings.


@router.get("/self/context")
async def ai_core_conversation_context(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What is running for the caller, and what recently finished (§5).

    Scoped to the token's operator, never to a query parameter: one operator's
    work is not context for another's conversation.
    """
    from ai.core import context

    return {
        "operator": user.sub,
        "active": context.active(user.sub),
        "description": context.describe(user.sub),
    }


@router.get("/self/calibration")
async def ai_core_calibration(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """How the stated confidences have actually held up (§5).

    An agent with too few resolved predictions is reported as unchecked rather
    than as accurate — a confidence nobody has verified is the author's
    judgement, and presenting it as a measured frequency is the fake-precision
    failure §22 exists to stop.
    """
    from ai.core import calibration

    records = calibration.summary()
    return {
        "operator": user.sub,
        "minimum_sample": calibration.MIN_SAMPLE,
        "tolerance": calibration.TOLERANCE,
        "agents": records,
        "note": (
            "Calibration annotates a stated confidence; it never rewrites one. "
            f"An agent needs {calibration.MIN_SAMPLE} resolved predictions in a "
            "confidence band before any rate is reported for it."
        ),
    }


@router.get("/self/depths")
async def ai_core_depths(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """The explanation registers, and the rule they all obey (§5)."""
    from ai.core import DEPTHS

    return {
        "depths": list(DEPTHS),
        "invariant": (
            "Every number, the counter-thesis, and what would change the conclusion "
            "survive every depth. A shorter version missing one of those is a "
            "different argument, not a simpler one."
        ),
    }


@router.get("/calls")
async def ai_core_calls(
    user: TokenPayload = Depends(_viewer),
    limit: int = Query(_DEFAULT_CALL_LIMIT, ge=1, le=_MAX_CALL_LIMIT),
) -> dict[str, Any]:
    """Recent model calls, newest first. Prompts are digests, never text."""
    records = audit.records()
    if not _is_superadmin(user):
        records = [record for record in records if record.get("operator") == user.sub]
    recent = list(reversed(records))[:limit]
    return {
        "scope": "platform" if _is_superadmin(user) else "self",
        "calls": recent,
        "returned": len(recent),
        "total_visible": len(records),
        # Stated rather than implied: someone reading this page needs to know
        # the window is bounded before concluding a call never happened.
        "retention": "in-memory ring, newest 500 calls",
    }


@router.get("/cache")
async def ai_core_cache(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """The response cache, or an honest zero when no deployment installed one."""
    cache = shared_cache()
    if cache is None:
        return {
            "enabled": False,
            "entries": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
            "detail": "no shared response cache is installed; every call reaches a provider",
        }
    stats = cache.stats()
    return {"enabled": True, **stats}


@router.get("/evals")
async def ai_core_evals(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """The latest eval report and what the promotion gate would do with it.

    "No report" is a state the page must show. The gate refuses on None — fail
    closed — and a UI that rendered that as a blank panel would hide the reason
    a promotion is being refused.
    """
    from api.safe_agent_platform import _eval_gate_allows, get_eval_report

    # The accessor the GATE uses, not the private module global. Reading
    # `_EVAL_REPORT` directly meant the page said "no report" while the gate
    # promoted happily from a report another worker had filed in Redis — the
    # page and the gate disagreeing about the same decision.
    report = get_eval_report()
    allowed, detail = _eval_gate_allows("canary")
    summary = None
    if report is not None:
        summary = {
            "score": getattr(report, "score", None),
            "total": getattr(report, "total", None),
            "passed": getattr(report, "passed", None),
            "failed_case_ids": list(getattr(report, "failed_case_ids", ()) or ()),
            "ran_at": getattr(report, "ran_at", None),
        }
    return {
        "report": summary,
        "promotion_allowed": allowed,
        "promotion_detail": detail,
        "gate_target": "canary",
    }


_DISCOVERY_TTL_S = 60.0
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _discover(provider: str | None = None) -> dict[str, Any]:
    """Ask the vendors, concurrently, and cache the answer briefly.

    Concurrent because eight vendors at a ten-second timeout is eighty seconds
    served one after another, and a settings page that blocks for eighty seconds
    is a page nobody opens. One slow vendor should cost its own timeout, not
    everyone else's.

    Cached for a minute because this is a page-load endpoint and the answer
    changes when a vendor ships a model, not when an operator refreshes. Without
    it, opening settings sends eight outbound requests every time.
    """
    from concurrent.futures import ThreadPoolExecutor

    from ai.gateway import discovery, vendors

    names = [provider] if provider else [*vendors.OPENAI_COMPATIBLE, discovery.LOCAL_PROVIDER]
    now = time.monotonic()
    fresh = {
        name: cached
        for name in names
        if (entry := _discovery_cache.get(name)) and now - entry[0] < _DISCOVERY_TTL_S
        for cached in (entry[1],)
    }
    stale = [name for name in names if name not in fresh]

    if stale:
        with ThreadPoolExecutor(max_workers=min(8, len(stale))) as pool:
            for name, result in zip(stale, pool.map(discovery.list_models, stale), strict=True):
                fresh[name] = result
                _discovery_cache[name] = (now, result)
    return fresh


@router.get("/models")
async def ai_core_models(
    provider: str | None = Query(default=None, description="Ask one vendor instead of all"),
    _: TokenPayload = Depends(_viewer),
) -> dict[str, Any]:
    """Which models each vendor currently serves.

    The model chain editor offers what exists rather than what was committed
    months ago: a vendor shipping a model used to mean a code change, and a
    vendor retiring one meant a chain leg that failed at call time.

    `configured` is a boolean. The credential that makes a vendor reachable
    never crosses this boundary -- an operator needs to know a key is set, not
    what it is.
    """
    try:
        results = _discover(provider)
    except KeyError:
        # An unknown provider name is a bad request, not an empty vendor list.
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}") from None

    rows = [row.as_dict() if hasattr(row, "as_dict") else row for _name, row in sorted(results.items())]
    return {
        "providers": rows,
        "configured_count": sum(1 for row in rows if row.get("configured")),
        "total_models": sum(len(row.get("models") or []) for row in rows),
    }


@router.get("/departments")
async def ai_core_departments(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """The Cluster A department directory, and what is actually wired.

    `implemented` per action is the honest field. A department whose actions are
    declared but unhandled looks identical to a working one in every listing
    that omits it — and the tool bus refuses those with `tool_not_implemented`
    rather than a successful no-op, so the page should say which is which.
    """
    try:
        from ai.departments import PERMISSIONS_VERSION, all_actions, directory, implemented_actions

        rows = directory()
        return {
            "departments": rows,
            "permissions_version": PERMISSIONS_VERSION,
            "actions_declared": len(all_actions()),
            "actions_implemented": len(implemented_actions()),
        }
    except Exception as exc:  # reporting must never take the page down
        logger.warning("ai_core: department directory unavailable (%s)", exc)
        return {
            "departments": [],
            "permissions_version": "",
            "actions_declared": 0,
            "actions_implemented": 0,
            "error": "directory_unavailable",
        }


@router.get("/capabilities/registry")
async def ai_core_capability_registry(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What the AI Hub specification asks for, and how much of it is real.

    §30 requires that a capability which cannot be built immediately still
    exists in the system as a registry entry and roadmap point, "rather than
    being silently omitted". This is where that becomes visible: 200-odd
    capabilities, each traced to the specification section that asks for it.

    **`verified` is reported apart from `live` deliberately.** One is what the
    registry was told; the other is what `verify()` measured by resolving each
    claim's evidence. `scripts/invariant_coverage.py` collapsed that distinction
    (F176) and could not print anything but full coverage while three of the
    components it certified were unprotected. `discrepancies` is the other half
    of the same rule: a claim whose module or symbol has since disappeared is
    reported here, never quietly dropped from the count.
    """
    from ai.hub.capabilities import coverage

    return coverage()


@router.get("/capabilities/app")
async def ai_core_app_surface(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What the PLATFORM can do, derived from the running route table.

    The AI Hub specification asks (§4, §31) for the application to be a set of
    capabilities the AI can see, rather than the AI being a component that only
    knows the endpoints somebody remembered to wire. Sixty-five routers are
    mounted; a hand-maintained list would be wrong within a day, and wrong in
    the direction nobody notices.

    **Discovery is not capability.** `visible` and `invokable` are reported
    separately and deliberately: knowing that order placement exists must not
    imply the AI can place one. Execution stays behind `ai/tools/bus.py`, and
    every write here is unreachable unless a tool was registered for it.
    """
    from ai.hub.app_surface import describe_app

    return describe_app().summary()


@router.get("/summary")
async def ai_core_summary(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """One request for the page header, so it does not need seven round trips."""
    rows = _chain_rows()
    reasoning = next((row for row in rows if row["role"] == "reasoning"), None)
    reachable = providers.reachability()
    records = audit.records()
    visible = records if _is_superadmin(user) else [r for r in records if r.get("operator") == user.sub]
    unserved = [record for record in visible if record.get("served_by") is None]
    cache = shared_cache()
    return {
        "role": user.role,
        "is_superadmin": _is_superadmin(user),
        "reasoning_primary": (reasoning["legs"][0]["model"] if reasoning and reasoning["legs"] else None),
        "reasoning_primary_reachable": bool(reasoning and reasoning["primary_reachable"]),
        "fallback_available": bool(reasoning and reasoning["fallback_available"]),
        "providers_reachable": sorted(name for name, ok in reachable.items() if ok),
        "providers_unreachable": sorted(name for name, ok in reachable.items() if not ok),
        "local_inference_enabled": providers.local_inference_enabled(),
        "calls_recorded": len(visible),
        # A call no leg served is the failure the gateway exists to make
        # visible. Surfaced in the header because it is the one number that
        # should never be quietly non-zero.
        "calls_unserved": len(unserved),
        "spent_usd": round(budget.spent(user.sub), 6),
        "cache_enabled": cache is not None,
        # Which of the AI's durable stores are actually installed.
        #
        # Every one of these fails in the same silent direction: a per-process
        # spend ceiling still refuses calls, an in-memory audit trail still
        # records them, a per-process eval report still gates promotions. They
        # just do it with a fraction of the state they appear to have, and
        # nothing said so — `budget.store_is_shared`, `audit.durable_sink_installed`
        # and `evals.store.store_is_shared` were each described in
        # `core/startup_factories.py` as what "the health surface reads back",
        # and no health surface read any of them.
        "durability": {
            "budget_shared": budget.store_is_shared(),
            "audit_durable": audit.durable_sink_installed(),
            "eval_report_shared": eval_store.store_is_shared(),
            # None means the schedule is off, which is the default and a
            # legitimate choice — every eval case is a paid model call.
            "eval_schedule_hours": (None if (interval := eval_schedule.interval_s()) is None else interval / 3600.0),
        },
    }


@router.get("/telemetry")
async def ai_core_telemetry(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """§22. What the platform can actually measure about itself, and what it cannot.

    The rule this endpoint exists to hold: **an unmeasured metric is absent,
    never zero.** Every number here is either a real reading or `null` with a
    reason, and `unmeasured` lists the second group separately so a caller does
    not have to infer it from the first.

    That is not a hypothetical discipline. `infrastructure/metrics.py` returns
    early when psutil is unavailable, leaving `system_cpu_percent` unset — and
    an unset `Gauge` reads back 0.0, so the same registry's two readers
    disagree about whether the machine is idle or unknown.

    The `neural_engine` block is bound to real model state: which vendors this
    deployment can reach, which of their breakers are open, whether anything
    has succeeded. The specification lists such an indicator among what already
    exists; it did not, and a decorative one that pulses whatever the model
    layer is doing would be the zero gauge in different clothes.
    """
    from ai import telemetry

    # No tool bus and no watcher count are passed, and both come back as
    # UNMEASURED with a reason rather than as zero. That is deliberate, not an
    # oversight: `build_tool_bus()` constructs a fresh bus per caller, so there
    # is no process-wide audit trail to count, and reporting a brand-new bus's
    # empty audit as "0 denials" would be this section's own defect — a
    # reassuring number produced by never having looked.
    return telemetry.snapshot(runner=_job_runner())


def _job_runner() -> Any:
    """The live job pool, or None when there is not one to observe.

    None matters: `agents.agent_health` reports an absent runner as unmeasured
    rather than as an idle pool, which is the same rule as every reading here.
    """
    try:
        from ai.jobs.runner import get_runner

        return get_runner()
    except Exception:
        return None


__all__ = ["router"]
