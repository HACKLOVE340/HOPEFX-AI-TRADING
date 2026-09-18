# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A confirmed Stripe payment credits the depositor's wallet — exactly once.

ADR 0021: the fiat wallet is the ledger the money path writes through. This is
Task 1 of docs/audit/plans/2026-09-18-wallet-becomes-the-ledger.md — the credit
side, which must land before the debit side because `_apply_movement` refuses a
debit against a wallet that does not exist or has no funds.

The money is credited on `payment_intent.succeeded`, NOT when the intent is
created. Creating an intent moves nothing.

## The test that matters is the replay

Stripe delivers webhooks AT LEAST once. Retries and replays are normal, not
exceptional. A repeated `payment_intent.succeeded` that credits twice creates
capital out of nothing, which is a P0 in its own right. `WalletTransaction`
gives `transaction_id` a unique constraint, but that id is generated per call,
so it cannot deduplicate anything — the deduplicating key is the Stripe payment
intent id, carried in `reference`.

These tests run against a REAL database (`sync_db_engine` + `db_tables`) rather
than the hand-rolled fake Sessions used elsewhere in the wallet suite. A fake
session cannot enforce a uniqueness constraint, and the constraint is the point:
a read-then-write check in Python races, and two concurrent deliveries of the
same event would both pass it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker


def _event(pi_id: str, *, cents: int, user_id: str | None = "user-dep-1") -> dict:
    """A `payment_intent.succeeded` data object, as Stripe sends it."""
    metadata: dict[str, str] = {"reference": "DEP-TESTREF"}
    if user_id is not None:
        metadata["user_id"] = user_id
    return {
        "id": pi_id,
        "amount": cents,  # Stripe amounts are INTEGER CENTS
        "currency": "usd",
        "customer": "cus_stripe_side_id",
        "metadata": metadata,
    }


@pytest.fixture
def wallet_and_rows(sync_db_engine, db_tables, monkeypatch):
    """A WalletManager on a real session factory, wired where the webhook looks."""
    from core.app_state import app_state
    from database.models import WalletTransaction
    from payments.wallet import WalletManager

    factory = sessionmaker(bind=sync_db_engine)

    # `sync_db_engine` and `db_tables` are SESSION-scoped, so rows survive
    # between tests. These assertions count rows, so a leaked row from an
    # earlier test reads as a duplicate credit — start from an empty ledger.
    with factory() as s:
        s.query(WalletTransaction).delete()
        s.commit()

    wm = WalletManager(session_factory=factory)
    monkeypatch.setattr(app_state, "wallet_manager", wm, raising=False)

    def rows(user_id: str = "user-dep-1"):
        with factory() as s:
            return s.query(WalletTransaction).filter_by(user_id=user_id).all()

    return wm, rows


def test_a_confirmed_payment_credits_the_wallet(wallet_and_rows):
    """The first production writer of wallet_transactions."""
    from api.billing import _credit_confirmed_deposit

    wm, rows = wallet_and_rows
    _credit_confirmed_deposit(_event("pi_first", cents=2500))

    written = rows()
    assert len(written) == 1, f"expected one ledger row, got {len(written)}"
    assert Decimal(str(written[0].amount)) == Decimal("25.00"), (
        "Stripe sends integer cents; 2500 must become 25.00, not 2500.00 and not 25.000001"
    )
    assert wm.get_wallet("user-dep-1") is not None, "the credit did not create the wallet"


def test_a_replayed_webhook_credits_only_once(wallet_and_rows):
    """THE test. Two deliveries of the SAME event must move money once."""
    from api.billing import _credit_confirmed_deposit

    wm, rows = wallet_and_rows
    _credit_confirmed_deposit(_event("pi_replayed", cents=5000))
    balance_after_first = wm.get_balance("user-dep-1")

    _credit_confirmed_deposit(_event("pi_replayed", cents=5000))

    written = rows()
    assert len(written) == 1, (
        f"a replayed payment_intent.succeeded wrote {len(written)} ledger rows — "
        "the same money was credited more than once, which creates capital"
    )
    assert wm.get_balance("user-dep-1") == balance_after_first, (
        "the balance moved twice for one payment"
    )


