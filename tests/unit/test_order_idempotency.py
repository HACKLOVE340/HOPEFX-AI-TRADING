# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_order_idempotency.py
=====================================
Regression tests for pre-launch finding R-01: a retried order was a second order.

Migration ``b2c3d4e5f6a7`` added ``UNIQUE(client_order_id)`` and its docstring
states the scope plainly — "Prevents duplicate order submission on broker retry
(network timeout **between API and broker**)". That is the engine→broker hop. The
client→API hop had nothing: a lost response, a load-balancer timeout, or a
double-tap produced a genuinely new request, a fresh engine-side
``client_order_id``, no UNIQUE collision, and a second real position.

The per-user order rate limit does not close this. Two distinct requests inside
the window are both legitimate to a rate limiter — it bounds frequency, not
duplication.

These tests exercise ``core.idempotency`` directly rather than through the order
route, because placing a real order needs a broker, risk manager and KYC'd user;
the semantics being protected live in the store.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from core import idempotency as idem


def _body_source(func) -> str:
    """Return a function's source with its docstring removed."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


@pytest.fixture(autouse=True)
def _clean_store():
    """Isolate tests from each other and from a live Redis.

    The store prefers Redis when reachable, and CI may or may not have one, so
    each test uses a unique user id — that keys the namespace apart regardless of
    backend — and the in-process map is cleared either way.
    """
    idem.reset_for_testing()
    yield
    idem.reset_for_testing()


_BODY = {"symbol": "XAUUSD", "side": "buy", "quantity": 0.1, "order_type": "market"}


@pytest.mark.unit
class TestFirstUseThenReplay:
    def test_first_use_returns_none_so_the_caller_proceeds(self):
        assert idem.begin("u-first", "key-1", _BODY) is None

    def test_completed_request_is_replayed_not_re_executed(self):
        idem.begin("u-replay", "key-1", _BODY)
        idem.complete("u-replay", "key-1", _BODY, {"order_id": "abc123", "status": "filled"})

        replayed = idem.begin("u-replay", "key-1", _BODY)
        assert replayed == {"order_id": "abc123", "status": "filled"}, (
            "A retry must return the original order's response. Returning None "
            "here would let the caller place the same order twice (R-01)."
        )

    def test_in_flight_replay_conflicts_rather_than_duplicating(self):
        """The first request has not finished, so there is no response to return."""
        idem.begin("u-inflight", "key-1", _BODY)
        with pytest.raises(idem.IdempotencyConflict):
            idem.begin("u-inflight", "key-1", _BODY)


@pytest.mark.unit
class TestKeyIsBoundToTheRequest:
    def test_same_key_different_order_is_rejected(self):
        """Otherwise a reused key silently hides a real, different order."""
        idem.begin("u-bound", "key-1", _BODY)
        idem.complete("u-bound", "key-1", _BODY, {"order_id": "abc123"})

        different = {**_BODY, "quantity": 5.0}  # 50x the size
        with pytest.raises(idem.IdempotencyKeyReused):
            idem.begin("u-bound", "key-1", different)

    def test_field_order_does_not_change_the_fingerprint(self):
        """An equivalent body serialised differently is the same request."""
        reordered = {"order_type": "market", "quantity": 0.1, "side": "buy", "symbol": "XAUUSD"}
        idem.begin("u-order", "key-1", _BODY)
        idem.complete("u-order", "key-1", _BODY, {"order_id": "abc123"})
        assert idem.begin("u-order", "key-1", reordered) == {"order_id": "abc123"}


@pytest.mark.unit
class TestIsolationAndFailureHandling:
    def test_keys_are_namespaced_per_user(self):
        """One caller's key must not collide with or probe another's."""
        idem.begin("user-a", "shared-key", _BODY)
        idem.complete("user-a", "shared-key", _BODY, {"order_id": "a-order"})

        # Same key string, different user → must be a fresh first use.
        assert idem.begin("user-b", "shared-key", _BODY) is None

    def test_failed_request_stays_retryable(self):
        """A rejection must not be cached as if it were a result.

        If a risk-gate rejection were stored, the caller could never place that
        order with that key again — the endpoint would have locked them out.
        """
        idem.begin("u-fail", "key-1", _BODY)
        idem.release("u-fail", "key-1")
        assert idem.begin("u-fail", "key-1", _BODY) is None

    def test_raw_key_is_not_used_as_the_storage_key(self):
        """The key reaches Redis; a caller-chosen string should not shape it."""
        full = idem._full_key("u-hash", "super-secret-client-key")
        assert "super-secret-client-key" not in full

    def test_order_body_is_not_stored_only_its_digest(self):
        fp = idem._fingerprint(_BODY)
        assert "XAUUSD" not in fp and "0.1" not in fp


@pytest.mark.unit
class TestRouteIsWired:
    """The store only helps on a route that actually uses it."""

    def test_place_order_accepts_an_idempotency_key_header(self):
        from api.trading import place_order

        sig = inspect.signature(place_order)
        assert "idempotency_key" in sig.parameters, (
            "POST /api/trading/orders must accept Idempotency-Key, or a retrying "
            "client still places duplicate orders (R-01)."
        )

    def test_place_order_claims_before_side_effects_and_releases_on_failure(self):
        from api import trading

        # Strip the docstring before comparing positions: place_order's docstring
        # lists its sub-functions by name ("_route_to_broker() — broker
        # submission"), so a raw source search finds the prose, not the call, and
        # reports the ordering backwards.
        src = _body_source(trading.place_order)
        claim = src.index("_idem.begin")
        route = src.index("_route_to_broker")
        assert claim < route, (
            "The key must be claimed before the order reaches the broker; "
            "claiming afterwards leaves the duplicate window wide open."
        )
        assert "_idem.release" in src, "a failed order must stay retryable (R-01)"
        assert "_idem.complete" in src, "a successful order must be replayable (R-01)"
