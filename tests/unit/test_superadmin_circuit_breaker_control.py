# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_superadmin_circuit_breaker_control.py
=====================================================
The superadmin circuit-breaker page reported success for actions that did
nothing at all.

`POST /superadmin/risk/circuit-breakers/{name}/open` did this:

    try:
        from risk.circuit_breakers import _GLOBAL_REGISTRY
        if name in _GLOBAL_REGISTRY:
            _GLOBAL_REGISTRY[name].force_open()
    except Exception:
        pass
    return {"ok": True, "name": name, "new_state": "open"}

Three independent failures, each sufficient on its own:

1. `_GLOBAL_REGISTRY` does not exist. The registry in `risk/circuit_breakers.py`
   is `_registry`, reached through `get_circuit_breakers()`. The import raised
   `ImportError` on every call and the bare `except` swallowed it.
2. `CircuitBreaker` had no `force_open()` and no `reset()`. Had the import
   worked, the call would have raised `AttributeError` — into the same `except`.
3. The registry is empty in production anyway. `register_circuit_breaker()` is
   called by nothing outside tests, despite `get_circuit_breakers()`'s docstring
   claiming "entries are added when a CircuitBreaker is constructed".

Because all three were swallowed, the handler returned `{"ok": true,
"new_state": "open"}` and an operator watching a live drawdown believed they had
halted trading. They had not: the only thing that changed was a JSON blob in
Redis under `superadmin:risk:circuit_breakers`, which the page then read back,
so the fabricated state looked persistent and real.

The list itself was fabricated too. With no live breakers, `_load_cb_states()`
bootstrapped six invented names — `daily_drawdown`, `order_rate`, `ml_engine`
and friends — cached them for an hour, and served them as breaker state.

**Semantics, derived from the class rather than chosen.** `CircuitBreaker`
already has the two operations; they were just not reachable:

* `pre_trade_check()` returns `(False, ...)` whenever `state is OPEN`, so
  tripping the state is what actually halts trading.
* `_schedule_recovery()` returns early when `_manual_override` is set, so the
  override is what keeps a breaker open rather than letting it auto-recover.
* `manual_override(False, ...)` re-runs `_check_risk_limits()`.

