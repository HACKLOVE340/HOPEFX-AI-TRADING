# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.payments — money movement, billing & idempotency.

Pure predicates for the framework's payments/billing categories: a charge must
be authorized and idempotent (no double-charge on retry), refunds never exceed
the original, deposits/withdrawals balance the ledger, currency math is exact,
no negative or NaN amounts, and every external payment event reconciles with the
internal record. This is the most direct "no unauthorized capital movement"
surface. Each returns ``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _EPS,
    _is_finite_number,
    _v,
)

_RULE = "No Unauthorized Capital Movement"


def verify_charge_authorized(authorized: bool, amount: float) -> list[Violation]:
    """No charge may post without explicit authorization."""
    if not authorized:
        return [_v(_RULE, CONSTITUTIONAL, f"unauthorized charge of {amount}")]
    return []


def verify_idempotent_charge(idempotency_key: Any, processed_keys: Iterable[Any]) -> list[Violation]:
    """A retried charge with a seen idempotency key must not double-charge."""
    if idempotency_key in set(processed_keys):
        return [_v(_RULE, CONSTITUTIONAL, f"duplicate charge for idempotency key {idempotency_key!r} (double-charge)")]
    return []


def verify_amount_valid(amount: float, *, allow_zero: bool = False) -> list[Violation]:
    """A monetary amount must be finite and non-negative."""
    if not _is_finite_number(amount):
        return [_v("No Data Corruption", CRITICAL, f"payment amount non-finite: {amount!r}")]
    if amount < 0 or (not allow_zero and abs(amount) <= _EPS):
        return [_v(_RULE, CRITICAL, f"invalid payment amount {amount}")]
    return []


def verify_refund_within_original(refund: float, original: float) -> list[Violation]:
    """A refund must never exceed the original captured amount."""
    if not (_is_finite_number(refund) and _is_finite_number(original)):
        return [_v("No Data Corruption", CRITICAL, "refund/original non-finite")]
    if refund > original + _EPS:
        return [_v(_RULE, CONSTITUTIONAL, f"refund {refund} exceeds original {original}")]
    return []


def verify_total_refunds_within_original(refunds: Iterable[float], original: float) -> list[Violation]:
    """Cumulative refunds must not exceed the original charge."""
    vals = list(refunds)
    if not all(_is_finite_number(r) for r in vals) or not _is_finite_number(original):
        return [_v("No Data Corruption", CRITICAL, "refund/original non-finite")]
    total = sum(vals)
    if total > original + _EPS:
        return [_v(_RULE, CONSTITUTIONAL, f"cumulative refunds {total} exceed original {original}")]
    return []


def verify_ledger_balanced(debits: float, credits: float, tol: float = 0.01) -> list[Violation]:
    """Double-entry: debits must equal credits for a payment transaction."""
    if not (_is_finite_number(debits) and _is_finite_number(credits)):
        return [_v("No Data Corruption", CRITICAL, "ledger debit/credit non-finite")]
    if abs(debits - credits) > tol:
        return [_v(_RULE, CONSTITUTIONAL, f"ledger unbalanced: debits {debits} != credits {credits}")]
    return []


def verify_balance_after(before: float, delta: float, after: float, tol: float = 0.01) -> list[Violation]:
    """An account balance after a movement must equal before + delta exactly."""
    if not all(_is_finite_number(x) for x in (before, delta, after)):
        return [_v("No Data Corruption", CRITICAL, "balance components non-finite")]
    if abs((before + delta) - after) > tol:
        return [_v(_RULE, CONSTITUTIONAL, f"balance mismatch: {before}+{delta} != {after}")]
    return []


def verify_currency_consistent(amounts_currency: str, account_currency: str) -> list[Violation]:
    """A payment's currency must match the account it touches (no silent FX)."""
    if amounts_currency != account_currency:
        return [_v(_RULE, CRITICAL, f"currency mismatch: payment {amounts_currency} vs account {account_currency}")]
    return []


def verify_payment_reconciles(
    internal_amount: float, gateway_amount: float, tol: float = 0.01, ref: str = ""
) -> list[Violation]:
    """An external gateway/PSP event must reconcile with the internal record."""
    if not (_is_finite_number(internal_amount) and _is_finite_number(gateway_amount)):
        return [_v("No Data Corruption", CRITICAL, "payment reconciliation values non-finite")]
    if abs(internal_amount - gateway_amount) > tol:
        return [
            _v(_RULE, CONSTITUTIONAL, f"payment {ref} mismatch: internal {internal_amount} != gateway {gateway_amount}")
        ]
    return []


def verify_withdrawal_within_balance(amount: float, available: float) -> list[Violation]:
    """A withdrawal must not exceed available (no overdraft / negative balance)."""
    if not (_is_finite_number(amount) and _is_finite_number(available)):
        return [_v("No Data Corruption", CRITICAL, "withdrawal values non-finite")]
    if amount > available + _EPS:
        return [_v(_RULE, CONSTITUTIONAL, f"withdrawal {amount} exceeds available {available}")]
    return []
