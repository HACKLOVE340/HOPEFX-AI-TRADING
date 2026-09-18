# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Wallet ledger integrity — the write path that moves user money.

These tests pin three defects found by the code-reading audit (F135, F136,
F138). None of them can fire today because nothing calls ``credit_wallet`` or
``debit_wallet`` yet: ``/payments/deposit`` is documented as not persisting and
``init_wallet`` only constructs the manager. They fire the moment that route is
wired, which is exactly why they are pinned now — the cost of a wrong balance is
not recoverable by a later patch.

  F135  ``TXN-%Y%m%d%H%M%S`` collides at second granularity against a UNIQUE
        column. The row is rejected, the exception is swallowed, and the caller
        is told the credit succeeded while the ledger has no record of it.
  F136  The balance is an unlocked read-modify-write, so concurrent credits
        lose updates.
  F138  ``invariants.payments.verify_balance_after`` is the check that catches
        both, and no production code path calls it.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from payments.wallet import WalletManager, WalletStatus, WalletType

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# F135 — ledger row identity
# --------------------------------------------------------------------------


def test_transaction_ids_are_unique_within_the_same_second():
    """
    ``transaction_id`` is a UNIQUE column (database/models.py WalletTransaction).
    A second-granularity timestamp is not an identity: two deposits inside one
    second produce the same id, the second INSERT is rejected, and the money is
    unaccounted for.
    """
    wm = WalletManager()
    wm.create_wallet("u1")

    ids = set()
    for _ in range(50):
        ok, _msg, txn = wm.credit_wallet("u1", Decimal("1.00"))
        assert ok
        ids.add(txn["transaction_id"])

    assert len(ids) == 50, "transaction ids collided within a single second"


def test_ledger_write_failure_is_not_reported_as_success():
    """
    A credit that could not be written to the ledger has not happened. Reporting
    success leaves the caller's balance moved in memory and absent from the
    durable record — the divergence a reconciliation can never close.
    """

    class ExplodingSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add(self, _row):
            raise RuntimeError("unique constraint violated")

        def commit(self):  # pragma: no cover - never reached
            raise AssertionError("commit should not be reached")

    wm = WalletManager(session_factory=ExplodingSession)
    wm.create_wallet("u1")

    ok, msg, txn = wm.credit_wallet("u1", Decimal("25.00"))

    assert ok is False, "credit reported success although no ledger row was written"
    assert txn is None
    assert "ledger" in msg.lower()
    # And the in-memory balance must not have moved either.
    assert wm.get_wallet("u1").subscription_balance == Decimal("0.00")


def test_debit_rolls_back_when_the_ledger_write_fails():
    """The same honesty rule in the other direction: a failed write must not
    leave the user's money debited."""

    class ExplodingSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add(self, _row):
            raise RuntimeError("disk full")

        def commit(self):  # pragma: no cover
            raise AssertionError("commit should not be reached")

    wm = WalletManager()
    wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("100.00"))
    wm.set_session_factory(ExplodingSession)

    ok, _msg, _txn = wm.debit_wallet("u1", Decimal("40.00"), transaction_type="fee")

    assert ok is False
    assert wm.get_wallet("u1").subscription_balance == Decimal("100.00")


def test_no_session_factory_is_still_a_success():
    """In-memory mode (tests, paper trading) has no ledger to write to. That is
    not a failure — only a configured backend that rejects the write is."""
    wm = WalletManager()
    wm.create_wallet("u1")
    ok, _msg, txn = wm.credit_wallet("u1", Decimal("10.00"))
    assert ok is True
    assert txn is not None


# --------------------------------------------------------------------------
# F136 — concurrent balance updates
# --------------------------------------------------------------------------


class SlowAdd(Decimal):
    """
    A Decimal that takes measurable time to be added to another.

    Under CPython the GIL makes the read-modify-write window on
    ``balance += amount`` narrow enough that a plain thread race passes on the
    broken code — which would make these tests worthless as guards. Widening the
    window with a real yield inside the arithmetic makes the interleaving
    deterministic, so the test fails on the unlocked implementation and passes
    only because the lock closes it.
    """

    def __radd__(self, other):
        time.sleep(0.002)
        return Decimal(other) + Decimal(self)


