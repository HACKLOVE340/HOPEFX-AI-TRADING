# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_advanced_orders_are_owner_scoped.py
====================================================
Regression tests for finding S-23: advanced orders ignored who was asking.

`api/advanced_orders.py` (`/api/orders/advanced`) is mounted **unconditionally**
— no feature flag — and guarded by `require_role("trader")`. All seven of its
endpoints bound `user` for authentication and then never consulted it:

    POST   /oco            attached SL/TP to whatever position_id it was given
    POST   /trailing-stop  same
    POST   /stop-limit     same
    DELETE /{order_id}     cancelled any order by id
    GET    /{order_id}     returned any order by id
    GET    /active         returned **every** user's active orders
    GET    /health         (aggregate counts only — legitimately unscoped)

The manager's API had nowhere to put an owner either:
``submit_oco(position_id, symbol, side, quantity, stop_loss_price,
take_profit_price)``, ``cancel_order(order_id)``.

This is not single-tenancy. `api/trading.py` routes every position, order and
balance call through `_user_broker_call(user_id, ...)`, and `close_position`
carries an explicit ownership check that logs ``"IDOR blocked: ..."``. The same
class of bug was found and fixed on the REST path; this router never got it.

So a trader could attach or cancel protective orders on another user's
position, and list every user's active advanced orders — symbols, sizes and
stop levels, which is exactly the data this module's own header calls "the most
sensitive data in the system, since knowing where stops sit is knowing where
forced liquidations occur".

Deliberately **not** changed, having read it: these endpoints do not run the
kill switch or the risk gate that `POST /api/trading/order` does. OCO and
trailing stops are protective — they attach a stop to an existing position
rather than opening exposure — and blocking them during a halt would leave
positions unprotected. That is a defensible design difference; the missing
ownership check was not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API = _REPO_ROOT / "api" / "advanced_orders.py"


@pytest.fixture
def manager():
    from execution.advanced_orders import AdvancedOrderManager

    return AdvancedOrderManager()


async def _alice_oco(manager) -> str:
    return await manager.submit_oco(
        user_id="alice",
        position_id="pos-alice",
        symbol="XAU/USD",
        side="sell",
        quantity=1.0,
        stop_loss_price=2400.0,
        take_profit_price=2600.0,
    )


@pytest.mark.unit
class TestOneUserCannotTouchAnothersOrders:
    @pytest.mark.asyncio
    async def test_active_orders_are_filtered_to_the_caller(self, manager):
        alice = await _alice_oco(manager)
        bob = await manager.submit_trailing_stop(
            user_id="bob",
            position_id="pos-bob",
            symbol="XAU/USD",
            side="sell",
            quantity=1.0,
            trail_distance_pips=20,
        )

        assert [o["order_id"] for o in manager.get_active_orders(user_id="alice")] == [alice]
        assert [o["order_id"] for o in manager.get_active_orders(user_id="bob")] == [bob]

    @pytest.mark.asyncio
    async def test_reading_someone_elses_order_answers_nothing(self, manager):
        alice = await _alice_oco(manager)

        assert manager.get_order(alice, user_id="bob") is None, (
            "Bob can read Alice's order — stop levels disclose where her position gets liquidated (S-23)."
        )
        assert manager.get_order(alice, user_id="alice")["order_id"] == alice

    @pytest.mark.asyncio
    async def test_cancelling_someone_elses_order_does_nothing(self, manager):
        alice = await _alice_oco(manager)

        assert await manager.cancel_order(alice, user_id="bob") is False
        assert [o["order_id"] for o in manager.get_active_orders(user_id="alice")] == [alice], (
            "Bob's cancel took effect on Alice's order — that removes her stop loss (S-23)."
        )

        assert await manager.cancel_order(alice, user_id="alice") is True
        assert manager.get_active_orders(user_id="alice") == []

    @pytest.mark.asyncio
    async def test_a_refusal_is_indistinguishable_from_a_missing_order(self, manager):
        """So a caller cannot enumerate which order ids exist."""
        alice = await _alice_oco(manager)

        assert manager.get_order(alice, user_id="bob") == manager.get_order("no-such-order", user_id="bob")
        assert await manager.cancel_order(alice, user_id="bob") == await manager.cancel_order(
            "no-such-order", user_id="bob"
        )


