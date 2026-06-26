# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk.risk_appetite — the Risk Appetite Framework as governance-approved policy-as-code.

A clearly-defined risk appetite is an institutional requirement: what losses are
acceptable, what trades are off-limits, which jurisdictions are allowed. This
module makes that policy a *versioned, signed, reviewable artifact* (governance
process) that the platform also *enforces* (technical control) — closing the gap
between "we have a policy document" and "the system actually obeys it".

The policy is a plain JSON file (``config/risk_appetite.json``; template in
``config/risk_appetite.example.json``). It carries governance metadata —
``version``, ``approved_by``, ``effective_date``, ``review_due`` — alongside the
hard limits and prohibitions. ``validate_policy()`` flags governance hygiene
problems (unsigned, past review date, placeholder approver); the enforcement
facade (``invariants.enforcement.enforce_risk_appetite``) checks live state
against the limits.

Stdlib only; safe to import anywhere (no I/O at import time).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _REPO_ROOT / "config" / "risk_appetite.json"
_EXAMPLE_PATH = _REPO_ROOT / "config" / "risk_appetite.example.json"

# Safe fallback policy — conservative limits, clearly marked unapproved so the
# governance validator flags it until a real signed policy is provided.
_DEFAULT_POLICY: dict[str, Any] = {
    "version": "0.0.0-default",
    "approved_by": "",
    "effective_date": "",
    "review_due": "",
    "limits": {
        "max_daily_loss_pct": 0.05,
        "max_drawdown_pct": 0.10,
        "max_position_pct": 0.05,
        "max_symbol_exposure_usd": 1_000_000,
        "max_leverage": 10,
        "approved_var_usd": 0,
    },
    "prohibited": {"symbols": [], "jurisdictions_blocked": []},
    "allowed_jurisdictions": [],
}


def load_risk_appetite(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load the risk-appetite policy. Falls back to the example template, then to
    a conservative built-in default — never raises, so a missing file degrades
    safely (the governance validator will flag the default as unapproved)."""
    candidates = [Path(path)] if path else [_DEFAULT_PATH, _EXAMPLE_PATH]
    for p in candidates:
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                data.pop("_comment", None)
                return data
        except Exception as exc:
            logger.warning("risk_appetite: could not load %s: %s", p, exc)
    return dict(_DEFAULT_POLICY)


def get_limits(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the hard-limit block, merged over defaults."""
    pol = policy if policy is not None else load_risk_appetite()
    merged = dict(_DEFAULT_POLICY["limits"])
    merged.update(pol.get("limits", {}) or {})
    return merged


def validate_policy(policy: dict[str, Any], today: str | None = None) -> list[str]:
    """Governance-hygiene check on the policy itself. Returns a list of issues
    (empty == healthy). ``today`` is an ISO date string (YYYY-MM-DD) used to
    detect a past-due review; pass it in so this stays pure/testable.

    This is the *governance process* surfaced as code: a risk policy that is
    unsigned, placeholder, or overdue for review must not silently govern capital.
    """
    issues: list[str] = []
    approver = str(policy.get("approved_by", "")).strip()
    if not approver:
        issues.append("risk-appetite policy is UNSIGNED (approved_by empty)")
    elif approver.upper().startswith("CHANGE_ME") or "placeholder" in approver.lower():
        issues.append(f"risk-appetite policy approver is a placeholder ({approver!r})")

    if not str(policy.get("version", "")).strip() or str(policy.get("version")).endswith("-default"):
        issues.append("risk-appetite policy has no real version (still the built-in default?)")

    review_due = str(policy.get("review_due", "")).strip()
    if not review_due:
        issues.append("risk-appetite policy has no review_due date")
    elif today and review_due < today:
        issues.append(f"risk-appetite policy review is OVERDUE (due {review_due}, today {today})")

    limits = policy.get("limits") or {}
    for key in ("max_daily_loss_pct", "max_drawdown_pct", "max_position_pct"):
        val = limits.get(key)
        if not isinstance(val, (int, float)) or not (0 < float(val) <= 1):
            issues.append(f"risk-appetite limit {key} is missing or out of range (0,1]: {val!r}")
    return issues
