# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.constitution — the platform constitution, as pure predicates.

The constitution (No Unauthorized Trade, No Hidden Loss, No State Corruption,
No Loss of Human Control, No Silent Failure, …) is encoded here as small,
side-effect-free functions. Each returns ``list[Violation]`` — empty means the
invariant holds. Because they are pure they can be used **two ways**:

  * inline enforcement — call before/after a state change and refuse to proceed
    (or halt) when a constitutional invariant is violated;
  * external verification — feed live state from an endpoint/DB and assert in
    CI / ops dashboards.

Severity ladder (from the constitution doc):
  CONSTITUTIONAL — must never be violated; a violation means corruption/fraud.
  CRITICAL       — halt the affected activity until resolved.
  WARNING        — investigate; not immediately dangerous.

Nothing here mutates state or performs I/O; it is safe to import anywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

CONSTITUTIONAL = "CONSTITUTIONAL"
CRITICAL = "CRITICAL"
WARNING = "WARNING"

# Tolerance for float comparisons (quantities, balances).
_EPS = 1e-9


@dataclass(frozen=True)
class Violation:
    rule: str  # constitutional rule, e.g. "No Hidden Loss"
    severity: str  # CONSTITUTIONAL | CRITICAL | WARNING
    message: str
    context: dict[str, Any] | None = None


def _v(rule: str, sev: str, msg: str, **ctx: Any) -> Violation:
    return Violation(rule, sev, msg, ctx or None)


# ── helpers ────────────────────────────────────────────────────────────────────
def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ════════════════════════════════════════════════════════════════════════════════
# 8/9. No Data Corruption / No State Corruption — order state machine
# ════════════════════════════════════════════════════════════════════════════════
# Terminal states accept no further transitions; an order may hold exactly one
# terminal outcome. Mirrors execution/oms.py's transition table.
TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"PENDING_NEW", "NEW", "CANCELLED", "REJECTED"}),
    "PENDING_NEW": frozenset({"NEW", "REJECTED", "CANCELLED"}),
    "NEW": frozenset(
        {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "PENDING_CANCEL"}
    ),
    "ACKNOWLEDGED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCELLED", "EXPIRED", "PENDING_CANCEL"}),
    "PARTIALLY_FILLED": frozenset({"FILLED", "CANCELLED", "EXPIRED", "PENDING_CANCEL"}),
    "PENDING_CANCEL": frozenset({"CANCELLED", "FILLED"}),
    "FILLED": frozenset(),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset(),
}


def verify_order_state_transition(from_status: str, to_status: str) -> list[Violation]:
    """An order must follow the lifecycle; a terminal order can never move again."""
    f, t = str(from_status).upper(), str(to_status).upper()
    out: list[Violation] = []
    if f in TERMINAL_STATES and f != t:
        out.append(
            _v("No State Corruption", CONSTITUTIONAL, f"order left terminal state {f}→{t}", from_status=f, to_status=t)
        )
    elif f in VALID_TRANSITIONS and t not in VALID_TRANSITIONS[f] and f != t:
        out.append(_v("No State Corruption", CRITICAL, f"illegal order transition {f}→{t}", from_status=f, to_status=t))
    return out


def verify_order_not_contradictory(order: dict[str, Any]) -> list[Violation]:
    """An order cannot simultaneously be filled and cancelled/rejected, and its
    filled quantity can never exceed the ordered quantity (no phantom fills)."""
    out: list[Violation] = []
    status = str(order.get("status", "")).upper()
    filled = order.get("filled_quantity", order.get("filled_qty"))
    qty = order.get("quantity", order.get("qty"))
    if status == "FILLED" and order.get("cancelled"):
        out.append(_v("No State Corruption", CONSTITUTIONAL, "order is FILLED and cancelled", order_id=order.get("id")))
    if _is_finite_number(filled) and _is_finite_number(qty) and filled > qty + _EPS:
        out.append(
            _v(
                "No State Corruption",
                CONSTITUTIONAL,
                f"filled {filled} exceeds ordered {qty} (phantom fill)",
                order_id=order.get("id"),
            )
        )
    if _is_finite_number(filled) and filled < -_EPS:
        out.append(_v("No State Corruption", CRITICAL, f"negative filled quantity {filled}", order_id=order.get("id")))
    return out