@pytest.mark.unit
class TestInternalCallersStillSeeEverything:
    """The monitor loops have no user context and must keep working."""

    @pytest.mark.asyncio
    async def test_no_user_id_matches_every_order(self, manager):
        alice = await _alice_oco(manager)
        bob = await manager.submit_stop_limit(
            user_id="bob",
            position_id="pos-bob",
            symbol="XAU/USD",
            side="buy",
            quantity=1.0,
            stop_price=2500.0,
            limit_price=2505.0,
        )

        seen = {o["order_id"] for o in manager.get_active_orders()}
        assert seen == {alice, bob}
        assert manager.get_order(alice) is not None
        assert await manager.cancel_order(bob) is True

    @pytest.mark.asyncio
    async def test_an_order_with_no_recorded_owner_stays_visible(self, manager):
        """This is an authorisation check, not a data migration."""
        legacy = await manager.submit_oco(
            position_id="pos-legacy",
            symbol="XAU/USD",
            side="sell",
            quantity=1.0,
            stop_loss_price=2400.0,
            take_profit_price=2600.0,
        )

        assert manager.get_order(legacy, user_id="anyone") is not None


@pytest.mark.unit
class TestTheOwnerIsRecordedOnTheOrder:
    """Not in a side index that can drift out of step with the order."""

    @pytest.mark.asyncio
    async def test_submitted_orders_carry_their_owner(self, manager):
        alice = await _alice_oco(manager)

        assert manager.get_order(alice, user_id="alice")["user_id"] == "alice"

    def test_all_three_order_types_have_the_field(self):
        from execution.advanced_orders import OCOOrder, StopLimitOrder, TrailingStopOrder

        for cls in (OCOOrder, TrailingStopOrder, StopLimitOrder):
            assert "user_id" in cls.__dataclass_fields__, f"{cls.__name__} cannot record an owner (S-23)"


@pytest.mark.unit
class TestEveryEndpointPassesTheCallerThrough:
    """Structural, so a new endpoint cannot quietly skip the scoping."""

    @staticmethod
    def _handlers() -> dict[str, str]:
        tree = ast.parse(_API.read_text(encoding="utf-8"))
        out: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                for d in node.decorator_list
            ):
                out[node.name] = ast.unparse(node)
        return out

    def test_the_expected_endpoints_are_present(self):
        assert set(self._handlers()) == {
            "submit_oco",
            "submit_trailing_stop",
            "submit_stop_limit",
            "cancel_advanced_order",
            "list_active_orders",
            "get_order_details",
            "advanced_orders_health",
        }

    @pytest.mark.parametrize(
        "handler",
        [
            "submit_oco",
            "submit_trailing_stop",
            "submit_stop_limit",
            "cancel_advanced_order",
            "list_active_orders",
            "get_order_details",
        ],
    )
    def test_it_uses_the_authenticated_caller(self, handler):
        assert "user.sub" in self._handlers()[handler], (
            f"{handler} binds `user` for authentication and then ignores it — which is the whole of S-23."
        )

    @pytest.mark.asyncio
    async def test_health_is_the_only_unscoped_endpoint(self, manager):
        """It is legitimately unscoped: counts and capability flags, no order data.

        Asserted against what `health()` actually returns rather than an
        allowlist written from memory — the first version of this test guessed
        the key names and failed on its own invention.
        """
        await _alice_oco(manager)
        health = manager.health()

        assert set(health) == {
            "running",
            "active_oco",
            "active_trailing",
            "active_stop_limit",
            "total_orders",
            "tracked_symbols",
            "native_oco",
            "native_trailing",
            "native_stop_limit",
        }, f"health() has changed shape: {sorted(health)} — re-check it discloses nothing per-user"

        # Nothing identifying: no order ids, no owners, no price levels.
        rendered = repr(health)
        assert "alice" not in rendered
        assert "oco_" not in rendered
        assert "2400" not in rendered and "2600" not in rendered
        assert isinstance(health["total_orders"], int)

    @pytest.mark.parametrize("handler", ["submit_oco", "submit_trailing_stop", "submit_stop_limit"])
    def test_submits_check_position_ownership(self, handler):
        assert "_require_position_ownership" in self._handlers()[handler], (
            f"{handler} lets a trader attach an order to a position they do not own (S-23)."
        )
