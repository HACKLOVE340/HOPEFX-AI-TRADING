# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§19 notification policy, as an operator-facing surface.

## Why this is not part of `api/ai_core.py`

It was, until `test_the_page_reads_no_endpoint_that_can_mutate` failed. That
test asserts the AI Core router exposes `GET` and `HEAD` only — "read-only by
construction, asserted rather than intended" — and it is right: the AI Core page
is the governance and observability surface, and a governance screen that can
mutate is a governance screen somebody can be phished through.

Setting quiet hours and adding a watch are mutations, so they belong on their
own router. Mounting them at a path *under* `/api/ai-core/` on a second router
object would have satisfied the assertion while defeating its purpose, which is
worse than failing it.

## Every route is scoped to the caller

The operator comes from the token, never from the request. A `?operator=`
parameter, or an `operator` field honoured from a POST body, would be the
cross-operator leak this platform already shipped once in the AI job manager —
rebuilt here on the channel that carries risk alerts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload, require_role

router = APIRouter(prefix="/api/ai-notifications", tags=["AI Notifications"])

_VIEWER_ROLE = "viewer"


def _viewer(user: TokenPayload = Depends(require_role(_VIEWER_ROLE))) -> TokenPayload:
    return user


@router.get("")
async def notification_inbox(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What the policy delivered, what it is holding, and what is unacknowledged.

    `deferred` is listed alongside `inbox` deliberately. Quiet hours schedule
    information rather than losing it, and an operator waking at seven has to be
    able to find what happened at three.
    """
    from ai.notify import service

    return {
        "operator": user.sub,
        "inbox": service.inbox_for(user.sub),
        "deferred": service.deferred_for(user.sub),
        "outstanding": service.outstanding(user.sub),
    }


@router.post("/{key}/acknowledge")
async def acknowledge_notification(key: str, user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Stop a notification escalating. Acknowledging is a statement that it was seen."""
    from ai.notify import service

    return {"acknowledged": service.acknowledge(key, operator=user.sub), "key": key}


@router.post("/release")
async def release_deferred_notifications(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Deliver anything whose hold has expired.

    A sleep-mode deferral has no scheduled end and stays held until the operator
    turns sleep mode off; releasing it on a timer would be inventing a delivery
    time nobody set.
    """
    from ai.notify import service

    return {"released": service.release_deferred(user.sub)}


@router.get("/policy")
async def notification_policy(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """This operator's settings, and the floor that no setting can turn off."""
    from ai.notify import CRITICAL_FLOOR_REASON
    from ai.notify import service

    policy = service.policy_for(user.sub)
    return {
        "operator": user.sub,
        "sleeping": policy.sleeping,
        "quiet_hours": (
            None
            if policy.quiet_hours is None
            else {
                "start_hour": policy.quiet_hours.start_hour,
                "end_hour": policy.quiet_hours.end_hour,
                "tz_offset_hours": policy.quiet_hours.tz_offset_hours,
            }
        ),
        "max_per_minute": policy.max_per_minute,
        "escalate_after_s": policy.escalate_after_s,
        "dedup_window_s": policy.dedup_window_s,
        # Reported, not merely implemented. An operator turning on quiet hours
        # deserves to see on the same screen what quiet hours cannot do.
        "critical_floor": CRITICAL_FLOOR_REASON,
    }


@router.put("/policy")
async def set_notification_policy(
    body: dict[str, Any],
    user: TokenPayload = Depends(_viewer),
) -> dict[str, Any]:
    """Set quiet hours, sleep mode and rate limits for the calling operator."""
    from ai.notify import Policy, QuietHours
    from ai.notify import service

    current = service.policy_for(user.sub)
    quiet_raw = body.get("quiet_hours", "__unset__")
    if quiet_raw == "__unset__":
        quiet = current.quiet_hours
    elif quiet_raw is None:
        quiet = None
    else:
        try:
            quiet = QuietHours(
                start_hour=int(quiet_raw["start_hour"]),
                end_hour=int(quiet_raw["end_hour"]),
                tz_offset_hours=float(quiet_raw.get("tz_offset_hours", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"quiet_hours is not valid: {exc}") from exc

    try:
        updated = Policy(
            operator=user.sub,
            quiet_hours=quiet,
            sleeping=bool(body.get("sleeping", current.sleeping)),
            max_per_minute=int(body.get("max_per_minute", current.max_per_minute)),
            escalate_after_s=(
                None
                if body.get("escalate_after_s", current.escalate_after_s) is None
                else float(body["escalate_after_s"])
                if "escalate_after_s" in body
                else current.escalate_after_s
            ),
            dedup_window_s=float(body.get("dedup_window_s", current.dedup_window_s)),
            wake_conditions=current.wake_conditions,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service.set_policy(user.sub, updated)
    return await notification_policy(user)


@router.get("/watches")
async def notification_watches(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """This operator's watches. There is no listing that spans operators."""
    from ai.notify import service

    waking = {(w.subject, w.comparison, w.threshold) for w in service.wake_conditions_for(user.sub)}
    return {
        "operator": user.sub,
        "watches": [
            {
                "subject": w.subject,
                "comparison": w.comparison,
                "threshold": w.threshold,
                "severity": w.severity,
                # Shown, because a watch that can wake you at three in the
                # morning must be distinguishable from one that cannot.
                "wake": (w.subject, w.comparison, w.threshold) in waking,
            }
            for w in service.watches_for(user.sub)
        ],
    }


@router.post("/watches")
async def add_notification_watch(body: dict[str, Any], user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Add a threshold watch, owned by the caller.

    `operator` is taken from the token and never from the body: accepting it
    from the request would let anyone create a watch that notifies somebody else.
    """
    from ai.notify import Watch
    from ai.notify import service

    try:
        watch = Watch(
            operator=user.sub,
            subject=str(body["subject"]),
            comparison=str(body["comparison"]),
            threshold=float(body["threshold"]),
            severity=str(body.get("severity", "important")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"watch is not valid: {exc}") from exc

    # A wake condition pierces sleep mode and quiet hours, so it is opt-in and
    # explicit. Defaulting it on would let a routine threshold wake somebody.
    service.add_watch(watch, wake=bool(body.get("wake", False)))
    return await notification_watches(user)
