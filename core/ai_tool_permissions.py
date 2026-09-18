from __future__ import annotations

"""Versioned, fail-closed permissions for AI skills and tools."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    PAPER_TRADING = "paper_trading"
    LIVE_TRADING = "live_trading"
    IRREVERSIBLE = "irreversible"


@dataclass(frozen=True)
class ToolPermission:
    tool_name: str
    version: str
    risk: ToolRisk
    enabled: bool = True
    requires_approval: bool = False


@dataclass(frozen=True)
class ToolReview:
    allowed: bool
    reason_codes: tuple[str, ...]
    permission_version: str


class ToolPermissionRegistry:
    def __init__(self, permissions: Iterable[ToolPermission], version: str) -> None:
        if not version.strip():
            raise ValueError("permission registry version is required")
        self._version = version
        self._permissions = {permission.tool_name: permission for permission in permissions}

    @property
    def version(self) -> str:
        return self._version

    def review(self, tool_name: str, *, approved: bool = False, live_mode: bool = False) -> ToolReview:
        permission = self._permissions.get(tool_name)
        if permission is None:
            return ToolReview(False, ("tool_not_registered",), self._version)
        if not permission.enabled:
            return ToolReview(False, ("tool_disabled",), self._version)
        if permission.risk in {ToolRisk.LIVE_TRADING, ToolRisk.IRREVERSIBLE} and not approved:
            return ToolReview(False, ("human_approval_required",), self._version)
        if permission.risk is ToolRisk.LIVE_TRADING and not live_mode:
            return ToolReview(False, ("live_tool_requires_live_mode",), self._version)
        if permission.risk is ToolRisk.IRREVERSIBLE and not approved:
            return ToolReview(False, ("irreversible_action_blocked",), self._version)
        return ToolReview(True, ("permission_granted",), self._version)


__all__ = ["ToolPermission", "ToolPermissionRegistry", "ToolReview", "ToolRisk"]
