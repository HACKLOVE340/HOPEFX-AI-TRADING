# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_graphql_orders_are_gated.py
============================================
Regression tests for findings S-17 and S-19: the GraphQL mutations bypassed
every risk gate, created nothing, and reported success either way.

``Mutation.place_order`` called ``state.broker.place_order(...)`` directly and
then returned ``OrderResult(placed=True, ...)`` unconditionally.

**Gate bypass.** ``POST /api/trading/order`` runs, in order:

    _check_subscription_gate → _check_kill_switch (hard block, first)
    → _check_trading_paused → _check_live_deployment_gates
    → _validate_order (broker availability, prop-firm rules)
    → _apply_risk_checks (RiskManager + CVaR) → _log_compliance

The mutation ran **none** of them, so an order placed over GraphQL reached the
broker with the kill switch engaged.

**Unconditional success.** ``placed=True`` was hardcoded. When the broker call
raised — caught and logged at warning level — or when no broker was attached at
all, the client still received ``placed=True``, a fabricated ``uuid4()[:8]``
order id, ``fill_price=0.0`` and the message "Order placed". A trader would
believe they held a position they did not hold. ``cancel_order`` and
``modify_order`` had the same shape: ``cancelled=True`` / ``modified=True``
regardless of outcome. Moving a stop-loss is a risk decision — being told the
stop moved when it did not is worse than being told the call failed.

Reachability: the mutations were dead in practice because the auth helper
rejected every request (S-15). Fixing that made them live, which is why this
had to be fixed in the same pass rather than filed.

**S-19 — ``create_alert`` stored nothing.** It generated ``uuid4()[:8]``, wrote
a log line, and returned ``created=True`` with that id. A real ``AlertEngine``
sits behind ``POST /api/alerts/`` and persists and evaluates alerts; the
mutation never touched it, so every alert created over GraphQL silently did not
exist and would never fire.

