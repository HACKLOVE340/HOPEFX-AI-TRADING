# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_trading_endpoints_are_isolated.py
==================================================
The reported bug, reproduced through the actual endpoints.

``tests/unit/test_per_user_accounts.py`` proves the registry hands two users two
accounts. This proves the *endpoints* use it: place an order as one user and
read positions, balance and orders as another, through the real handler
functions with no broker mocking.

That distinction matters. The registry could be perfect and a single handler
still calling ``_broker_call`` would put every user back on the shared book —
which is exactly how the original gaps appeared, endpoint by endpoint.
"""

from __future__ import annotations

import pytest

from core.account_registry import reset_account_registry

pytestmark = pytest.mark.unit


class _User:
    def __init__(self, sub: str, role: str = "trader"):
        self.sub = sub
        self.role = role


@pytest.fixture(autouse=True)
def _isolated_paper_accounts(monkeypatch):
    monkeypatch.setenv("BROKER_TYPE", "paper")
    monkeypatch.setenv("INITIAL_BALANCE", "50000")
    reset_account_registry()
    yield
    reset_account_registry()


@pytest.fixture
def trading(monkeypatch):
    """api.trading with a broker present so readiness guards pass.

    ``app_state.broker`` still has to exist — several handlers check it to decide
    whether the engine has booted — but nothing may *read* from it. That is what
    this test is really asserting.
    """
    import api.trading as trading_mod
    from brokers.paper_trading import PaperTradingBroker

    class _State:
        broker = PaperTradingBroker(user_id="shared-engine", namespace="test-shared-engine")
        db_session_factory = None
        risk_manager = None
        compliance_manager = None

    monkeypatch.setattr(trading_mod, "app_state", _State())
    return trading_mod


async def _place(trading, user: _User, qty: float, symbol: str = "XAUUSD"):
    """Place an order the way the endpoint does, skipping the gates that need
    a database and a subscription service."""
    from api.trading import OrderRequest

    order = OrderRequest(symbol=symbol, side="buy", quantity=qty)
    return await trading._route_to_broker(order, user.sub)


@pytest.mark.asyncio
async def test_one_users_order_does_not_appear_in_anothers_positions(trading):
    alice, bob = _User("alice"), _User("bob")

    await _place(trading, alice, 2.0)

    assert await trading.get_positions(user=bob) == [], (
        "alice's order is visible in bob's positions — this is the report"
    )
    alice_positions = await trading.get_positions(user=alice)
    assert len(alice_positions) == 1
    assert alice_positions[0].quantity == 2.0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["trader", "admin", "superadmin"])
async def test_no_role_sees_another_users_positions(trading, role):
    """Including the roles that used to bypass the filter entirely."""
    await _place(trading, _User("alice"), 1.0)

    operator = _User("operator-1", role)
    assert await trading.get_positions(user=operator) == [], (
        f"a {role} sees another user's positions on the ordinary endpoint"
    )


@pytest.mark.asyncio
async def test_an_operators_own_trade_is_not_shown_to_others(trading):
    """The report, in the direction it was phrased: the superadmin trades and
    somebody else sees it."""
    await _place(trading, _User("root", "superadmin"), 3.0)

    assert await trading.get_positions(user=_User("bob")) == []


@pytest.mark.asyncio
async def test_balances_do_not_move_together(trading):
    alice, bob = _User("alice"), _User("bob")

    before = await trading.get_balance(user=bob)
    await _place(trading, alice, 4.0)
    after = await trading.get_balance(user=bob)

    assert after["balance"] == before["balance"], "alice's trade moved bob's balance"
    assert after["equity"] == before["equity"], "alice's trade moved bob's equity"


@pytest.mark.asyncio
async def test_orders_are_not_shared(trading):
    """``GET /api/trading/orders`` had no ownership filter of any kind."""
    await _place(trading, _User("alice"), 1.0)

    # limit/offset passed explicitly: calling the handler directly bypasses
    # FastAPI's dependency resolution, so the Query defaults arrive as Query
    # objects rather than ints.
    bob_orders = await trading.get_orders(user=_User("bob"), status_filter=None, limit=50, offset=0)
    alice_orders = await trading.get_orders(user=_User("alice"), status_filter=None, limit=50, offset=0)

    bob_ids = {o["order_id"] for o in bob_orders["orders"]}
    alice_ids = {o["order_id"] for o in alice_orders["orders"]}
    assert not (bob_ids & alice_ids), f"bob can see alice's orders: {sorted(bob_ids & alice_ids)}"


@pytest.mark.asyncio
async def test_close_all_cannot_reach_another_users_book(trading):
    """The destructive one. ``close_all_positions`` on the shared engine would
    liquidate every trader's book from one user's "Close All" button."""
    alice, bob = _User("alice"), _User("bob")
    await _place(trading, alice, 1.0)
    await _place(trading, bob, 1.0)

    await trading.close_all_positions(user=alice)

    assert await trading.get_positions(user=alice) == []
    assert len(await trading.get_positions(user=bob)) == 1, "alice's close-all liquidated bob's position"


@pytest.mark.asyncio
async def test_the_shared_engine_is_never_read(trading):
    """The engine's own book must not leak into anybody's view, whatever is in
    it."""
    shared = trading.app_state.broker
    await shared.connect()
    await shared.place_market_order(symbol="XAUUSD", side="buy", quantity=9.0)

    for user in (_User("alice"), _User("root", "superadmin")):
        positions = await trading.get_positions(user=user)
        assert positions == [], f"{user.role} sees the shared engine's own position: {positions}"


@pytest.mark.asyncio
async def test_the_account_payload_declares_whether_it_is_isolated(trading):
    balance = await trading.get_balance(user=_User("alice"))
    assert balance is not None

    resolution = await trading._resolve_account("alice")
    assert resolution.isolated is True
