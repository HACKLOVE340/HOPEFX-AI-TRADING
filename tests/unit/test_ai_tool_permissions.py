from __future__ import annotations

from core.ai_tool_permissions import (
    ToolPermission,
    ToolPermissionRegistry,
    ToolRisk,
)


def _registry() -> ToolPermissionRegistry:
    return ToolPermissionRegistry(
        [
            ToolPermission("market.read", "1.0.0", ToolRisk.READ_ONLY),
            ToolPermission("paper.order", "1.0.0", ToolRisk.PAPER_TRADING),
            ToolPermission("live.order", "1.0.0", ToolRisk.LIVE_TRADING),
            ToolPermission("account.close", "1.0.0", ToolRisk.IRREVERSIBLE),
        ],
        version="permissions-2026-09-05",
    )


def test_unknown_tools_fail_closed() -> None:
    review = _registry().review("unknown")

    assert review.allowed is False
    assert review.reason_codes == ("tool_not_registered",)


def test_read_only_and_paper_tools_are_allowed() -> None:
    registry = _registry()

    assert registry.review("market.read").allowed is True
    assert registry.review("paper.order").allowed is True


def test_live_trading_requires_approval_and_live_mode() -> None:
    registry = _registry()

    assert registry.review("live.order").reason_codes == ("human_approval_required",)
    assert registry.review("live.order", approved=True).reason_codes == ("live_tool_requires_live_mode",)
    assert registry.review("live.order", approved=True, live_mode=True).allowed is True


def test_irreversible_tools_require_approval() -> None:
    review = _registry().review("account.close")

    assert review.allowed is False
    assert review.reason_codes == ("human_approval_required",)