def verify_no_duplicate_ids(
    items: Iterable[dict[str, Any]], id_field: str = "id", rule: str = "No Data Corruption"
) -> list[Violation]:
    """No two records (orders, fills, transactions) may share an id — the
    duplicate-processing / double-fill guard."""
    seen: set[Any] = set()
    dups: set[Any] = set()
    for it in items:
        i = it.get(id_field)
        if i is None:
            continue
        if i in seen:
            dups.add(i)
        seen.add(i)
    if dups:
        return [
            _v(
                rule,
                CONSTITUTIONAL,
                f"{len(dups)} duplicate {id_field}(s): {sorted(dups)[:5]}",
                field=id_field,
                count=len(dups),
            )
        ]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# 3/4/5. No Hidden Loss / Exposure / Risk — capital & PnL conservation
# ════════════════════════════════════════════════════════════════════════════════
def verify_pnl_reconciliation(realized: float, unrealized: float, total: float, tol: float = 0.01) -> list[Violation]:
    """realized + unrealized must equal total PnL (no hidden/unaccounted PnL)."""
    for name, val in (("realized", realized), ("unrealized", unrealized), ("total", total)):
        if not _is_finite_number(val):
            return [_v("No Hidden Loss", CONSTITUTIONAL, f"PnL component '{name}' is non-finite ({val!r})")]
    if abs((realized + unrealized) - total) > tol:
        return [
            _v(
                "No Hidden Loss",
                CONSTITUTIONAL,
                f"PnL mismatch: realized({realized}) + unrealized({unrealized}) != total({total})",
                diff=round((realized + unrealized) - total, 6),
            )
        ]
    return []


def verify_capital_conservation(
    allocated: float, available: float, reserved: float, total: float, tol: float = 0.01
) -> list[Violation]:
    """allocated + available + reserved must equal total capital (no money
    created or destroyed)."""
    parts = {"allocated": allocated, "available": available, "reserved": reserved, "total": total}
    for name, val in parts.items():
        if not _is_finite_number(val):
            return [_v("No Hidden Capital", CONSTITUTIONAL, f"capital component '{name}' is non-finite ({val!r})")]
    if abs((allocated + available + reserved) - total) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                "capital does not reconcile: allocated+available+reserved != total",
                diff=round((allocated + available + reserved) - total, 6),
                **parts,
            )
        ]
    return []


def verify_capital_equation(
    opening: float, deposits: float, realized: float, withdrawals: float, fees: float, closing: float, tol: float = 0.01
) -> list[Violation]:
    """opening + deposits + realized − withdrawals − fees == closing.
    A violation means an accounting bug, reconciliation bug, or fraud."""
    vals = [opening, deposits, realized, withdrawals, fees, closing]
    if not all(_is_finite_number(x) for x in vals):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "capital-equation component is non-finite")]
    expected = opening + deposits + realized - withdrawals - fees
    if abs(expected - closing) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                f"capital equation broken: expected closing {round(expected, 4)} != {closing}",
                diff=round(expected - closing, 6),
            )
        ]
    return []


def verify_no_negative_balance(balance: float, name: str = "balance") -> list[Violation]:
    """Cash/account balance must never go negative (unless explicitly a margin
    account — caller decides)."""
    if not _is_finite_number(balance):
        return [_v("No Data Corruption", CONSTITUTIONAL, f"{name} is non-finite ({balance!r})")]
    if balance < -_EPS:
        return [_v("No Hidden Loss", CRITICAL, f"{name} is negative ({balance})", value=balance)]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# 5. No Hidden Risk — hard limit bounds
