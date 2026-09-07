# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§16: the operator's control over what the AI remembers about them.

Review, correct, approve a long-term fact, and delete.

## Its own router, because most of this writes

`api/ai_core.py` is asserted read-only by
`test_the_page_reads_no_endpoint_that_can_mutate`, and correcting or deleting a
memory is a write. This module already made the mistake of putting §19's
settings on that router once; it is not repeated.

## Every route is scoped to the caller

The operator comes from the token, never from the request. A memory review that
accepted an operator name would be a way to read what the AI remembers about
somebody else, which is the worst possible version of the cross-operator leak
this platform has already shipped once.

## Deletion reports what it could not reach

`POST /forget` returns `complete`, and `complete` is false when any store could
not be cleared — with the reason. An incomplete deletion reported as complete
tells the operator their data is gone when it is not, and that is worse than a
deletion that fails loudly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload, require_role

router = APIRouter(prefix="/api/ai-memory", tags=["AI Memory"])

_VIEWER_ROLE = "viewer"


def _viewer(user: TokenPayload = Depends(require_role(_VIEWER_ROLE))) -> TokenPayload:
    return user


@router.get("")
async def memory_review(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Everything remembered about the caller, by tier."""
    from ai.memory import governance

    return governance.review(operator=user.sub)


@router.get("/tiers")
async def memory_tiers(_: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """What each tier is for and how long it lasts."""
    from ai.memory import tiers

    return {
        "tiers": list(tiers.TIERS),
        "limits": dict(tiers.LIMITS),
        "retention": {
            "working": "the current turn — cleared when the turn ends",
            "session": "the current session — cleared when the session ends",
            "episodic": "significant events; survives a session",
            "project": "long-running work; survives a session",
            "long_term": "approved facts only; written through an approval, never directly",
        },
    }


@router.patch("/{entry_id}")
async def memory_correct(entry_id: str, body: dict[str, Any], user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Correct a remembered value, keeping that it was corrected.

    A 404 covers both "no such entry" and "not yours", deliberately: separating
    them turns an id into an oracle for what the AI remembers about other people.
    """
    from ai.memory import governance

    if "value" not in body:
        raise HTTPException(status_code=400, detail="a correction needs a `value`")

    corrected = governance.correct(entry_id, operator=user.sub, value=body["value"], by=user.sub)
    if corrected is None:
        raise HTTPException(status_code=404, detail="no such memory entry")
    return corrected


@router.get("/long-term/pending")
async def memory_pending_long_term(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Facts proposed for permanent retention, awaiting the caller's decision."""
    from ai.memory import governance

    return {"operator": user.sub, "pending": governance.pending_long_term(operator=user.sub)}


@router.post("/long-term/{proposal_id}/approve")
async def memory_approve_long_term(proposal_id: str, user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Keep a fact permanently. Nothing reaches long-term without this."""
    from ai.memory import governance

    return {"approved": governance.approve_long_term(proposal_id, by=user.sub), "id": proposal_id}


@router.post("/long-term/{proposal_id}/reject")
async def memory_reject_long_term(proposal_id: str, user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    from ai.memory import governance

    return {"rejected": governance.reject_long_term(proposal_id, by=user.sub), "id": proposal_id}


@router.post("/forget")
async def memory_forget(user: TokenPayload = Depends(_viewer)) -> dict[str, Any]:
    """Delete everything remembered about the caller.

    Returns what was removed AND what could not be reached. `complete` is false
    whenever anything was left behind — the durable department-memory store is
    keyed by department and has no operator column, so it says so rather than
    reporting a deletion it did not perform.
    """
    from ai.memory import governance

    return governance.forget(operator=user.sub).as_dict()