The mutations now delegate to the same helpers the REST endpoints use, so the
paths cannot drift, and refusals surface with their real reason rather than
as "An internal error occurred".
"""

from __future__ import annotations

import ast
import json
import tempfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "api" / "graphql_schema.py"

_PLACE = 'mutation { placeOrder(symbol: "XAU/USD", side: "BUY", lots: 0.01) { placed orderId message } }'
_CANCEL = 'mutation { cancelOrder(orderId: "abc") { cancelled message } }'
_MODIFY = 'mutation { modifyOrder(orderId: "abc", stopLoss: 1.0) { modified message } }'


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "graphql-orders-test-secret-min-32-chars")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.graphql_schema import graphql_router

    app = FastAPI()
    app.include_router(graphql_router, prefix="/graphql")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def headers():
    from auth.jwt import ALGORITHM, _get_secret

    token = pyjwt.encode(
        {"sub": "gql-order-user", "type": "access", "role": "trader", "exp": int(time.time()) + 600},
        _get_secret(),
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _post(client, headers, query: str) -> dict:
    return client.post("/graphql", json={"query": query}, headers=headers).json()


@pytest.mark.unit
class TestNothingClaimsSuccessItDidNotAchieve:
    """No broker is attached in a unit run — the honest answer is a refusal."""

    def test_place_order_does_not_report_a_phantom_fill(self, client, headers):
        body = _post(client, headers, _PLACE)

        assert body["data"] is None, (
            f"placeOrder returned {json.dumps(body['data'])} with no broker "
            "attached. It must refuse rather than hand back placed=true and a "
            "fabricated order id (S-17)."
        )
        assert "Broker not initialised" in body["errors"][0]["message"]

    def test_cancel_order_does_not_report_a_phantom_cancel(self, client, headers):
        body = _post(client, headers, _CANCEL)

        assert body["data"] is None
        assert "not cancelled" in body["errors"][0]["message"]

    def test_modify_order_does_not_report_a_phantom_modify(self, client, headers):
        body = _post(client, headers, _MODIFY)

        assert body["data"] is None
        assert "not modified" in body["errors"][0]["message"]

    def test_the_refusal_carries_its_real_reason(self, client, headers):
        """Not "An internal error occurred" — the trader needs to know why."""
        body = _post(client, headers, _PLACE)
        error = body["errors"][0]

        assert error["message"] != "An internal error occurred"
        assert error["extensions"]["error_code"] == "VALIDATION_ERROR"


@pytest.mark.unit
class TestTheKillSwitchStopsAGraphQLOrder:
    """The gate that matters most, exercised through the real mutation."""

    def test_an_engaged_kill_switch_refuses_the_order(self, client, headers, monkeypatch):
        from kill_switch import KillSwitch

        from api import trading

        switch = KillSwitch(flag_file=Path(tempfile.mkdtemp()) / "halt.flag")
        switch.activate(reason="unit test halt")
        monkeypatch.setattr(trading, "_kill_switch_instance", switch, raising=False)
        assert switch.is_active()

        try:
            body = _post(client, headers, _PLACE)
        finally:
            switch.reset_for_testing()

        assert body["data"] is None, "an order was accepted with the kill switch engaged (S-17)"
        message = body["errors"][0]["message"]
        assert "kill switch active" in message
        assert "unit test halt" in message, "the halt reason must reach the client"


@pytest.mark.unit
class TestTheMutationUsesTheRestPipeline:
    """Structural: the two order paths must not drift apart again."""

    @staticmethod
    def _place_order_body() -> list[ast.stmt]:
        tree = ast.parse(_SCHEMA.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "place_order":
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body = body[1:]  # the docstring describes the old bug
                return body
        raise AssertionError("Mutation.place_order not found in api/graphql_schema.py")

    @classmethod
    def _place_order_source(cls) -> str:
        return "\n".join(ast.unparse(statement) for statement in cls._place_order_body())

    @classmethod
    def _called_names(cls) -> set[str]:
        """Names actually *invoked* in the mutation.

        Deliberately not a substring search over the source: the gates are
        imported inside the function, so their names appear in the body whether
        or not anything calls them. Deleting all four `_check_*()` calls left a
        naive text check green — the failure that produced this method.
        """
        called: set[str] = set()
        for statement in cls._place_order_body():
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name):
                        called.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        called.add(func.attr)
        return called

    @pytest.mark.parametrize(
        "gate",
        [
            "_check_subscription_gate",
            "_check_kill_switch",
            "_check_trading_paused",
            "_check_live_deployment_gates",
            "_validate_order",
            "_apply_risk_checks",
            "_log_compliance",
            "_route_to_broker",
            "_record_fill",
        ],
    )
    def test_every_rest_gate_is_invoked(self, gate):
        assert gate in self._called_names(), (
            f"{gate}() is not called by the GraphQL placeOrder mutation. The "
            "REST endpoint runs it before any order reaches a broker; GraphQL "
            "must not be a way around it (S-17)."
        )

    def test_it_no_longer_calls_the_broker_directly(self):
        source = self._place_order_source()
        assert "broker.place_order" not in source, (
            "placeOrder is calling the broker directly again, which is what skipped every gate (S-17)."
        )

    def test_placed_true_is_only_reached_after_the_pipeline(self):
        """`placed=True` must sit after `_record_fill`, not before the try."""
        source = self._place_order_source()
        assert source.index("_record_fill") < source.index("placed=True"), (
            "the success flag is set before the order is actually recorded"
        )


@pytest.mark.unit
class TestSideNormalisation:
    """`OrderRequest.side` is `^(buy|sell)$`; GraphQL accepts BUY/LONG/SELL/SHORT."""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [("BUY", "buy"), ("buy", "buy"), ("LONG", "buy"), ("SELL", "sell"), ("SHORT", "sell")],
    )
    def test_accepted_sides_map_to_the_order_request_pattern(self, given, expected, client, headers):
        from api.trading import OrderRequest

        # The mapping the mutation applies, asserted against the model that
        # consumes it — `side.upper()` used to be passed straight through and
        # failed OrderRequest validation on every single order.
        order = OrderRequest(symbol="XAU/USD", side=expected, quantity=0.01)
        assert order.side == expected

        query = f'mutation {{ placeOrder(symbol: "XAU/USD", side: "{given}", lots: 0.01) {{ placed }} }}'
        message = _post(client, headers, query)["errors"][0]["message"]
        assert "Invalid side" not in message
        assert "string_pattern_mismatch" not in message, (
            f"side={given!r} did not survive normalisation into OrderRequest"
        )

    def test_a_nonsense_side_is_still_rejected(self, client, headers):
        query = 'mutation { placeOrder(symbol: "XAU/USD", side: "SIDEWAYS", lots: 0.01) { placed } }'
        assert "Invalid side" in _post(client, headers, query)["errors"][0]["message"]


@pytest.mark.unit
class TestMutationsStillRequireAuth:
    @pytest.mark.parametrize("query", [_PLACE, _CANCEL, _MODIFY], ids=["place", "cancel", "modify"])
    def test_no_token_no_order(self, client, query):
        body = client.post("/graphql", json={"query": query}).json()

        assert body["data"] is None
        assert body["errors"][0]["message"] == "Authentication required"
        assert body["errors"][0]["extensions"]["error_code"] == "UNAUTHORIZED"


@pytest.mark.unit
class TestAlertsAreActuallyCreated:
    """S-19: ``createAlert`` stored nothing and reported success anyway.

    It generated ``uuid4()[:8]``, logged a line, and returned ``created=True``
    with that id. ``POST /api/alerts/`` writes to a real ``AlertEngine`` that
    persists and evaluates alerts; this mutation never touched it. Every alert
    created over GraphQL silently did not exist and would never fire.
    """

    @pytest.fixture
    def admin_headers(self):
        from auth.jwt import ALGORITHM, _get_secret

        # Admin bypasses require_plan("starter"), isolating the storage path.
        token = pyjwt.encode(
            {"sub": "gql-alert-user", "type": "access", "role": "admin", "exp": int(time.time()) + 600},
            _get_secret(),
            algorithm=ALGORITHM,
        )
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _alerts_for(user_id: str):
        from api.alerts import _get_engine

        return [a for a in _get_engine(None).get_alerts(user_id=user_id) if a.user_id == user_id]

    def test_the_alert_reaches_the_engine(self, client, admin_headers):
        before = len(self._alerts_for("gql-alert-user"))

        body = _post(
            client,
            admin_headers,
            'mutation { createAlert(symbol: "XAU/USD", condition: "above", price: 2500.0) { created alertId } }',
        )

        assert body.get("errors") is None, body.get("errors")
        assert body["data"]["createAlert"]["created"] is True

        after = self._alerts_for("gql-alert-user")
        assert len(after) == before + 1, (
            "createAlert reported success but stored nothing — the caller is "
            "told an alert exists that will never fire (S-19)."
        )

        created = after[-1]
        assert created.symbol == "XAU/USD"
        assert created.conditions[0].type.value == "price_above"
        assert created.conditions[0].threshold == 2500.0
        assert created.user_id == "gql-alert-user"

    def test_the_returned_id_is_the_engines_id_not_a_random_one(self, client, admin_headers):
        body = _post(
            client,
            admin_headers,
            'mutation { createAlert(symbol: "XAU/USD", condition: "below", price: 1900.0) { alertId } }',
        )
        returned = body["data"]["createAlert"]["alertId"]

        assert returned, "no alert id returned"
        assert any(a.id == returned for a in self._alerts_for("gql-alert-user")), (
            f"alert id {returned!r} does not match anything in the engine — it is a fabricated uuid again (S-19)."
        )

    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("above", "price_above"),
            ("below", "price_below"),
            ("crosses_above", "price_cross_above"),
            ("crosses_below", "price_cross_below"),
        ],
    )
    def test_each_condition_maps_to_a_real_engine_condition(self, condition, expected, client, admin_headers):
        from notifications.alert_engine import AlertConditionType

        assert AlertConditionType(expected)  # the engine really has it

        body = _post(
            client,
            admin_headers,
            f'mutation {{ createAlert(symbol: "EUR/USD", condition: "{condition}", price: 1.1) {{ created }} }}',
        )
        assert body.get("errors") is None, body.get("errors")
        assert self._alerts_for("gql-alert-user")[-1].conditions[0].type.value == expected

    def test_bare_crosses_is_refused_rather_than_guessed(self, client, admin_headers):
        """A single threshold cannot say which direction was meant."""
        body = _post(
            client,
            admin_headers,
            'mutation { createAlert(symbol: "XAU/USD", condition: "crosses", price: 2400.0) { created } }',
        )

        message = body["errors"][0]["message"]
        assert "Invalid condition" in message
        assert "crosses_above" in message and "crosses_below" in message, (
            "the error must name the two directional forms that replace it"
        )

    def test_get_engine_tolerates_a_missing_request(self):
        """The GraphQL path shares this helper and has no FastAPI Request."""
        from api.alerts import _get_engine

        assert _get_engine(None) is not None, (
            "_get_engine did `request.app.state` unconditionally and raised "
            "AttributeError on None; step 3 lazy-init exists exactly so a "
            "missing engine is not fatal."
        )