# ════════════════════════════════════════════════════════════════════════════════
def verify_within_limit(
    value: float, limit: float, name: str, rule: str = "No Hidden Risk", severity: str = CRITICAL
) -> list[Violation]:
    """A risk/exposure metric must stay within its approved hard limit."""
    if not _is_finite_number(value):
        return [_v(rule, CONSTITUTIONAL, f"{name} is non-finite ({value!r})")]
    if _is_finite_number(limit) and value > limit:
        return [_v(rule, severity, f"{name} {value} exceeds limit {limit}", value=value, limit=limit)]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# 8. No Data Corruption — market data integrity
# ════════════════════════════════════════════════════════════════════════════════
def verify_tick(price: float, volume: float, ts: float | None = None, now: float | None = None) -> list[Violation]:
    """A market tick must have price>0, volume>=0, and a non-future timestamp."""
    out: list[Violation] = []
    if not _is_finite_number(price) or price <= 0:
        out.append(_v("No Data Corruption", CRITICAL, f"invalid tick price {price!r}"))
    if not _is_finite_number(volume) or volume < 0:
        out.append(_v("No Data Corruption", CRITICAL, f"invalid tick volume {volume!r}"))
    if ts is not None and now is not None and _is_finite_number(ts) and ts > now + 1.0:
        out.append(_v("No Data Corruption", CRITICAL, f"future-dated tick ts={ts} > now={now}"))
    return out


def verify_spread(bid: float, ask: float) -> list[Violation]:
    """Best bid must not exceed best ask (crossed/corrupted book)."""
    if not (_is_finite_number(bid) and _is_finite_number(ask)):
        return [_v("No Data Corruption", CRITICAL, f"non-finite quote bid={bid!r} ask={ask!r}")]
    if bid > ask + _EPS:
        return [_v("No Data Corruption", CRITICAL, f"crossed book: bid {bid} > ask {ask}")]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# 17/20. No Unexplained Behavior / No Silent Failure — numeric integrity
# ════════════════════════════════════════════════════════════════════════════════
def verify_finite(value: Any, name: str) -> list[Violation]:
    """A numeric output must be finite — NaN/Infinity is silent corruption."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
        return [_v("No Silent Failure", CRITICAL, f"{name} is non-finite ({value!r})")]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# 14. No Loss Of Human Control — kill switch must be present & operable
# ════════════════════════════════════════════════════════════════════════════════
def verify_human_control(kill_switch: Any) -> list[Violation]:
    """The kill switch object must exist and expose an operable engage/disengage
    surface — humans must always be able to halt the system."""
    if kill_switch is None:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, "kill switch is not wired (None)")]
    engage = any(hasattr(kill_switch, m) for m in ("trigger", "engage", "activate", "trip"))
    query = any(hasattr(kill_switch, m) for m in ("is_active", "active", "is_triggered", "status"))
    if not engage:
        return [
            _v(
                "No Loss Of Human Control",
                CONSTITUTIONAL,
                "kill switch exposes no engage method (trigger/engage/activate)",
            )
        ]
    if not query:
        return [_v("No Loss Of Human Control", CRITICAL, "kill switch exposes no state query method")]
    return []


# ── aggregate ──────────────────────────────────────────────────────────────────
def summarize(violations: list[Violation]) -> dict[str, Any]:
    """Bucket violations by severity for reporting / gating."""
    by = {CONSTITUTIONAL: 0, CRITICAL: 0, WARNING: 0}
    for v in violations:
        by[v.severity] = by.get(v.severity, 0) + 1
    return {
        "ok": by[CONSTITUTIONAL] == 0 and by[CRITICAL] == 0,
        "counts": by,
        "violations": [{"rule": v.rule, "severity": v.severity, "message": v.message} for v in violations],
    }
