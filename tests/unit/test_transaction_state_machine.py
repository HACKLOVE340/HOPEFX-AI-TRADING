"""F222 (TODO item 5) — `payments/transaction_manager.py` had no state machine.

427 lines, named by no test file, and it is the ledger of every deposit,
withdrawal, payment, commission, transfer and refund.

`update_transaction_status` assigned any status over any status. `cancel` and
`reverse` each guarded their own entry condition, but `complete` and `fail` did
not — so a REVERSED transaction could be completed again, and then reversed
again. Measured before the fix:

    deposit 100.00 → complete → reverse → complete → reverse
    = 200.00 of reversals from one 100.00 deposit, across 3 transactions

That is a double refund reachable through the module's own public API, with no
tampering and no race. The fix is a transition table, the same shape as
`core/ai_contracts.py::_ALLOWED_TRANSITIONS` — which this audit already
identified as the right pattern for exactly this problem.
"""

from __future__ import annotations

import sys
from decimal import Decimal

import pytest


def _module():
    """The module object, not a re-exported singleton."""
    import payments.transaction_manager  # noqa: F401

    return sys.modules["payments.transaction_manager"]


_MOD = _module()
TransactionManager = _MOD.TransactionManager
TransactionStatus = _MOD.TransactionStatus
TransactionType = _MOD.TransactionType


@pytest.fixture
def manager():
    return TransactionManager()


def _deposit(manager, amount: str = "100.00"):
    return manager.record_transaction(
        user_id="u-1",
        wallet_id="w-1",
        transaction_type=TransactionType.DEPOSIT,
        amount=Decimal(amount),
        currency="USD",
        method="stripe",
        wallet_type="subscription",
    )


# ── the double refund ─────────────────────────────────────────────────────────


def test_a_reversed_transaction_cannot_be_completed_again(manager) -> None:
    """The step that made the double refund possible."""
    txn = _deposit(manager)
    manager.complete_transaction(txn.transaction_id)
    manager.reverse_transaction(txn.transaction_id, "customer dispute")

    assert txn.status is TransactionStatus.REVERSED
    assert manager.complete_transaction(txn.transaction_id) is False
    assert txn.status is TransactionStatus.REVERSED


def test_one_deposit_cannot_produce_two_reversals(manager) -> None:
    """The whole chain, end to end — this is the money at stake."""
    txn = _deposit(manager, "100.00")
    manager.complete_transaction(txn.transaction_id)

    first = manager.reverse_transaction(txn.transaction_id, "customer dispute")
    assert first is not None

    manager.complete_transaction(txn.transaction_id)  # refused now
    second = manager.reverse_transaction(txn.transaction_id, "again")

    assert second is None, "a single deposit was reversed twice"

    reversals = [record for record in manager.transactions.values() if record.type is TransactionType.WITHDRAWAL]
    assert len(reversals) == 1
    assert sum(record.amount for record in reversals) == Decimal("100.00")


# ── the transition table ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("terminal", "attempted"),
    [
        (TransactionStatus.REVERSED, TransactionStatus.COMPLETED),
        (TransactionStatus.REVERSED, TransactionStatus.PENDING),
        (TransactionStatus.CANCELLED, TransactionStatus.COMPLETED),
        (TransactionStatus.FAILED, TransactionStatus.COMPLETED),
        (TransactionStatus.COMPLETED, TransactionStatus.PENDING),
        (TransactionStatus.COMPLETED, TransactionStatus.CANCELLED),
    ],
    ids=lambda value: value.value,
)
def test_a_settled_transaction_does_not_go_backwards(manager, terminal, attempted) -> None:
    txn = _deposit(manager)
    txn.status = terminal

    assert manager.update_transaction_status(txn.transaction_id, attempted) is False
    assert txn.status is terminal


@pytest.mark.parametrize(
    ("start", "allowed"),
    [
        (TransactionStatus.PENDING, TransactionStatus.PROCESSING),
        (TransactionStatus.PENDING, TransactionStatus.COMPLETED),
        (TransactionStatus.PENDING, TransactionStatus.FAILED),
        (TransactionStatus.PENDING, TransactionStatus.CANCELLED),
        (TransactionStatus.PROCESSING, TransactionStatus.COMPLETED),
        (TransactionStatus.PROCESSING, TransactionStatus.FAILED),
        (TransactionStatus.COMPLETED, TransactionStatus.REVERSED),
    ],
    ids=lambda value: value.value,
)
def test_the_legitimate_transitions_still_work(manager, start, allowed) -> None:
    """A table that refuses everything is not a fix."""
    txn = _deposit(manager)
    txn.status = start

    assert manager.update_transaction_status(txn.transaction_id, allowed) is True
    assert txn.status is allowed


def test_a_status_can_be_reasserted(manager) -> None:
    """Idempotent retries must not be treated as an illegal transition."""
    txn = _deposit(manager)
    manager.complete_transaction(txn.transaction_id)

    assert manager.complete_transaction(txn.transaction_id) is True
    assert txn.status is TransactionStatus.COMPLETED


# ── the contracts nothing watched before ─────────────────────────────────────


def test_a_failure_records_its_reason(manager) -> None:
    txn = _deposit(manager)

    assert manager.fail_transaction(txn.transaction_id, "card declined") is True
    assert txn.status is TransactionStatus.FAILED
    assert txn.failed_reason == "card declined"


def test_only_a_pending_transaction_can_be_cancelled(manager) -> None:
    txn = _deposit(manager)
    manager.complete_transaction(txn.transaction_id)

    assert manager.cancel_transaction(txn.transaction_id) is False
    assert txn.status is TransactionStatus.COMPLETED


def test_only_a_completed_transaction_can_be_reversed(manager) -> None:
    txn = _deposit(manager)

    assert manager.reverse_transaction(txn.transaction_id, "too early") is None
    assert txn.status is TransactionStatus.PENDING


def test_a_reversal_points_back_at_what_it_reversed(manager) -> None:
    """An audit trail that cannot be followed in both directions is half a trail."""
    txn = _deposit(manager)
    manager.complete_transaction(txn.transaction_id)

    reversal = manager.reverse_transaction(txn.transaction_id, "customer dispute")

    assert reversal.metadata["original_transaction"] == txn.transaction_id
    assert txn.metadata["reversed_by"] == reversal.transaction_id
    assert reversal.amount == txn.amount
    assert reversal.type is TransactionType.WITHDRAWAL


@pytest.mark.parametrize("amount", ["0", "-1", "-0.01"])
def test_a_non_positive_amount_is_refused(manager, amount: str) -> None:
    with pytest.raises(ValueError, match="positive"):
        _deposit(manager, amount)


def test_an_unknown_transaction_is_refused(manager) -> None:
    assert manager.update_transaction_status("TXN-nope", TransactionStatus.COMPLETED) is False
    assert manager.reverse_transaction("TXN-nope", "reason") is None
    assert manager.cancel_transaction("TXN-nope") is False
