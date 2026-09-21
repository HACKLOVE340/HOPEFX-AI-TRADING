# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`/billing/balance` must say which number it is showing, and admit when it does not know.

BALANCE-SOURCE-SPLIT. `get_balance` promises "the authenticated user's wallet
balance" and reads the BROKER account, then overwrites it with the subscription
manager — never `wallet_transactions`, the ledger a withdrawal is refused
against since ADR 0021. Two numbers, from two sources, and nothing saying so.

Three separate defects sit in that one function, and each has its own test here:

* **A failed lookup reads as a real zero.** Both sources are wrapped in
  `except Exception: logger.debug(...)`, and DEBUG is off in production. A user
  whose broker call times out is shown `0.00` in a response byte-identical to a
  genuinely empty account. This is the shape `hopefx-dead-controls` calls "the
  evidence swallowed by except", on a money display.
* **The docstring's priority is backwards.** It says the subscription manager is
  read "when available" and the broker is the fallback. The code reads the broker
  first and lets the subscription manager overwrite it.
* **`round(x, 2)` on a float is banker's rounding.** 2.675 becomes 2.67, not
  2.68. `hopefx-money-precision` names this one by name.

What these tests deliberately do NOT do is decide which source is authoritative.
That is reconciliation, and it is the owner's call. They make the disagreement
VISIBLE, which is what the register says deleting the docstring's promise would
fail to do: "that would leave two numbers and no statement that they disagree".
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker


def _user(sub: str = "user-bal-1"):
    return SimpleNamespace(sub=sub)


def _balance(**_kw):
    from api.billing import get_balance

    return asyncio.run(get_balance(user=_user()))


@pytest.fixture
def no_sources(monkeypatch):
    """Neither the broker nor the subscription manager can answer."""
    from core.app_state import app_state

    from api import billing

    monkeypatch.setattr(app_state, "broker", None, raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)

    def _boom():
        raise RuntimeError("subscription manager unavailable")

    monkeypatch.setattr(billing, "_get_subscription_manager", _boom, raising=False)
    return billing


@pytest.fixture
def broker_only(monkeypatch):
    """A broker that answers, and a subscription manager that cannot."""
    from core.app_state import app_state

    from api import billing

    class _Broker:
        @staticmethod
        async def get_account():
            return SimpleNamespace(balance=1234.56, margin_used=100.0)

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)

    def _boom():
        raise RuntimeError("subscription manager unavailable")

    monkeypatch.setattr(billing, "_get_subscription_manager", _boom, raising=False)
    return billing


# ── a failed lookup is not a zero balance ────────────────────────────────────


def test_a_failed_lookup_is_not_reported_as_a_zero_balance(no_sources):
    """Showing 0.00 for "we could not find out" is a money bug with a friendly face."""
    result = _balance()

    assert result.get("balance_known") is False, (
        "no source answered and the response still presents a number as if it were known"
    )


def test_a_real_zero_is_distinguishable_from_a_failed_lookup(monkeypatch):
    """The control. If both read the same, the first test proves nothing."""
    from core.app_state import app_state

    from api import billing

    class _Broker:
        @staticmethod
        async def get_account():
            return SimpleNamespace(balance=0.0, margin_used=0.0)

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)
    monkeypatch.setattr(
        billing, "_get_subscription_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")), raising=False
    )

    result = _balance()

    assert result["balance"] == 0.0
    assert result.get("balance_known") is True, "a genuine zero was reported as unknown"


# ── the response says where the number came from ─────────────────────────────


def test_the_response_names_the_source_it_used(broker_only):
    """Two sources, one number. Which one is not a detail."""
    result = _balance()

    assert result.get("source") == "broker", f"expected the broker to be named, got {result.get('source')!r}"
    assert result["balance"] == 1234.56


def test_a_source_that_failed_is_reported_not_swallowed(no_sources, caplog):
    """DEBUG is off in production, so a DEBUG line is the same as no line."""
    import logging

    with caplog.at_level(logging.WARNING, logger="api.billing"):
        _balance()

    assert caplog.records, (
        "every balance source failed and nothing was logged above DEBUG — in production this is a silent zero"
    )


