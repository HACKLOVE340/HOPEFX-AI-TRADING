# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants — the platform constitution as pure, testable predicates.

See ``invariants.constitution`` for the constitutional invariant functions and
the ``Violation`` model. These are enforced inline (refuse/halt on violation)
and verified externally (CI / ops via scripts/runtime_invariant_check.py).
"""

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    summarize,
    verify_capital_conservation,
    verify_capital_equation,
    verify_finite,
    verify_human_control,
    verify_no_duplicate_ids,
    verify_no_negative_balance,
    verify_order_not_contradictory,
    verify_order_state_transition,
    verify_pnl_reconciliation,
    verify_spread,
    verify_tick,
    verify_within_limit,
)

__all__ = [
    "CONSTITUTIONAL",
    "CRITICAL",
    "WARNING",
    "Violation",
    "summarize",
    "verify_capital_conservation",
    "verify_capital_equation",
    "verify_finite",
    "verify_human_control",
    "verify_no_duplicate_ids",
    "verify_no_negative_balance",
    "verify_order_not_contradictory",
    "verify_order_state_transition",
    "verify_pnl_reconciliation",
    "verify_spread",
    "verify_tick",
    "verify_within_limit",
]
