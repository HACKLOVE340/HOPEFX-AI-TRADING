# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.registry — the single source of truth for every invariant predicate.

At platform scale the danger is not a missing check; it is *not knowing what is
checked*. This module auto-discovers every ``verify_*`` / ``catastrophic_*``
predicate across the ``invariants`` package by introspection, so there is one
authoritative, always-current inventory — no hand-maintained list to drift.

It also maps the platform's declared **critical components** to their protection
(invariants / monitoring / alerts / recovery) so coverage gaps are explicit. The
manifest below is the one place to declare "this component is critical"; the
coverage report (scripts/invariant_coverage.py) and the meta-invariants
(invariants.meta.verify_*_coverage) consume it.

Pure introspection; no side effects at import.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

# Modules that are infrastructure, not predicate libraries — excluded from the
# predicate inventory so the count reflects real checks.
_NON_PREDICATE_MODULES = {"registry", "enforcement"}
_PREDICATE_PREFIXES = ("verify_", "catastrophic_")


def discover_predicates() -> dict[str, list[str]]:
    """Return {module_name: [predicate_function_names]} for every invariants
    submodule, discovered by introspection (always current)."""
    import invariants

    out: dict[str, list[str]] = {}
    for mod_info in pkgutil.iter_modules(invariants.__path__):
        name = mod_info.name
        if name in _NON_PREDICATE_MODULES or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"invariants.{name}")
        except Exception:  # noqa: S112 - a module that won't import simply isn't inventoried
            continue
        preds = sorted(
            fn_name
            for fn_name, fn in inspect.getmembers(mod, inspect.isfunction)
            # Only functions DEFINED in this module (not imported helpers)
            if fn.__module__ == mod.__name__ and fn_name.startswith(_PREDICATE_PREFIXES)
        )
        if preds:
            out[name] = preds
    return out


def predicate_count() -> int:
    """Total number of invariant predicates across the package."""
    return sum(len(v) for v in discover_predicates().values())


def registry_summary() -> dict[str, Any]:
    """A compact, serializable summary of the whole invariant inventory."""
    by_module = discover_predicates()
    return {
        "modules": len(by_module),
        "predicates": sum(len(v) for v in by_module.values()),
        "by_module": {m: len(p) for m, p in sorted(by_module.items())},
    }


# ── Critical-component manifest (the one place to declare criticality) ────────────
# protected/monitored/alerted/recoverable are booleans the coverage report checks.
# Keep this honest: a component marked critical without protection is a real gap.
CRITICAL_COMPONENTS: dict[str, dict[str, bool]] = {
    "order_execution":   {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "risk_engine":       {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "reconciliation":    {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "kill_switch":       {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "market_data_feed":  {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "ml_inference":      {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "audit_log":         {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "database":          {"protected": True, "monitored": True, "alerted": True, "recoverable": False},
    "redis_cache":       {"protected": True, "monitored": True, "alerted": True, "recoverable": False},
    "broker_connection": {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "ledger_treasury":   {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
    "ai_agents":         {"protected": True, "monitored": True, "alerted": True, "recoverable": True},
}


def coverage_counts() -> dict[str, tuple[int, int]]:
    """For each protection dimension return (covered, total) across critical
    components — feeds the meta.verify_*_coverage invariants."""
    total = len(CRITICAL_COMPONENTS)
    dims = ("protected", "monitored", "alerted", "recoverable")
    return {dim: (sum(1 for c in CRITICAL_COMPONENTS.values() if c.get(dim)), total) for dim in dims}
