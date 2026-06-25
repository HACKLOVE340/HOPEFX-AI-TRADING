# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.execution — execution quality, latency, reconciliation & pre-trade.

Pure predicates from the framework's execution/broker/settlement sections:
slippage bounds, latency budget, local↔broker state reconciliation, the full
pre-trade gate, and settlement balance. Each returns list[Violation].
"""

from __future__ import annotations

from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _is_finite_number,
    _v,
)


def verify_slippage(expected_price: float, actual_price: float, max_slippage_pct: float) -> list[Violation]:
    """Realised slippage must stay within the allowed threshold."""
    if not (_is_finite_number(expected_price) and _is_finite_number(actual_price)) or expected_price <= 0:
        return [_v("No Hidden Loss", CRITICAL, f"invalid prices expected={expected_price} actual={actual_price}")]
    slip = abs(actual_price - expected_price) / expected_price * 100
    if slip > max_slippage_pct:
        return [_v("No Hidden Loss", CRITICAL, f"slippage {slip:.3f}% exceeds max {max_slippage_pct}%",
                   slippage_pct=round(slip, 4))]
    return []


def verify_latency_budget(latencies_ms: dict[str, float], budget_ms: float) -> list[Violation]:
    """Total decision latency (data+inference+risk+execution) must fit the budget."""
    vals = [v for v in latencies_ms.values() if _is_finite_number(v)]
    total = sum(vals)
    if total > budget_ms:
        return [_v("No Unbounded Failure", CRITICAL,
                   f"decision latency {total:.1f}ms exceeds budget {budget_ms}ms", stages=latencies_ms)]
    return []


def verify_broker_reconciliation(local_state: Any, broker_state: Any, name: str = "position") -> list[Violation]:
    """Local platform state must match the broker's (No Hidden Exposure)."""
    if local_state != broker_state:
        return [_v("No Hidden Exposure", CONSTITUTIONAL,
                   f"{name} mismatch: local={local_state!r} broker={broker_state!r}")]
    return []


def verify_reported_matches_actual(reported_fill: Any, exchange_fill: Any) -> list[Violation]:
    """What the system BELIEVES happened must equal what ACTUALLY happened — the
    reality-integrity invariant that sits above almost all others."""
    if reported_fill != exchange_fill:
        return [_v("No State Corruption", CONSTITUTIONAL,
                   f"reality mismatch: reported {reported_fill!r} != exchange {exchange_fill!r}")]
    return []


def verify_settlement_balanced(trades_value: float, clearing_value: float, tol: float = 0.01) -> list[Violation]:
    if not (_is_finite_number(trades_value) and _is_finite_number(clearing_value)):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "settlement values non-finite")]
    if abs(trades_value - clearing_value) > tol:
        return [_v("No Hidden Capital", CONSTITUTIONAL,
                   f"settlement unbalanced: trades {trades_value} != clearing {clearing_value}")]
    return []


def verify_pre_trade_gate(*, prediction_exists: bool, confidence_ok: bool, risk_approved: bool,
                          capital_available: bool, market_open: bool, broker_reachable: bool,
                          kill_switch_active: bool) -> list[Violation]:
    """Every autonomous trade must pass ALL pre-trade checks. A single failure
    (or an active kill switch) blocks the trade — No Unauthorized Trade."""
    out: list[Violation] = []
    checks = {
        "prediction_exists": prediction_exists,
        "confidence_ok": confidence_ok,
        "risk_approved": risk_approved,
        "capital_available": capital_available,
        "market_open": market_open,
        "broker_reachable": broker_reachable,
    }
    if kill_switch_active:
        out.append(_v("No Unauthorized Trade", CONSTITUTIONAL, "kill switch ACTIVE — trade must be blocked"))
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        sev = CONSTITUTIONAL if ("risk_approved" in failed or "prediction_exists" in failed) else CRITICAL
        out.append(_v("No Unauthorized Trade", sev, f"pre-trade checks failed: {failed}"))
    return out
