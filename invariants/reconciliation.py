# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.reconciliation — capital, ledger, custody, treasury & economic recon.

Pure predicates from the framework's settlement/treasury/economic sections: the
reconciliation chain (exchange→broker→custodian→ledger→portfolio→risk all
agree), ledger immutability, custody reconciliation, treasury flow balance,
double-entry, alpha attribution completeness, fee/tax integrity, and
revenue-leakage detection.
"""

from __future__ import annotations

from collections.abc import Mapping

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _is_finite_number,
    _v,
)


def verify_reconciliation_chain(balances: Mapping[str, float], tol: float = 0.01) -> list[Violation]:
    """Every layer (exchange/broker/custodian/ledger/portfolio/risk) must report
    the same balance. Any divergence is corruption, fraud, or a recon bug."""
    vals = [v for v in balances.values() if _is_finite_number(v)]
    if len(vals) != len(balances):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "a reconciliation layer reported a non-finite balance")]
    if not vals:
        return []
    if max(vals) - min(vals) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                f"reconciliation chain disagrees: {dict(balances)}",
                spread=round(max(vals) - min(vals), 6),
            )
        ]
    return []


def verify_custody_reconciled(
    custodian_holdings: float, internal_holdings: float, tol: float = 0.01
) -> list[Violation]:
    if not (_is_finite_number(custodian_holdings) and _is_finite_number(internal_holdings)):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "custody holdings non-finite")]
    if abs(custodian_holdings - internal_holdings) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                f"custody mismatch: custodian {custodian_holdings} != internal {internal_holdings}",
            )
        ]
    return []


def verify_double_entry(total_debits: float, total_credits: float, tol: float = 0.01) -> list[Violation]:
    """Ledger must balance: debits == credits."""
    if not (_is_finite_number(total_debits) and _is_finite_number(total_credits)):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "ledger totals non-finite")]
    if abs(total_debits - total_credits) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                f"ledger unbalanced: debits {total_debits} != credits {total_credits}",
            )
        ]
    return []


def verify_ledger_immutable(entry_hash: str, stored_hash: str) -> list[Violation]:
    if entry_hash != stored_hash:
        return [_v("No Audit Gap", CONSTITUTIONAL, "ledger entry hash changed (immutability violated)")]
    return []


def verify_treasury_flow(
    opening: float, deposits: float, withdrawals: float, funding: float, closing: float, tol: float = 0.01
) -> list[Violation]:
    """opening + deposits − withdrawals + funding == closing (treasury balance)."""
    vals = [opening, deposits, withdrawals, funding, closing]
    if not all(_is_finite_number(x) for x in vals):
        return [_v("No Hidden Capital", CONSTITUTIONAL, "treasury flow component non-finite")]
    expected = opening + deposits - withdrawals + funding
    if abs(expected - closing) > tol:
        return [
            _v(
                "No Hidden Capital",
                CONSTITUTIONAL,
                f"treasury does not reconcile: expected {round(expected, 4)} != closing {closing}",
            )
        ]
    return []


def verify_alpha_attribution(total_pnl: float, attributed: Mapping[str, float], tol: float = 0.01) -> list[Violation]:
    """Every dollar of PnL must be attributable to a source (No Hidden Loss)."""
    vals = list(attributed.values())
    if not all(_is_finite_number(x) for x in [*vals, total_pnl]):
        return [_v("No Hidden Loss", CONSTITUTIONAL, "PnL attribution component non-finite")]
    if abs(sum(vals) - total_pnl) > tol:
        return [
            _v(
                "No Hidden Loss",
                CRITICAL,
                f"unattributed PnL: sum(sources) {round(sum(vals), 4)} != total {total_pnl}",
                unexplained=round(total_pnl - sum(vals), 6),
            )
        ]
    return []


def verify_fee_integrity(expected_fee: float, charged_fee: float, tol: float = 0.01) -> list[Violation]:
    if not (_is_finite_number(expected_fee) and _is_finite_number(charged_fee)):
        return [_v("No Hidden Loss", CRITICAL, "fee values non-finite")]
    if abs(expected_fee - charged_fee) > tol:
        return [_v("No Hidden Loss", CRITICAL, f"fee mismatch: expected {expected_fee} != charged {charged_fee}")]
    return []


def verify_revenue_leakage(expected_revenue: float, recognized_revenue: float, tol: float = 0.01) -> list[Violation]:
    """Recognised revenue must match expected — unexplained loss is leakage/fraud."""
    if not (_is_finite_number(expected_revenue) and _is_finite_number(recognized_revenue)):
        return [_v("No Hidden Loss", CRITICAL, "revenue values non-finite")]
    if expected_revenue - recognized_revenue > tol:
        return [
            _v(
                "No Hidden Loss",
                CRITICAL,
                f"revenue leakage: expected {expected_revenue} but recognized {recognized_revenue}",
                leak=round(expected_revenue - recognized_revenue, 6),
            )
        ]
    return []
