# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_per_user_accounts.py
=====================================
Backlog T-01 — two users trading the same symbol must not share a position.

``app_state.broker`` was one process-wide engine with one account, and
``PaperTradingBroker.positions`` is keyed by *symbol*. ``_update_position``
merges into the existing entry ("For simplicity, assume same side"), so a 1-lot
buy and a 3-lot buy on XAUUSD produced **one** position — quantity 4.0, entry
price averaged, id ``"XAUUSD"``. Two users' capital in one object, and
``close_position("XAUUSD")`` closing it for both.

Nothing on the read path can undo that merge: once the two fills are averaged
into a single record there is no share left to attribute to either user. The
separation has to exist in the broker, which is what ``core.account_registry``
provides — one ``PaperTradingBroker`` per user, each with its own positions,
orders, balance and Redis namespace. The class already supported this and its
docstring documents the pattern; nothing had ever constructed a second instance.

These tests are the ones that would have caught the original report: *"if the
superadmin enters a trade, another user can see it."*
"""

from __future__ import annotations

import pytest

from core.account_registry import get_account_registry, reset_account_registry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    monkeypatch.setenv("BROKER_TYPE", "paper")
    monkeypatch.setenv("INITIAL_BALANCE", "100000")
    reset_account_registry()
    yield
    reset_account_registry()


async def _buy(resolution, symbol="XAUUSD", qty=1.0):
    return await resolution.broker.place_market_order(symbol=symbol, side="buy", quantity=qty)


# ── The reported defect ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_users_trading_one_symbol_get_separate_positions():
    reg = get_account_registry()
    alice = await reg.resolve("alice")
    bob = await reg.resolve("bob")

    await _buy(alice, qty=1.0)
    await _buy(bob, qty=3.0)

    alice_positions = await alice.broker.get_positions()
    bob_positions = await bob.broker.get_positions()

    assert len(alice_positions) == 1
    assert len(bob_positions) == 1
    assert alice_positions[0].quantity == 1.0, (
        f"alice's position shows {alice_positions[0].quantity} lots — bob's 3 lots were "
        "merged into it. This is the symbol-keyed position dict (T-01)."
    )
    assert bob_positions[0].quantity == 3.0


@pytest.mark.asyncio
async def test_a_superadmin_trade_is_not_visible_to_another_user():
    """The report, stated literally."""
    reg = get_account_registry()
    superadmin = await reg.resolve("superadmin-1")
    trader = await reg.resolve("trader-1")

    await _buy(superadmin, qty=2.0)

    assert await trader.broker.get_positions() == [], "a trade placed by the superadmin appears in another user's book"


@pytest.mark.asyncio
async def test_closing_one_users_position_leaves_the_other_open():
    """``close_position`` takes a symbol. On the shared broker that closed the
    single merged position, so one user flattening their book flattened the
    other's too."""
    reg = get_account_registry()
    alice = await reg.resolve("alice")
    bob = await reg.resolve("bob")

    await _buy(alice)
    await _buy(bob)

    alice.broker.close_position("XAUUSD")

    assert await alice.broker.get_positions() == []
    assert len(await bob.broker.get_positions()) == 1, "closing alice's position also closed bob's"


@pytest.mark.asyncio
async def test_one_users_pnl_does_not_move_another_users_balance():
    """The second half of the report: the superadmin's trade moved everyone's
    numbers, because balance and equity came from the one shared account."""
    reg = get_account_registry()
    alice = await reg.resolve("alice")
    bob = await reg.resolve("bob")

    bob_balance_before = bob.broker.balance
    bob_equity_before = bob.broker.equity

    await _buy(alice, qty=5.0)

    assert bob.broker.balance == bob_balance_before, "alice's trade moved bob's balance"
    assert bob.broker.equity == bob_equity_before, "alice's trade moved bob's equity"


@pytest.mark.asyncio
async def test_each_account_starts_from_the_configured_balance():
    reg = get_account_registry()
    alice = await reg.resolve("alice")
    bob = await reg.resolve("bob")

    assert alice.broker.balance == 100_000.0
    assert bob.broker.balance == 100_000.0
    assert alice.broker is not bob.broker


# ── Registry behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_same_user_always_gets_the_same_account():
    reg = get_account_registry()
    first = await reg.resolve("alice")
    await _buy(first)
    second = await reg.resolve("alice")

    assert second.broker is first.broker
    assert len(await second.broker.get_positions()) == 1, "the user's own position vanished on the second call"


@pytest.mark.asyncio
async def test_concurrent_first_requests_do_not_split_a_user_across_two_accounts():
    """Two simultaneous requests from one user must not each build a broker —
    that would scatter their positions across two objects and recreate the bug
    in a new shape."""
    import asyncio

    reg = get_account_registry()
    results = await asyncio.gather(*(reg.resolve("racy") for _ in range(12)))

    brokers = {id(r.broker) for r in results}
    assert len(brokers) == 1, f"one user ended up with {len(brokers)} accounts"


@pytest.mark.asyncio
async def test_per_user_namespace_is_stable_under_test_env(monkeypatch):
    """PaperTradingBroker's default namespace is a fresh UUID when APP_ENV=test,
    which would hand the same user a different account on every call. The
    registry names the namespace explicitly for that reason."""
    monkeypatch.setenv("APP_ENV", "test")
    reset_account_registry()
    reg = get_account_registry()

    first = await reg.resolve("alice")
    second = await reg.resolve("alice")
    assert first.broker._redis_namespace == second.broker._redis_namespace == "user:alice"


# ── Honesty about live venues ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("broker_type", ["oanda", "mt5", "ibkr"])
async def test_a_live_venue_is_reported_as_not_isolated(monkeypatch, broker_type):
    """There is one real account at the venue. Presenting two users with "their
    own" view of it would be a lie with money attached, so the resolution says
    so instead."""
    monkeypatch.setenv("BROKER_TYPE", broker_type)
    reset_account_registry()
    reg = get_account_registry()

    resolution = await reg.resolve("alice")
    assert resolution.isolated is False
    assert broker_type in resolution.reason


@pytest.mark.asyncio
async def test_an_unauthenticated_request_is_not_isolated():
    reg = get_account_registry()
    resolution = await reg.resolve("")
    assert resolution.isolated is False
    assert "no authenticated user id" in resolution.reason


@pytest.mark.asyncio
async def test_a_failed_account_creation_is_reported_not_hidden(monkeypatch):
    """Falling back to the shared broker is sometimes unavoidable; doing it
    silently is what turns it into a leak."""
    reg = get_account_registry()

    async def _boom(_user_id):
        raise RuntimeError("redis exploded")

    monkeypatch.setattr(reg, "_create_broker", _boom)

    resolution = await reg.resolve("alice")
    assert resolution.isolated is False
    assert "redis exploded" in resolution.reason