class SlowCompare(Decimal):
    """Same idea for the sufficient-balance check: both threads read the same
    balance, stall inside the comparison, and then both subtract."""

    def __gt__(self, other):  # evaluated for ``balance < amount``
        time.sleep(0.002)
        return Decimal(self) > Decimal(other)

    def __rsub__(self, other):
        return Decimal(other) - Decimal(self)


def test_concurrent_credits_do_not_lose_updates():
    """
    ``wallet.subscription_balance += amount`` is a read-modify-write. Two threads
    that read the same balance both write their own total and one deposit
    vanishes. Money is not allowed to vanish.
    """
    wm = WalletManager()
    wm.create_wallet("u1")

    workers = 8
    per_worker = 4
    start = threading.Barrier(workers)

    def deposit():
        start.wait()
        for _ in range(per_worker):
            wm.credit_wallet("u1", SlowAdd("1.00"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda _: deposit(), range(workers)))

    expected = Decimal(workers * per_worker)
    assert wm.get_wallet("u1").subscription_balance == expected


def test_concurrent_debits_cannot_overdraw():
    """
    The sufficient-balance check and the subtraction are separate statements.
    Under concurrency both threads can pass the check on the same balance and
    the account goes negative — an overdraft the platform funds.
    """
    wm = WalletManager()
    wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("100.00"))

    workers = 16
    start = threading.Barrier(workers)
    granted = []
    lock = threading.Lock()

    def withdraw():
        start.wait()
        ok, _msg, _txn = wm.debit_wallet("u1", SlowCompare("10.00"), transaction_type="fee")
        with lock:
            granted.append(ok)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda _: withdraw(), range(workers)))

    balance = wm.get_wallet("u1").subscription_balance
    assert balance >= Decimal("0.00"), f"wallet overdrawn to {balance}"
    assert sum(granted) == 10, "more debits were granted than the balance covered"
    assert balance == Decimal("0.00")


# --------------------------------------------------------------------------
# F138 — the invariant that catches both, actually wired
# --------------------------------------------------------------------------


def test_balance_after_invariant_refuses_a_corrupted_movement(monkeypatch):
    """
    ``verify_balance_after`` exists and is unit-tested in isolation, but no
    production path calls it. Wire it into the write path: if the recorded
    balance_after does not equal before + delta, the movement is refused rather
    than recorded.
    """
    wm = WalletManager()
    wallet = wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("50.00"))

    # Simulate the corruption the invariant is meant to catch: something moves
    # the balance out from under the write path between the read and the check.
    real_now = wm._new_transaction_id

    def corrupting_id():
        wallet.subscription_balance += Decimal("999.00")
        return real_now()

    monkeypatch.setattr(wm, "_new_transaction_id", corrupting_id)

    ok, msg, txn = wm.credit_wallet("u1", Decimal("10.00"))

    assert ok is False, "a balance that does not reconcile was accepted"
    assert txn is None
    assert "balance" in msg.lower()


def test_amount_must_be_finite_and_positive():
    """NaN and infinity are finite-number violations the invariants reject; the
    write path must reject them before they reach a balance."""
    wm = WalletManager()
    wm.create_wallet("u1")

    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        ok, _msg, _txn = wm.credit_wallet("u1", bad)
        assert ok is False, f"accepted {bad} as a credit amount"

    assert wm.get_wallet("u1").subscription_balance == Decimal("0.00")


# --------------------------------------------------------------------------
# Balance restore must not mix the two wallets
# --------------------------------------------------------------------------


def test_restore_does_not_read_a_commission_balance_into_the_subscription_wallet():
    """
    ``_load_balance_from_db`` took the newest row for the user regardless of
    which wallet it belonged to, and assigned its balance_after to
    ``subscription_balance``. A commission credit followed by a restart
    therefore overwrote the subscription balance with an unrelated number.
    """

    class Row:
        def __init__(self, balance_after, notes):
            self.balance_after = balance_after
            self.notes = notes

    rows = [
        Row(70.0, WalletType.SUBSCRIPTION),
        Row(5.0, WalletType.COMMISSION),  # newest row belongs to the other wallet
    ]

    class Query:
        def __init__(self, rows):
            self._rows = rows

        def filter_by(self, **kw):
            notes = kw.get("notes")
            if notes is None:
                return Query(self._rows)
            return Query([r for r in self._rows if r.notes == notes])

        def order_by(self, *_a):
            return Query(list(reversed(self._rows)))

        def first(self):
            return self._rows[0] if self._rows else None

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def query(self, _model):
            return Query(rows)

    wm = WalletManager(session_factory=Session)
    wallet = wm.create_wallet("u1")

    assert wallet.subscription_balance == Decimal("70.0")
    assert wallet.commission_balance == Decimal("5.0")


