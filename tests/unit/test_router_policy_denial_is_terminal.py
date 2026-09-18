"""A router that refuses an order must not be overruled by its caller.

`hopefx_engine._execute_decision` falls back to a direct `broker.place_order`
when `ExecutionEngine` is unavailable. On that path it consulted `SmartRouter`
and then did this::

    if sr_result.get("status") not in ("rejected", "error"):
        ...                                   # routed
    else:
        logger.warning("SmartRouter rejected (%s) — falling back to direct order", ...)

    if not _used_smart_router:
        await self._broker.place_order(**order_kwargs)      # placed anyway

`rejected` is not only "no venue was reachable". `execution/smart_router.py`
returns it for five policy denials:

| where | reason | what it means |
|---|---|---|
| :557 | `unauthorized:…` | `enforce_order_authorization` refused. Logged CRITICAL as "Router BLOCKED order". The comment above it reads: *no order may reach a broker without a risk-approval token + decision id* |
| :266 | `spread_too_wide:…` | spread beyond the configured maximum |
| :266 | `sentiment_blackout:…` | news blackout |
| :266 | `macro_impact_blackout:…` | macro-event blackout |
| :283 | `fia_throttle:…` | FIA 3.4 regulatory message throttle |

So the authorization invariant logged that it had blocked the order, and the
order went to the broker regardless. That is the `hopefx-dead-controls` shape at
its purest: the control fires correctly and the caller ignores it.

The fallback path runs only when `ExecutionEngine` is unavailable, which makes
it rare rather than safe — the 12-check pre-trade gate is absent there too, so
the router's verdict was the last policy control standing on it.

Transport failures are treated separately and are not all alike:

* `no_brokers_available` — nothing was transmitted, and the pre-route gates
  already passed to reach it, so a direct send is policy-clean.
* `all_brokers_failed:…`, `timeout:…`, or an exception out of the router — an
  order may already be in flight. Sending another is the duplicate fill
  ROUTER-TO was fixed to prevent, so these refuse until the outcome is
  reconciled. Rule 3: fail closed on anything that trades.

These tests drive the real `_execute_decision`, not a copy of its logic.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


class _Spy:
    """A broker that records whether anyone asked it to place an order."""

    def __init__(self) -> None:
        self.orders: list[dict] = []

    def get_positions(self):
        return []

    def place_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"fill_price": 1.0, "order_id": "SHOULD-NOT-EXIST"}


class _Router:
    def __init__(self, result: dict | Exception) -> None:
        self._result = result
        self.calls = 0

    async def route_and_execute(self, request):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _engine(router, broker):
    """A HopeFXEngine positioned exactly on the fallback path.

    Built with __new__ so none of the real startup runs; every attribute the
    path reads is set explicitly, so the test cannot pass by accident of
    construction.
    """
    from hopefx_engine import HopeFXEngine

    e = HopeFXEngine.__new__(HopeFXEngine)
    e._execution_engine = None  # the condition that selects the fallback path
    e._smart_router = router
    e._broker = broker
    e.trading_mode = "live"
    e.broker_name = "spy"
    e._risk_manager = SimpleNamespace(
        size_order=lambda d: SimpleNamespace(quantity=1.0, stop_loss_usd=0.9, take_profit_usd=1.1, reject_reason=None),
        notify_position_opened=lambda *a, **k: None,
        notify_position_closed=lambda *a, **k: None,
    )
    e._trade_logger = SimpleNamespace(log_fill=lambda *a, **k: None)
    e._position_tracker = None
    e._order_listeners = []
    return e


def _decide(engine):
    decision = SimpleNamespace(action="long", confidence=0.9, reason="test")
    asyncio.run(engine._execute_decision(decision, price=1.0, symbol="XAUUSD"))


POLICY_DENIALS = [
    "unauthorized:missing risk-approval token",
    "spread_too_wide:42.0bps",
    "sentiment_blackout:0.910",
    "macro_impact_blackout:0.880",
    "fia_throttle:CRITICAL",
]


class TestAPolicyDenialReachesNoBroker:
    @pytest.mark.parametrize("reason", POLICY_DENIALS)
    def test_a_rejected_order_is_not_placed_directly(self, reason):
        broker = _Spy()
        engine = _engine(_Router({"status": "rejected", "reason": reason, "broker": "none"}), broker)

        _decide(engine)

        assert broker.orders == [], (
            f"the router refused this order ({reason}) and it was placed on the broker anyway: {broker.orders}"
        )

    def test_the_authorization_refusal_is_the_one_that_matters_most(self):
        """Singled out because the router logs it at CRITICAL as 'Router BLOCKED order'."""
        broker = _Spy()
        engine = _engine(
            _Router({"status": "rejected", "reason": "unauthorized:no decision id", "broker": "none"}), broker
        )

        _decide(engine)

        assert not broker.orders


class TestTransportFailuresAreNotAllAlike:
    def test_no_brokers_available_may_still_go_direct(self):
        """Nothing was transmitted and the pre-route gates already passed.

        The positive control for the whole file: if this refused too, the fix
        would be "never place an order", which passes every test above while
        removing the feature.
        """
        broker = _Spy()
        engine = _engine(_Router({"status": "rejected", "reason": "no_brokers_available", "broker": "none"}), broker)

        _decide(engine)

        assert len(broker.orders) == 1, "a policy-clean transport gap must still be able to place"

    @pytest.mark.parametrize("reason", ["all_brokers_failed:broker_non_fill", "timeout:primary"])
    def test_an_order_that_may_be_in_flight_is_not_duplicated(self, reason):
        broker = _Spy()
        engine = _engine(_Router({"status": "rejected", "reason": reason, "broker": "none"}), broker)

        _decide(engine)

        assert broker.orders == [], (
            "the router had already reached a broker, so a direct order risks the duplicate "
            "fill ROUTER-TO exists to prevent"
        )

    def test_an_exception_out_of_the_router_is_an_unknown_outcome(self):
        broker = _Spy()
        engine = _engine(_Router(RuntimeError("connection reset mid-send")), broker)

        _decide(engine)

        assert broker.orders == [], "an unknown outcome must not be resolved by sending another order"


class TestTheHappyPathStillWorks:
    def test_a_routed_fill_places_nothing_directly(self):
        broker = _Spy()
        engine = _engine(_Router({"status": "filled", "broker": "primary", "fill_price": 1.0}), broker)

        _decide(engine)

        assert broker.orders == [], "the router filled it; the engine must not send a second order"


class TestThePredicateIsTiedToTheRouter:
    """The allow-list must keep describing the real router.

    `_router_refusal_is_terminal` allow-lists the transport gaps and treats
    everything else as a policy denial. That is the safe direction — a policy
    reason added to `smart_router.py` later is terminal by default rather than
    silently overruled — but it is only safe while the allow-list still names
    things the router actually returns.
    """

    def test_every_policy_reason_the_router_can_return_is_terminal(self):
        from hopefx_engine import _router_refusal_is_terminal

        for reason in POLICY_DENIALS:
            assert _router_refusal_is_terminal(reason), reason

    def test_a_transport_gap_is_not_terminal(self):
        from hopefx_engine import _router_refusal_is_terminal

        assert not _router_refusal_is_terminal("no_brokers_available")

    @pytest.mark.parametrize("reason", [None, "", "   ", 0, object()])
    def test_an_unknown_reason_fails_closed(self, reason):
        """Rule 3. A refusal nobody can classify is not a licence to trade."""
        from hopefx_engine import _router_refusal_is_terminal

        assert _router_refusal_is_terminal(reason)

    def test_the_allow_list_names_reasons_the_router_really_returns(self):
        """Starvation guard, and a drift guard.

        If `smart_router.py` renames `no_brokers_available`, this allow-list
        stops matching anything — the fix still fails closed, but it also stops
        being able to place a policy-clean order, and nobody would notice. So
        the entry is checked against the router's own source.
        """
        from pathlib import Path

        from hopefx_engine import _ROUTER_TRANSPORT_GAPS

        source = Path(__file__).resolve().parents[2] / "execution" / "smart_router.py"
        text = source.read_text(encoding="utf-8")
        assert '"status": "rejected"' in text, "the router no longer rejects this way — re-read it"

        for gap in _ROUTER_TRANSPORT_GAPS:
            assert gap in text, (
                f"{gap!r} is allow-listed as a transport gap but no longer appears in "
                f"{source.name} — the classification has drifted from the router"
            )

    def test_the_policy_reasons_this_file_tests_are_real(self):
        """The tests above would prove nothing if they asserted invented strings."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / "execution" / "smart_router.py").read_text(encoding="utf-8")

        for stem in ("unauthorized", "spread_too_wide", "sentiment_blackout", "macro_impact_blackout", "fia_throttle"):
            assert stem in source, f"{stem!r} is not a reason this router produces — the test is fiction"
