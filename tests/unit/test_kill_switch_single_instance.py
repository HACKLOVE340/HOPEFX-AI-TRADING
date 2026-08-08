"""Regression tests for kill-switch instance identity.

Round 3 audit finding S2-01 (docs/HARDENING_BACKLOG.md).

``app.py`` constructed its **own** ``KillSwitch`` and started it (poll loop,
flag-file watcher, Redis latch listener), while ``kill_switch.py`` exposes a
module singleton that is never started but **is** the instance the money path
consults via ``risk/pre_trade_gate.py`` ``_check_kill_switch``. Nothing
synchronised the two.

Consequences of the split:

  * ``POST /api/kill-switch/activate`` (the router ``app.py`` registers) set the
    app instance and returned success while orders kept flowing, because the
    pre-trade gate reads the module singleton.
    ``POST /nuclear/kill_switch/activate`` (``api/nuclear.py``) is the one that
    actually stopped trading. Two endpoints, opposite effects.
  * Writing ``kill_switch.flag`` — the documented runbook mechanism — was polled
    only by the app instance, so it never blocked a trade.
  * Redis cross-pod activation likewise reached only the app instance.
  * ``RiskManager._halt_trading`` activates ``app.kill_switch``; the gate's
    instance stayed inactive.
  * Health routes report the app instance, so a ``/nuclear``-activated kill
    switch displayed as **inactive** while trading was blocked.

Only ``HOPEFX_KILL_SWITCH=1`` worked on both, because each reads it in
``__init__``.

These tests pin the invariant: **exactly one KillSwitch instance**, and the one
the money path reads is the one the API and the ops mechanisms drive.
"""

import pytest


@pytest.mark.unit
class TestKillSwitchSingleInstance:
    def test_app_uses_the_module_singleton(self):
        """app.kill_switch must BE kill_switch.kill_switch, not a second object."""
        import app as app_module
        import kill_switch as ks_module

        assert app_module.kill_switch is ks_module.kill_switch, (
            "app.py must not construct its own KillSwitch — the money path reads "
            "the module singleton via risk/pre_trade_gate.py (S2-01)."
        )

    def test_app_does_not_construct_a_killswitch(self):
        """Guard the root cause, not just the symptom.

        A future edit could re-introduce `KillSwitch(...)` in app.py and this
        would drift back apart, so assert the constructor call is gone.
        """
        import inspect

        import app as app_module

        src = inspect.getsource(app_module)
        assert "KillSwitch(" not in src, (
            "app.py must import the kill_switch singleton, never instantiate KillSwitch (S2-01)."
        )

    def test_pre_trade_gate_sees_singleton_activation(self):
        """Activating the singleton must block at the pre-trade gate.

        This is the end-to-end property that failed: the gate resolves its kill
        switch independently, so identity has to hold all the way through.
        """
        from unittest.mock import MagicMock

        import kill_switch as ks_module
        from risk.pre_trade_gate import GateOrder, PreTradeGate, TradeBlockedError

        ks = ks_module.kill_switch
        ks.reset_for_testing()

        rm = MagicMock()
        # RiskManager does not set _kill_switch, so the gate falls back to the
        # module singleton — exactly the production path.
        rm._kill_switch = None
        rm._trading_halted = False

        gate = PreTradeGate(rm)
        order = GateOrder(symbol="XAU_USD", side="BUY", quantity=1.0, price=3300.0)

        try:
            ks.activate("test: S2-01 regression")
            with pytest.raises(TradeBlockedError) as exc:
                gate.check(order)
            assert exc.value.reason_code == "KILL_SWITCH_ACTIVE"
        finally:
            ks.reset_for_testing()

    def test_router_and_gate_share_one_instance(self):
        """The router app.py registers must drive the instance the gate reads.

        Reproduces the "wrong endpoint" scenario: activating through the object
        the app router was built with has to be visible to the gate.
        """
        from unittest.mock import MagicMock

        import app as app_module
        import kill_switch as ks_module
        from risk.pre_trade_gate import GateOrder, PreTradeGate, TradeBlockedError

        ks_module.kill_switch.reset_for_testing()

        rm = MagicMock()
        rm._kill_switch = None
        rm._trading_halted = False
        gate = PreTradeGate(rm)
        order = GateOrder(symbol="XAU_USD", side="BUY", quantity=1.0, price=3300.0)

        try:
            # Activate via the object app.py handed to create_kill_switch_router.
            app_module.kill_switch.activate("test: activated via app router instance")
            with pytest.raises(TradeBlockedError):
                gate.check(order)
        finally:
            ks_module.kill_switch.reset_for_testing()

    def test_singleton_keeps_the_event_bus_wiring(self):
        """Consolidating must not drop cross-pod propagation.

        app.py wired a Redis EventBus into its own instance; after the fix the
        singleton must carry it, or Redis/cross-pod activation is silently lost.
        """
        import app as app_module  # noqa: F401  (import wires the bus as a side effect)
        import kill_switch as ks_module

        assert ks_module.kill_switch._event_bus is not None, (
            "app.py must attach the event bus to the singleton via "
            "set_event_bus() so cross-pod propagation survives the fix (S2-01)."
        )
