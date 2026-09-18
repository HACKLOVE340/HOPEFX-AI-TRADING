# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A withdrawal debits the wallet ledger — behind a flag, and refusing honestly.

Task 2 of docs/audit/plans/2026-09-18-wallet-becomes-the-ledger.md, under
ADR 0021. Task 1 made deposits credit the ledger; only now is there anything to
debit, because `_apply_movement` refuses a debit against a wallet that does not
exist or has no funds.

## Why this ships default-off

`api/billing.py::get_balance` promises "the authenticated user's wallet balance"
and reads the BROKER account, falling back to the subscription manager. It never
reads the wallet ledger. The number a user sees and the number `debit_wallet`
checks come from different sources, and the ledger carries no history — nothing
wrote it before Task 1. Unflagged, every withdrawal would refuse `402` for users
the UI says have funds. `WITHDRAWAL_DEBITS_LEDGER` defaults to false.

## Why the refusals are not collapsed

`debit_wallet` can refuse for eight distinct reasons. Mapping them all to one
status hides a ledger-corruption event behind "insufficient funds". The
reconciliation failure in particular must never be a 4xx: nothing the caller did
caused it and nothing they change will fix it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker


def _request(amount: float = 50.0):
    from api.payments import FiatWithdrawRequest

    return FiatWithdrawRequest(amount=amount, destination="bank")


def _user(sub: str = "user-wd-1"):
    from types import SimpleNamespace

    return SimpleNamespace(sub=sub)


async def _withdraw(amount: float = 50.0, sub: str = "user-wd-1"):
    from api.payments import fiat_withdraw

    return await fiat_withdraw(_request(amount), user=_user(sub), _rl=None)


@pytest.fixture
def ledger(sync_db_engine, db_tables, monkeypatch):
    """A funded wallet, a real AML gate, and the flag ON."""
    from compliance import aml
    from core.app_state import app_state
    from database.models import WalletTransaction
    from payments.wallet import WalletManager

    factory = sessionmaker(bind=sync_db_engine)
    with factory() as s:
        s.query(WalletTransaction).delete()
        s.commit()

    wm = WalletManager(session_factory=factory)
    monkeypatch.setattr(app_state, "wallet_manager", wm, raising=False)
    monkeypatch.setenv("WITHDRAWAL_DEBITS_LEDGER", "true")

    # A REAL gate over the REAL ledger. `debit_wallet` fails closed
    # unconditionally, so a test without a reachable gate would refuse every
    # withdrawal and tempt someone to loosen that fail-closed — which is the
    # trap `_screen_withdrawal_for_aml`'s docstring predicts.
    monkeypatch.setattr(aml, "_aml_gate", aml.AMLGate(session_factory=factory), raising=False)

    def fund(amount: str, user_id: str = "user-wd-1"):
        ok, msg, _ = wm.credit_wallet(user_id, Decimal(amount), reference=f"seed:{user_id}:{amount}")
        assert ok, f"seeding the wallet failed: {msg}"

    def rows(user_id: str = "user-wd-1", kind: str | None = None):
        with factory() as s:
            q = s.query(WalletTransaction).filter_by(user_id=user_id)
            if kind:
                q = q.filter_by(transaction_type=kind)
            return q.all()

    return wm, fund, rows


# ── the flag ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_flag_defaults_to_off_and_nothing_is_debited(ledger, monkeypatch):
    """Default behaviour is unchanged: 202, and the ledger is untouched."""
    _wm, fund, rows = ledger
    fund("500.00")
    monkeypatch.delenv("WITHDRAWAL_DEBITS_LEDGER", raising=False)

    result = await _withdraw(50.0)

    assert result["status"] == "pending"
    assert rows(kind="withdrawal") == [], "the flag is off and a debit row was written anyway"


@pytest.mark.asyncio
async def test_with_the_flag_on_a_withdrawal_writes_a_debit_row(ledger):
    """The first production debit of the ledger."""
    wm, fund, rows = ledger
    fund("500.00")

    result = await _withdraw(50.0)

    written = rows(kind="withdrawal")
    assert len(written) == 1, f"expected one debit row, got {len(written)}"
    assert Decimal(str(written[0].amount)) == Decimal("50.00")
    assert wm.get_balance("user-wd-1")["subscription_balance"] == Decimal("450.00")
    assert result["status"] == "pending"


# ── the refusals, each distinct ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_over_balance_is_402_and_writes_nothing(ledger):
    from fastapi import HTTPException

    _wm, fund, rows = ledger
    fund("20.00")

    with pytest.raises(HTTPException) as exc:
        await _withdraw(50.0)

    assert exc.value.status_code == 402, f"insufficient funds should be 402, got {exc.value.status_code}"
    assert rows(kind="withdrawal") == [], "a refused withdrawal still wrote a ledger row"


@pytest.mark.asyncio
async def test_no_wallet_is_404_not_402(ledger):
    """Having no wallet is not the same event as having an empty one."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _withdraw(50.0, sub="user-with-no-wallet")

    assert exc.value.status_code == 404, f"expected 404 for a missing wallet, got {exc.value.status_code}"


@pytest.mark.asyncio
async def test_a_frozen_wallet_is_409_not_402(ledger):
    """An operator froze this wallet. If that reads as a balance problem the
    freeze looks like a bug and someone 'fixes' it."""
    from fastapi import HTTPException

    wm, fund, _rows = ledger
    fund("500.00")
    wm.freeze_wallet("user-wd-1")

    with pytest.raises(HTTPException) as exc:
        await _withdraw(50.0)

    assert exc.value.status_code == 409, f"a frozen wallet should be 409, got {exc.value.status_code}"


@pytest.mark.asyncio
async def test_a_reconciliation_failure_is_5xx_not_4xx(ledger, monkeypatch):
    """Corruption must never read as the caller's fault.

    Decimal arithmetic on whole cents is exact, so a mismatch is not drift — it
    is a balance that must never be recorded. Returning 4xx would tell the user
    to change their request, which cannot help.
    """
    from fastapi import HTTPException

    from payments.wallet import WalletManager

    wm, fund, _rows = ledger
    fund("500.00")
    monkeypatch.setattr(
        WalletManager,
        "debit_wallet",
        lambda *a, **k: (False, "Balance did not reconcile; movement refused", None),
    )

    with pytest.raises(HTTPException) as exc:
        await _withdraw(50.0)

    assert exc.value.status_code >= 500, (
        f"a reconciliation failure must not be a client error, got {exc.value.status_code}"
    )


# ── the point of the whole exercise ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_aml_daily_count_rule_can_now_fire(ledger):
    """AML Rule 3 counts same-day withdrawals. It has never had rows to count.

    MAX_WITHDRAWALS_PER_DAY defaults to 5, so the sixth must be refused — by
    compliance, with a 403, not by the balance check.
    """
    from fastapi import HTTPException

    _wm, fund, rows = ledger
    fund("10000.00")

    for _ in range(5):
        await _withdraw(10.0)

    assert len(rows(kind="withdrawal")) == 5

    with pytest.raises(HTTPException) as exc:
        await _withdraw(10.0)

    assert exc.value.status_code == 403, (
        f"the sixth same-day withdrawal should be refused by AML with 403, got "
        f"{exc.value.status_code} — if this is 402 the balance check refused it instead"
    )
    assert len(rows(kind="withdrawal")) == 5, "the refused withdrawal was still recorded"