So force-open = trip to OPEN *and* pin, and reset = unpin *and re-evaluate*.
Reset deliberately does **not** force the state to CLOSED: that would resume
trading through a live drawdown breach on an operator's click, which is the one
outcome this whole subsystem exists to prevent.
"""

from __future__ import annotations

from datetime import timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _make_broker(balance: float = 100_000.0) -> MagicMock:
    broker = MagicMock()
    broker.get_balance.return_value = balance
    broker.get_positions.return_value = []
    broker.cancel_all_orders.return_value = None
    return broker


def _make_cb(balance: float = 100_000.0):
    from risk.circuit_breakers import CircuitBreaker

    return CircuitBreaker(broker=_make_broker(balance), redis_client=None)


class TestTheDeadSymbol:
    def test_the_endpoint_no_longer_imports_a_name_that_does_not_exist(self):
        from pathlib import Path

        src = Path("api/superadmin/risk_management.py").read_text()
        assert "_GLOBAL_REGISTRY" not in src, (
            "risk.circuit_breakers has no _GLOBAL_REGISTRY; importing it raises "
            "ImportError into a bare except, so the control silently does nothing"
        )

    def test_the_real_registry_name_is_what_the_module_exports(self):
        import risk.circuit_breakers as mod

        assert not hasattr(mod, "_GLOBAL_REGISTRY")
        assert hasattr(mod, "get_circuit_breakers")


class TestTheBreakerHasTheOperations:
    def test_force_open_exists(self):
        from risk.circuit_breakers import CircuitBreaker

        assert callable(getattr(CircuitBreaker, "force_open", None)), (
            "the endpoint calls force_open(); AttributeError was being swallowed"
        )

    def test_reset_exists(self):
        from risk.circuit_breakers import CircuitBreaker

        assert callable(getattr(CircuitBreaker, "reset", None))


class TestForceOpenActuallyHaltsTrading:
    def test_it_moves_the_breaker_to_open(self):
        from risk.circuit_breakers import CircuitState

        cb = _make_cb()
        cb.force_open(reason="manual halt", authorized_by="superadmin@hopefx.io")

        assert cb.state is CircuitState.OPEN

    def test_pre_trade_check_then_rejects_orders(self):
        """The point of the button: no order gets through afterwards."""
        cb = _make_cb()
        allowed_before, _ = cb.pre_trade_check({"symbol": "XAUUSD", "volume": 0.1})
        cb.force_open(reason="manual halt", authorized_by="superadmin@hopefx.io")
        allowed_after, why = cb.pre_trade_check({"symbol": "XAUUSD", "volume": 0.1})

        assert allowed_before is True, "baseline: a clean breaker should permit the order"
        assert allowed_after is False
        assert "OPEN" in (why or "")

    def test_it_pins_the_breaker_so_it_cannot_auto_recover(self):
        """_schedule_recovery() returns early only when the override is set."""
        cb = _make_cb()
        cb.force_open(reason="manual halt", authorized_by="superadmin@hopefx.io")

        assert cb._manual_override is True

    def test_it_records_who_did_it(self):
        cb = _make_cb()
        cb.force_open(reason="suspected feed corruption", authorized_by="ops@hopefx.io")

        trail = " ".join(str(entry) for entry in cb.state_changes)
        assert "ops@hopefx.io" in trail
        assert "suspected feed corruption" in trail

    def test_the_rejection_message_names_the_human_who_halted_it(self):
        """pre_trade_check quotes breach_history, not state_changes.

        Recording only the state change left every rejected order reading
        "Circuit breaker OPEN: Unknown", which is indistinguishable from an
        automatic trip and tells the desk nothing.
        """
        cb = _make_cb()
        cb.force_open(reason="suspected feed corruption", authorized_by="ops@hopefx.io")

        _, why = cb.pre_trade_check({"symbol": "XAUUSD", "volume": 0.1})
        assert "Unknown" not in (why or "")
        assert "ops@hopefx.io" in (why or "")


class TestResetIsSafe:
    def test_it_clears_the_operator_pin(self):
        cb = _make_cb()
        cb.force_open(reason="manual halt", authorized_by="ops@hopefx.io")
        cb.reset(reason="incident closed", authorized_by="ops@hopefx.io")

        assert cb._manual_override is False

    def test_it_does_not_resume_trading_through_a_live_breach(self):
        """The one outcome this subsystem exists to prevent.

        The breaker is OPEN on a real drawdown. Reset must lift the operator pin
        and let the risk state decide — it must not force CLOSED.
        """
        from risk.circuit_breakers import CircuitState

        cb = _make_cb(balance=100_000.0)
        cb.peak_balance = 100_000.0
        cb.broker.get_balance.return_value = 80_000.0  # 20% down, limit is 10%
        cb.current_drawdown = 0.20
        cb.state = CircuitState.OPEN

        cb.reset(reason="operator clicked reset", authorized_by="ops@hopefx.io")

        allowed, why = cb.pre_trade_check({"symbol": "XAUUSD", "volume": 0.1})
        assert allowed is False, (
            "reset resumed trading while the account was 20% below peak; reset must "
            "clear the manual pin, not override a live breach"
        )
        assert why

    def test_it_records_who_did_it(self):
        cb = _make_cb()
        cb.force_open(reason="halt", authorized_by="ops@hopefx.io")
        cb.reset(reason="all clear", authorized_by="lead@hopefx.io")

        trail = " ".join(str(entry) for entry in cb.state_changes)
        assert "lead@hopefx.io" in trail
        assert "all clear" in trail

    def test_neither_operation_needs_a_running_event_loop(self):
        """These are called from sync contexts and from async handlers alike."""
        cb = _make_cb()
        cb.force_open(reason="halt", authorized_by="ops@hopefx.io")
        cb.reset(reason="clear", authorized_by="ops@hopefx.io")


class TestTheRegistryIsPopulated:
    def test_constructing_a_breaker_registers_it(self):
        """get_circuit_breakers()'s docstring has always claimed this."""
        from risk.circuit_breakers import get_circuit_breakers

        cb = _make_cb()

        assert cb in get_circuit_breakers().values(), (
            "the registry stayed empty in production, so the superadmin page had no live breaker to show or act on"
        )

    def test_a_registered_breaker_is_reachable_by_name(self):
        from risk.circuit_breakers import get_circuit_breakers

        cb = _make_cb()
        names = [n for n, v in get_circuit_breakers().items() if v is cb]

        assert names, "a constructed breaker must be addressable by name"


