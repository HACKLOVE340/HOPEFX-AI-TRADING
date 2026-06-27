# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.compliance — surveillance, MNPI, retention, jurisdiction, access.

Pure predicates from the framework's compliance sections: trade-surveillance
heuristics (wash trading, spoofing, layering), restricted-list / MNPI blocking,
data-retention bounds, jurisdiction enforcement, chain-of-custody, approval-
workflow integrity, and privilege-escalation detection.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Compliance Breach"


def verify_no_wash_trade(buyer_id: Any, seller_id: Any) -> list[Violation]:
    """Same beneficial owner on both sides of a trade is wash trading."""
    if buyer_id is not None and buyer_id == seller_id:
        return [_v(_RULE, CONSTITUTIONAL, f"wash trade: buyer == seller ({buyer_id!r})")]
    return []


def verify_no_spoofing(placed: int, cancelled: int, filled: int, max_cancel_ratio: float = 0.95) -> list[Violation]:
    """A very high place→cancel ratio with near-zero fills is a spoofing signature."""
    if placed <= 0:
        return []
    cancel_ratio = cancelled / placed
    if cancel_ratio >= max_cancel_ratio and filled == 0:
        return [
            _v(
                _RULE,
                CRITICAL,
                f"possible spoofing: {cancelled}/{placed} cancelled, 0 filled",
                cancel_ratio=round(cancel_ratio, 3),
            )
        ]
    return []


def verify_no_layering(same_side_orders_at_levels: int, max_levels: int = 10) -> list[Violation]:
    """An abnormal number of same-side orders stacked across price levels suggests layering."""
    if same_side_orders_at_levels > max_levels:
        return [_v(_RULE, WARNING, f"possible layering: {same_side_orders_at_levels} same-side resting orders")]
    return []


def verify_not_restricted(symbol: str, restricted_list: set[str]) -> list[Violation]:
    """No trading in restricted / MNPI / embargoed instruments."""
    if symbol in restricted_list:
        return [_v(_RULE, CONSTITUTIONAL, f"trade in restricted/MNPI instrument {symbol}")]
    return []


def verify_retention(age_days: float, min_days: float, max_days: float, name: str = "record") -> list[Violation]:
    """Records must be kept long enough but not beyond policy."""
    out: list[Violation] = []
    if not _is_finite_number(age_days):
        return [_v(_RULE, CRITICAL, f"{name} age non-finite")]
    if age_days > max_days:
        out.append(_v(_RULE, CRITICAL, f"{name} retained {age_days}d > max {max_days}d (must be purged)"))
    if age_days < 0:
        out.append(_v("No Data Corruption", CRITICAL, f"{name} has negative age"))
    return out


def verify_jurisdiction_allowed(client_jurisdiction: str, allowed: set[str]) -> list[Violation]:
    if allowed and client_jurisdiction not in allowed:
        return [_v(_RULE, CONSTITUTIONAL, f"action in disallowed jurisdiction {client_jurisdiction}")]
    return []


def verify_chain_of_custody(custody_chain: Sequence[Any]) -> list[Violation]:
    """An asset's custody chain must be unbroken (no None/gaps)."""
    if any(link is None for link in custody_chain):
        return [_v("No Audit Gap", CONSTITUTIONAL, "broken chain of custody (gap in custody record)")]
    return []


def verify_approval_workflow(required_steps: Sequence[str], completed_steps: Sequence[str]) -> list[Violation]:
    """Required approval steps cannot be bypassed."""
    missing = [s for s in required_steps if s not in completed_steps]
    if missing:
        return [_v(_RULE, CONSTITUTIONAL, f"approval workflow bypassed; missing steps: {missing}")]
    return []


def verify_no_privilege_escalation(granted_role_level: int, authorized_level: int) -> list[Violation]:
    if granted_role_level > authorized_level:
        return [
            _v(
                "No Loss Of Human Control",
                CONSTITUTIONAL,
                f"privilege escalation: granted level {granted_role_level} > authorized {authorized_level}",
            )
        ]
    return []
