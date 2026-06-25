# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.economic — platform economics, reporting & investor protection.

Pure predicates from the framework's economic/organizational/investor sections:
economic equilibrium (flows balance), no false/misleading reporting, client
fund segregation, redemption/withdrawal fairness, and legal/contract limits.
Each returns list[Violation].
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_economic_equilibrium(inflows: float, outflows: float, profit: float, fees: float,
                                delta_capital: float, tol: float = 0.01) -> list[Violation]:
    """inflows − outflows + profit − fees must equal the change in capital."""
    vals = [inflows, outflows, profit, fees, delta_capital]
    if not all(_is_finite_number(x) for x in vals):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "economic-equilibrium component non-finite")]
    expected = inflows - outflows + profit - fees
    if abs(expected - delta_capital) > tol:
        return [_v("No Hidden Capital", CONSTITUTIONAL,
                   f"economic disequilibrium: expected Δcapital {round(expected, 4)} != {delta_capital}")]
    return []


def verify_report_accurate(reported: float, actual: float, tol: float = 0.01) -> list[Violation]:
    """Investor/risk/performance reports must match source-of-truth (no false reporting)."""
    if not (_is_finite_number(reported) and _is_finite_number(actual)):
        return [_v("No Compliance Breach", CRITICAL, "report values non-finite")]
    if abs(reported - actual) > tol:
        return [_v("No Compliance Breach", CONSTITUTIONAL,
                   f"misleading report: reported {reported} != actual {actual}")]
    return []


def verify_fund_segregation(client_funds: Mapping[Any, float], commingled: bool) -> list[Violation]:
    """Client funds must be segregated, never commingled with house/other clients."""
    if commingled:
        return [_v("No Cross-Tenant Leakage", CONSTITUTIONAL, "client funds are commingled (segregation breach)")]
    bad = [c for c, v in client_funds.items() if _is_finite_number(v) and v < 0]
    if bad:
        return [_v("No Hidden Loss", CONSTITUTIONAL, f"negative segregated balance for client(s): {bad[:5]}")]
    return []


def verify_redemption_fairness(requested: float, honored: float, available: float) -> list[Violation]:
    """A redemption that could be honored from available funds must not be denied/short-paid."""
    if not all(_is_finite_number(x) for x in (requested, honored, available)):
        return [_v("No Compliance Breach", CRITICAL, "redemption values non-finite")]
    if honored < requested and available >= requested:
        return [_v("No Compliance Breach", CRITICAL,
                   f"unfair redemption: honored {honored} < requested {requested} despite {available} available")]
    return []


def verify_within_contract_limits(value: float, contract_limit: float, name: str) -> list[Violation]:
    """A client/strategy cannot exceed its contractual/legal limit."""
    if _is_finite_number(value) and _is_finite_number(contract_limit) and value > contract_limit:
        return [_v("No Compliance Breach", CONSTITUTIONAL, f"{name} {value} exceeds contract limit {contract_limit}")]
    return []


def verify_cost_growth(growth_pct: float, limit_pct: float) -> list[Violation]:
    """Operational cost growth must stay bounded (cost-drift detection)."""
    if _is_finite_number(growth_pct) and growth_pct > limit_pct:
        return [_v("No Hidden Loss", WARNING, f"operational cost growth {growth_pct}% > {limit_pct}%")]
    return []
