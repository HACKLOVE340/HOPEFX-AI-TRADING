# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_account_isolation.py
=====================================
Users must not see — or share — each other's trading activity.

**What was found.** ``app_state.broker`` is one process-wide engine with one
account, and every logged-in user trades against it. This is stated in the code
itself (``api/trading.py``: "a single process-wide paper engine shared by every
logged-in user, so its get_positions() returns EVERYONE's positions";
``api/ws_live.py``: "single-account deployment ... BEFORE enabling multi-tenant
accounts this MUST become send_to_user"). Isolation was deferred, and the
filters added afterwards landed unevenly: ``/trading/positions`` filtered,
``/trading/orders`` did not, ``/trading/balance`` did not, ``api/portfolio.py``
did not, and the WebSocket account broadcaster pushed one account's equity to
every subscriber.

**It goes deeper than the reads.** ``PaperTradingBroker.positions`` is a
``dict[str, Position]`` keyed by *symbol*, and ``_update_position`` merges into
the existing entry ("For simplicity, assume same side"). So two users buying
XAUUSD do not get two positions — they get one, with a weighted-average entry
price and the combined quantity, whose id is the symbol. Their capital is
commingled in a single object, and ``close_position("XAUUSD")`` closes it for
both. ``PaperTradingBroker.__init__`` already accepts ``user_id``; it is stored
in ``self._user_id`` and never read.

That is why filtering the reads is not sufficient on its own, and why it is not
safe alone either: with one netted position per symbol, at most one user can own
the matching row, so gating positions without fixing the broker would make the
*other* user's own position vanish from their screen.

This file covers the ownership layer that is in place (``core.tenancy``) and
pins the broker behaviour that the account work has to change.
"""

from __future__ import annotations

import pytest

from core import tenancy

pytestmark = pytest.mark.unit


class _User:
    def __init__(self, sub: str, role: str = "trader"):
        self.sub = sub
        self.role = role


# ── The acting account ───────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["trader", "admin", "superadmin"])
def test_every_role_acts_on_its_own_account(role):
    """Operators used to bypass the position filter entirely — ``None`` meaning
    "no filtering" — so an admin placing a trade saw the whole book on the
    ordinary endpoints. Whole-book access now lives on operator routes that name
    the account explicitly and are audited."""
    assert tenancy.acting_user_id(_User("u-1", role)) == "u-1"


def test_operator_roles_are_recognised_for_the_operator_routes():
    assert tenancy.is_operator(_User("u", "superadmin"))
    assert tenancy.is_operator(_User("u", "admin"))
    assert not tenancy.is_operator(_User("u", "trader"))
    assert not tenancy.is_operator(_User("u", "viewer"))


# ── Fail closed ──────────────────────────────────────────────────────────────


def test_no_database_yields_an_empty_book_not_the_shared_one(monkeypatch):
    """If ownership cannot be established there is no safe way to show the
    shared engine's rows. An empty book is a bug a user reports; another
    trader's positions is one nobody reports and everybody sees."""
    monkeypatch.setattr(tenancy, "_session_factory", lambda: None)

    assert tenancy.owned_position_ids("alice") == set()
    assert tenancy.owned_order_ids("alice") == set()


def test_a_failing_query_yields_an_empty_book(monkeypatch):
    def _boom():
        class _F:
            def __call__(self):
                raise RuntimeError("db down")

        return _F()

    monkeypatch.setattr(tenancy, "_session_factory", _boom)
    assert tenancy.owned_position_ids("alice") == set()


def test_an_empty_user_id_yields_an_empty_book():
    assert tenancy.owned_position_ids("") == set()


# ── Row scoping ──────────────────────────────────────────────────────────────


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_only_owned_rows_survive():
    rows = [_Row(id="p1"), _Row(id="p2"), _Row(id="p3")]
    kept = tenancy.scope_rows(rows, {"p1", "p3"})
    assert [r.id for r in kept] == ["p1", "p3"]


def test_rows_with_no_identifier_are_dropped_not_kept():
    """An unidentifiable row cannot be shown to have come from this account."""
    rows = [_Row(id="p1"), _Row(id=""), _Row(other="x")]
    assert [r.id for r in tenancy.scope_rows(rows, {"p1"})] == ["p1"]


def test_orders_are_matched_on_their_own_id_attribute():
    """Broker objects are not uniform — positions expose ``id``, orders expose
    ``order_id``."""
    rows = [_Row(order_id="o1"), _Row(order_id="o2")]
    kept = tenancy.scope_rows(rows, {"o2"}, id_attrs=("id", "order_id"))
    assert [r.order_id for r in kept] == ["o2"]


def test_dict_rows_work_too():
    rows = [{"id": "a"}, {"id": "b"}]
    assert tenancy.scope_rows(rows, {"b"}) == [{"id": "b"}]


# ── The model gap that made /trading/orders unfilterable ─────────────────────


def test_the_order_model_declares_its_owning_user():
    """The ``orders.user_id`` COLUMN has existed since migration o1p2q3r4s5t6,
    but this model never declared it, so the ORM had no attribute to filter on
    and the orders endpoint returned the shared book to every caller."""
    from database.models import Order

    assert "user_id" in Order.__table__.columns, (
        "Order has no user_id attribute — core.tenancy cannot scope orders and "
        "GET /api/trading/orders falls back to showing everyone's"
    )


def test_the_orders_ownership_index_is_named_as_the_migration_created_it():
    """Two differently-named indexes on the same column is how create_all and
    Alembic drift apart."""
    from database.models import Order

    names = {i.name for i in Order.__table__.indexes}
    assert "idx_orders_user_id" in names
    assert "ix_orders_user_id" not in names, "index=True on the column duplicates the explicit Index"


# ── Why one broker instance can never serve two users ────────────────────────


@pytest.mark.asyncio
async def test_one_broker_instance_merges_everything_into_one_position_per_symbol():
    """The measurement behind ``core.account_registry``.

    A single ``PaperTradingBroker`` keys ``positions`` by symbol and merges on
    write, so two fills on one symbol become one record — quantity summed, entry
    averaged, id equal to the symbol. That is correct for *one* account and
    catastrophic for two, and it cannot be undone downstream: after the merge
    there is no share left to attribute to either user.

    This is pinned rather than fixed. The netting is right for a single account;
    the fix is to stop sharing the instance, which is what the registry does —
    see tests/unit/test_per_user_accounts.py.
    """
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(user_id="shared", namespace="test-shared-merge")
    await broker.connect()

    await broker.place_market_order(symbol="XAUUSD", side="buy", quantity=1.0)
    await broker.place_market_order(symbol="XAUUSD", side="buy", quantity=3.0)

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 4.0
    assert str(positions[0].id) == "XAUUSD", "the position id is the symbol — there is no per-user identity in it"


@pytest.mark.asyncio
async def test_the_registry_is_what_separates_them():
    """The same two fills, routed through per-user accounts."""
    from core.account_registry import get_account_registry, reset_account_registry

    reset_account_registry()
    try:
        reg = get_account_registry()
        alice = await reg.resolve("iso-alice")
        bob = await reg.resolve("iso-bob")

        await alice.broker.place_market_order(symbol="XAUUSD", side="buy", quantity=1.0)
        await bob.broker.place_market_order(symbol="XAUUSD", side="buy", quantity=3.0)

        assert (await alice.broker.get_positions())[0].quantity == 1.0
        assert (await bob.broker.get_positions())[0].quantity == 3.0
    finally:
        reset_account_registry()