class TestTheEndpointTellsTheTruth:
    def test_acting_on_a_breaker_with_no_live_object_is_not_reported_as_success(self):
        """A fabricated name must not answer {'ok': true, 'new_state': 'open'}."""
        import inspect

        from api.superadmin.risk_management import force_open_circuit_breaker

        src = inspect.getsource(force_open_circuit_breaker)
        assert '"ok": True' not in src.split("_persist_cb_states")[0] or "live" in src, (
            "the handler must distinguish 'the live breaker was opened' from 'a JSON blob in Redis was edited'"
        )

    def test_the_bootstrap_list_is_marked_as_not_live(self):
        """Six invented breaker names were served as if they were real state."""
        from api.superadmin.risk_management import _load_cb_states
        from risk.circuit_breakers import get_circuit_breakers

        get_circuit_breakers().clear()
        states = _load_cb_states()

        assert states, "the page should still render something"
        for entry in states:
            assert entry.get("live") is False, (
                f"{entry.get('name')!r} is a placeholder, not a registered breaker, "
                f"and the page must say so rather than implying live state"
            )

    def test_a_live_breaker_is_reported_as_live(self):
        from api.superadmin.risk_management import _load_cb_states
        from risk.circuit_breakers import get_circuit_breakers

        get_circuit_breakers().clear()
        _make_cb()
        states = _load_cb_states()

        assert any(entry.get("live") is True for entry in states)


class TestTwoBreakersDoNotCollide:
    """A second breaker must not silently replace the first.

    `_derive_name` falls back to `type(broker).__name__` and
    `register_circuit_breaker` overwrites by key, so two brokers of the same
    class with no `broker_name` mapped to one registry entry. A superadmin
    force-open would then halt only the surviving instance while answering
    `{"ok": true, "new_orders_blocked": true}` — a narrower form of the very
    "the control reports success without controlling anything" bug this
    subsystem was fixed for.
    """

    def test_both_breakers_are_registered(self):
        from risk.circuit_breakers import get_circuit_breakers

        get_circuit_breakers().clear()
        first = _make_cb()
        second = _make_cb()

        registered = list(get_circuit_breakers().values())
        assert first in registered
        assert second in registered, (
            "the second breaker overwrote the first in the registry, so halting 'MagicMock' would halt only one of them"
        )

    def test_they_get_distinct_names(self):
        from risk.circuit_breakers import get_circuit_breakers

        get_circuit_breakers().clear()
        _make_cb()
        _make_cb()

        assert len(get_circuit_breakers()) == 2

    def test_an_explicit_name_is_respected(self):
        from risk.circuit_breakers import CircuitBreaker, get_circuit_breakers

        get_circuit_breakers().clear()
        cb = CircuitBreaker(broker=_make_broker(), redis_client=None, name="oanda_live")

        assert get_circuit_breakers()["oanda_live"] is cb

    def test_a_broker_name_attribute_is_used_verbatim(self):
        from risk.circuit_breakers import CircuitBreaker, get_circuit_breakers

        get_circuit_breakers().clear()
        broker = _make_broker()
        broker.broker_name = "ftmo_challenge"
        cb = CircuitBreaker(broker=broker, redis_client=None)

        assert get_circuit_breakers()["ftmo_challenge"] is cb