def test_frozen_wallet_still_refuses_movement():
    """Regression guard: the locking rework must not drop the status gate."""
    wm = WalletManager()
    wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("100.00"))
    wm.freeze_wallet("u1")

    ok_credit, _m1, _t1 = wm.credit_wallet("u1", Decimal("1.00"))
    ok_debit, _m2, _t2 = wm.debit_wallet("u1", Decimal("1.00"))

    assert ok_credit is False
    assert ok_debit is False
    assert wm.get_wallet("u1").subscription_balance == Decimal("100.00")
    assert wm.get_wallet("u1").status == WalletStatus.FROZEN


# --------------------------------------------------------------------------
# Transfers must conserve the total
# --------------------------------------------------------------------------


def test_transfer_conserves_the_total_balance():
    wm = WalletManager()
    wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("60.00"))

    ok, msg = wm.transfer_between_wallets("u1", Decimal("25.00"), WalletType.SUBSCRIPTION, WalletType.COMMISSION)

    assert ok, msg
    wallet = wm.get_wallet("u1")
    assert wallet.subscription_balance == Decimal("35.00")
    assert wallet.commission_balance == Decimal("25.00")
    assert wallet.subscription_balance + wallet.commission_balance == Decimal("60.00")


def test_no_observer_sees_a_half_completed_transfer():
    """
    The debit and the credit are two movements. Between them the user's total is
    short by the transferred amount, and get_balance() would report it. Holding
    the lock across both legs is what makes that state unobservable.
    """
    wm = WalletManager()
    wm.create_wallet("u1")
    wm.credit_wallet("u1", Decimal("100.00"))

    totals = []
    stop = threading.Event()

    def observe():
        while not stop.is_set():
            b = wm.get_balance("u1")
            totals.append(b["total_balance"])

    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    try:
        # SlowAdd sleeps inside the credit leg — that is, after the debit has
        # already committed — which is exactly the window in which the total is
        # short. Without it the window is too narrow for the observer to land in
        # and the test passes on unlocked code.
        for _ in range(6):
            wm.transfer_between_wallets("u1", SlowAdd("10.00"), WalletType.SUBSCRIPTION, WalletType.COMMISSION)
            wm.transfer_between_wallets("u1", SlowAdd("10.00"), WalletType.COMMISSION, WalletType.SUBSCRIPTION)
    finally:
        stop.set()
        watcher.join(timeout=2)

    assert totals, "observer never sampled the balance"
    assert set(totals) == {100.0}, f"a partial transfer was observable: {sorted(set(totals))}"


def test_sub_cent_amounts_are_refused_not_rounded():
    """
    balance_after is persisted to a Float column. A balance that is a whole
    number of cents round-trips exactly; a sub-cent residue would live only in
    memory and be lost on restart. Rounding it here would instead move money the
    caller did not ask to move, so it is refused.
    """
    wm = WalletManager()
    wm.create_wallet("u1")

    ok, msg, _txn = wm.credit_wallet("u1", Decimal("0.005"))
    assert ok is False
    assert "cent" in msg.lower()
    assert wm.get_wallet("u1").subscription_balance == Decimal("0.00")

    ok, _msg, _txn = wm.credit_wallet("u1", Decimal("0.01"))
    assert ok is True


def test_balances_round_trip_through_the_float_ledger_column():
    """Every recorded balance_after must read back as the exact Decimal it was."""
    wm = WalletManager()
    wm.create_wallet("u1")

    for amount in ("0.01", "0.07", "19.99", "1234.56", "0.03"):
        ok, _msg, txn = wm.credit_wallet("u1", Decimal(amount))
        assert ok
        assert Decimal(str(txn["balance_after"])) == wm.get_wallet("u1").subscription_balance
