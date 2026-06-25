# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.portfolio — portfolio state, construction & exposure invariants.

Pure predicates from the framework's portfolio sections: portfolio state machine,
portfolio-value reconciliation, construction budgets (diversification / risk /
position-sizing / correlation / liquidity), hedging integrity, currency-exposure
reconciliation, synthetic exposure tracking, and capital efficiency.
"""

from __future__ import annotations

from collections.abc import Mapping

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

# Portfolio lifecycle: must go through LIQUIDATING before CLOSED, etc.
_PORTFOLIO_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"FUNDED", "CLOSED"}),
    "FUNDED": frozenset({"ACTIVE", "CLOSED"}),
    "ACTIVE": frozenset({"RESTRICTED", "LIQUIDATING"}),
    "RESTRICTED": frozenset({"ACTIVE", "LIQUIDATING"}),
    "LIQUIDATING": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}


def verify_portfolio_state_transition(from_state: str, to_state: str) -> list[Violation]:
    """Portfolio may never jump ACTIVE→CLOSED without LIQUIDATING."""
    f, t = str(from_state).upper(), str(to_state).upper()
    if f == t:
        return []
    allowed = _PORTFOLIO_TRANSITIONS.get(f)
    if allowed is not None and t not in allowed:
        sev = CONSTITUTIONAL if (f == "ACTIVE" and t == "CLOSED") else CRITICAL
        return [_v("No State Corruption", sev, f"illegal portfolio transition {f}→{t}")]
    return []


def verify_portfolio_value(positions_value: float, cash_balance: float, realized_pnl: float,
                           unrealized_pnl: float, portfolio_value: float, tol: float = 0.01) -> list[Violation]:
    """positions + cash + realized + unrealized must equal portfolio value."""
    vals = [positions_value, cash_balance, realized_pnl, unrealized_pnl, portfolio_value]
    if not all(_is_finite_number(x) for x in vals):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "portfolio-value component is non-finite")]
    lhs = positions_value + cash_balance + realized_pnl + unrealized_pnl
    if abs(lhs - portfolio_value) > tol:
        return [_v("No Hidden Capital", CONSTITUTIONAL,
                   f"portfolio value mismatch: parts {round(lhs, 4)} != {portfolio_value}",
                   diff=round(lhs - portfolio_value, 6))]
    return []


def verify_position_sizing(position_value: float, portfolio_value: float, max_pct: float) -> list[Violation]:
    """No single position may exceed its sizing limit as a share of the book."""
    if not (_is_finite_number(position_value) and _is_finite_number(portfolio_value)) or portfolio_value <= 0:
        return [_v("No Hidden Exposure", CONSTITUTIONAL, "position/portfolio value invalid")]
    pct = position_value / portfolio_value * 100
    if pct > max_pct:
        return [_v("No Hidden Exposure", CRITICAL, f"position {pct:.1f}% exceeds sizing limit {max_pct}%")]
    return []


def verify_diversification(num_positions: int, minimum: int) -> list[Violation]:
    if num_positions < minimum:
        return [_v("No Hidden Risk", WARNING, f"only {num_positions} positions (< min {minimum}) — under-diversified")]
    return []


def verify_correlation_budget(max_pairwise_corr: float, limit: float) -> list[Violation]:
    """A 'diversified' book whose holdings are highly correlated is concentrated."""
    if _is_finite_number(max_pairwise_corr) and max_pairwise_corr > limit:
        return [_v("No Hidden Exposure", WARNING,
                   f"max pairwise correlation {max_pairwise_corr} exceeds budget {limit} (hidden concentration)")]
    return []


def verify_hedging(hedge_coverage: float, required_coverage: float) -> list[Violation]:
    """A position requiring a hedge must be sufficiently covered."""
    if not _is_finite_number(hedge_coverage):
        return [_v("No Hidden Risk", CONSTITUTIONAL, "hedge coverage is non-finite")]
    if hedge_coverage < required_coverage:
        return [_v("No Hidden Risk", CRITICAL, f"hedge coverage {hedge_coverage} below required {required_coverage}")]
    return []


def verify_currency_reconciled(exposure_by_ccy: Mapping[str, float], net_total: float,
                               tol: float = 0.01) -> list[Violation]:
    """Per-currency exposure must sum to the reported net (no hidden FX exposure)."""
    vals = list(exposure_by_ccy.values())
    if not all(_is_finite_number(x) for x in [*vals, net_total]):
        return [_v("No Hidden Exposure", CONSTITUTIONAL, "currency exposure component non-finite")]
    if abs(sum(vals) - net_total) > tol:
        return [_v("No Hidden Exposure", CRITICAL, "currency exposure does not reconcile to net total")]
    return []


def verify_synthetic_exposure_tracked(notional_synthetic: float, tracked_synthetic: float,
                                      tol: float = 0.01) -> list[Violation]:
    """Synthetic/derivative notional exposure must be tracked, not hidden."""
    if not (_is_finite_number(notional_synthetic) and _is_finite_number(tracked_synthetic)):
        return [_v("No Hidden Exposure", CONSTITUTIONAL, "synthetic exposure non-finite")]
    if abs(notional_synthetic - tracked_synthetic) > tol:
        return [_v("No Hidden Exposure", CRITICAL,
                   f"untracked synthetic exposure: notional {notional_synthetic} != tracked {tracked_synthetic}")]
    return []


def verify_capital_efficiency(utilization: float, minimum: float = 0.0, maximum: float = 1.0) -> list[Violation]:
    """Capital utilization should be within a sane band (idle capital / over-deployment)."""
    if not _is_finite_number(utilization):
        return [_v("No Hidden Capital", WARNING, "capital utilization non-finite")]
    if utilization > maximum:
        return [_v("No Hidden Risk", CRITICAL, f"capital over-deployed: utilization {utilization} > {maximum}")]
    if utilization < minimum:
        return [_v("No Hidden Capital", WARNING, f"capital under-utilized: {utilization} < {minimum}")]
    return []
