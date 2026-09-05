from __future__ import annotations

"""Superadmin review endpoints for AI recovery decisions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload
from core.ai_tool_permissions import ToolPermissionRegistry, ToolPermission, ToolRisk
from ._shared import _log_superadmin_action, _require_superadmin

router = APIRouter(prefix="/superadmin/ai-operations", tags=["ai-operations"])

_registry = ToolPermissionRegistry(
    (
        ToolPermission("market.read", "1.0.0", ToolRisk.READ_ONLY),
        ToolPermission("paper.order", "1.0.0", ToolRisk.PAPER_TRADING),
        ToolPermission("live.order", "1.0.0", ToolRisk.LIVE_TRADING),
    ),
    version="permissions-2026-09-05",
)


class ToolReviewBody(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128)
    approved: bool = False
    live_mode: bool = False


@router.get("/permissions")
async def get_permissions(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return {"version": _registry.version, "tools": sorted(_registry._permissions)}


@router.post("/permissions/review")
async def review_permission(
    body: ToolReviewBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    review = _registry.review(body.tool_name, approved=body.approved, live_mode=body.live_mode)
    _log_superadmin_action(user, "ai_tool_permission_review", f"tool={body.tool_name} allowed={review.allowed}")
    return {
        "allowed": review.allowed,
        "reason_codes": review.reason_codes,
        "permission_version": review.permission_version,
    }


@router.post("/recovery/assess")
async def assess_recovery(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    from security.self_healer import get_healer

    healer = get_healer()
    if not hasattr(healer, "run_ai_recovery_assessment"):
        raise HTTPException(status_code=503, detail="AI recovery assessment is unavailable")
    assessment = await healer.run_ai_recovery_assessment("operator-assessment")
    _log_superadmin_action(user, "ai_recovery_assessment", assessment["decision"]["action"])
    return assessment


@router.get("/recovery/latest")
async def latest_recovery_report(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    from security.self_healer import get_healer

    report = get_healer().get_last_diagnostic_report()
    return {"report": report, "repair_applied": False, "execution_mode": "assessment_only"}