# ── the ledger is reported alongside, so the split is visible ────────────────


def test_the_ledger_balance_is_reported_alongside(sync_db_engine, db_tables, monkeypatch):
    """Reconciliation needs the two numbers side by side to compare at all."""
    from core.app_state import app_state
    from database.models import WalletTransaction
    from payments.wallet import WalletManager

    from api import billing

    factory = sessionmaker(bind=sync_db_engine)
    with factory() as s:
        s.query(WalletTransaction).delete()
        s.commit()

    wm = WalletManager(session_factory=factory)
    ok, msg, _ = wm.credit_wallet("user-bal-1", Decimal("40.00"), reference="seed:bal")
    assert ok, msg

    class _Broker:
        @staticmethod
        async def get_account():
            return SimpleNamespace(balance=1234.56, margin_used=0.0)

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", wm, raising=False)
    monkeypatch.setattr(
        billing, "_get_subscription_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")), raising=False
    )

    result = _balance()

    assert result.get("ledger_balance") == 40.0, (
        f"the wallet ledger — the number a withdrawal is actually refused against — is not in the response: {result!r}"
    )
    assert result["balance"] == 1234.56
    assert result.get("sources_agree") is False, (
        "the shown balance and the ledger disagree and the response does not say so"
    )


# ── money rounding ───────────────────────────────────────────────────────────


def test_rounding_is_half_up_not_bankers(monkeypatch):
    """`round(2.675, 2)` is 2.67. A cent, every time, in the same direction."""
    from core.app_state import app_state

    from api import billing

    class _Broker:
        @staticmethod
        async def get_account():
            return SimpleNamespace(balance=2.675, margin_used=0.0)

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)
    monkeypatch.setattr(
        billing, "_get_subscription_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")), raising=False
    )

    result = _balance()

    assert result["balance"] == 2.68, (
        f"expected ROUND_HALF_UP to give 2.68, got {result['balance']} — that is banker's rounding"
    )


# ── a zero balance must not crash the lookup ─────────────────────────────────


@pytest.mark.parametrize(
    "account,label",
    [
        (SimpleNamespace(balance=0.0, margin_used=0.0), "object-style"),
        ({"balance": 0.0, "margin_used": 0.0}, "mapping-style"),
    ],
)
def test_a_zero_balance_does_not_crash_the_broker_read(account, label, monkeypatch):
    """`getattr(a, "balance", 0) or a.get("balance", 0)` conflated MISSING with ZERO.

    A broker reporting a genuine zero fell through to the mapping branch because
    0.0 is falsy; an object-style account has no `.get`, so it raised
    AttributeError into an `except` that logged at DEBUG. The user saw a number
    that came from somewhere else entirely, and nothing said so.

    Both shapes are tested because the fix has two branches and a fix that only
    works for the shape the test uses is not a fix.
    """
    from core.app_state import app_state

    from api import billing

    class _Broker:
        @staticmethod
        async def get_account():
            return account

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)
    monkeypatch.setattr(
        billing, "_get_subscription_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")), raising=False
    )

    result = _balance()

    assert result["balance"] == 0.0
    assert result["balance_known"] is True, f"a real zero from a {label} account read as unknown"
    assert result["source"] == "broker"


def test_a_nonzero_mapping_account_still_reads(monkeypatch):
    """The control for the above: the mapping branch must still return the value."""
    from core.app_state import app_state

    from api import billing

    class _Broker:
        @staticmethod
        async def get_account():
            return {"balance": 77.5, "margin_used": 2.25}

    monkeypatch.setattr(app_state, "broker", _Broker(), raising=False)
    monkeypatch.setattr(app_state, "wallet_manager", None, raising=False)
    monkeypatch.setattr(
        billing, "_get_subscription_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")), raising=False
    )

    result = _balance()

    assert result["balance"] == 77.5
    assert result["frozen"] == 2.25