def test_two_distinct_payments_both_credit(wallet_and_rows):
    """A control. Deduplication must key on the payment, not refuse every second credit.

    Without this, an implementation that credits once and then refuses
    everything would pass the replay test.
    """
    from api.billing import _credit_confirmed_deposit

    _wm, rows = wallet_and_rows
    _credit_confirmed_deposit(_event("pi_one", cents=1000))
    _credit_confirmed_deposit(_event("pi_two", cents=1000))

    assert len(rows()) == 2, "two different payments must produce two ledger rows"


def test_a_payment_that_names_no_user_credits_nobody(wallet_and_rows):
    """Fail closed on attribution: never guess which wallet money belongs to.

    Retrying will not help — the intent simply carries no user_id — so this is
    reported rather than raised, and loudly enough to be found.
    """
    from api.billing import _credit_confirmed_deposit

    _wm, rows = wallet_and_rows
    result = _credit_confirmed_deposit(_event("pi_orphan", cents=9900, user_id=None))

    assert rows("user-dep-1") == [], "an unattributable payment was credited to someone"
    assert result.get("credited") is False
    assert "attribut" in (result.get("reason") or "").lower()


def test_the_ledger_being_unavailable_does_not_silently_drop_the_money(monkeypatch):
    """No wallet manager means the credit is LOST unless someone is told.

    Returning "handled" here is how a confirmed payment goes unrecorded with
    nothing in the logs to find later.
    """
    from core.app_state import app_state

    from api.billing import _credit_confirmed_deposit

    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)
    result = _credit_confirmed_deposit(_event("pi_no_ledger", cents=1000))

    assert result.get("credited") is False
    assert result.get("retryable") is True, (
        "a missing ledger is a server-side problem, so the delivery must be retryable "
        "rather than acknowledged as done"
    )


# ── the control must actually RUN on the webhook path ────────────────────────


def _drive_the_webhook(monkeypatch, event: dict):
    """Call the real route with a verified event, stubbing only Stripe itself."""
    import asyncio
    from types import SimpleNamespace

    from api import billing

    class _FakeClient:
        @staticmethod
        def verify_webhook(_payload, _sig):
            return event

        @staticmethod
        def handle_webhook_event(_event):
            return {"handled": True}

    monkeypatch.setattr(
        "monetization.stripe_live.get_stripe_client",
        lambda: _FakeClient(),
        raising=False,
    )
    monkeypatch.setattr(billing, "_get_subscription_manager", lambda: SimpleNamespace(
        handle_stripe_webhook=lambda *_a, **_k: None
    ), raising=False)

    class _Request:
        headers = {"stripe-signature": "sig"}

        async def body(self):
            return b"{}"

    return asyncio.run(billing.stripe_webhook(_Request()))


def test_the_webhook_route_actually_credits(wallet_and_rows, monkeypatch):
    """`hopefx-dead-controls`: a credit helper nothing calls is not a credit path.

    Asserted by driving the route, not by reading it.
    """
    _wm, rows = wallet_and_rows
    _drive_the_webhook(
        monkeypatch,
        {"id": "evt_1", "type": "payment_intent.succeeded",
         "data": {"object": _event("pi_via_route", cents=4200)}},
    )

    written = rows()
    assert len(written) == 1, "the webhook route ran and no ledger row was written"
    assert Decimal(str(written[0].amount)) == Decimal("42.00")


def test_an_unrelated_event_is_not_treated_as_a_deposit(wallet_and_rows, monkeypatch):
    """A control. Only payment_intent.succeeded moves money."""
    _wm, rows = wallet_and_rows
    _drive_the_webhook(
        monkeypatch,
        {"id": "evt_2", "type": "customer.subscription.updated",
         "data": {"object": _event("pi_not_a_deposit", cents=9999)}},
    )

    assert rows() == [], "a subscription event credited the wallet"


def test_a_credit_that_cannot_be_recorded_asks_stripe_to_redeliver(monkeypatch):
    """Acknowledging an uncreditable payment loses the money silently.

    Stripe retries on a 5xx and stops on a 2xx, so 'handled' here is how a
    confirmed deposit goes unrecorded with nothing left to recover it from.
    """
    from fastapi import HTTPException

    from core.app_state import app_state

    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)

    with pytest.raises(HTTPException) as excinfo:
        _drive_the_webhook(
            monkeypatch,
            {"id": "evt_3", "type": "payment_intent.succeeded",
             "data": {"object": _event("pi_no_ledger_route", cents=1000)}},
        )

    assert excinfo.value.status_code == 503, (
        f"expected a retryable 5xx so Stripe redelivers, got {excinfo.value.status_code}"
    )
