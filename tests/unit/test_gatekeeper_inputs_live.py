"""Regression tests: Gatekeeper checks must run on live inputs.

Round 3 audit findings S2-02, S2-03 and S2-04 (docs/HARDENING_BACKLOG.md).

Same shape as S1-04: the checks were implemented correctly but wired to state
nothing on the decision-engine path ever wrote, so they compared a constant
against a limit and could never fire.

S2-02 — ``Gatekeeper.start()`` was never called from ``startup_factories``, and
``start()`` is what launches ``_breach_listener``, the **only** production
writer of ``_kill_active`` and the equity tracker. Checks 1 (kill switch),
3 (daily drawdown) and 4 (max drawdown) therefore evaluated ``False``, ``0.0``
and ``0.0`` forever, and ``metrics()`` reported ``daily_dd_pct: 0.0`` no matter
the real account.

S2-03 — check 11 read ``getattr(signal, "tick_spread", 0.0)``. The brain's
``Signal`` (``strategies/base.py``) has no such attribute, so the gate compared
``0.0 > _MAX_SPREAD_USD`` on every call. The spread gate — the control meant to
keep the system out of a news spike — could not fire.

S2-04 — the FIA 2024 pre-trade controls were handed a hardcoded order size of
``1.0``, side ``"long"``, capital from ``INITIAL_BALANCE``, and
``daily_pnl=0.0``, because ``Signal`` carries none of those fields. The FIA
daily-loss control had a constant zero as its input and could never trigger.
"""

from unittest.mock import MagicMock

import pytest


def _gatekeeper():
    from risk.gatekeeper import Gatekeeper

    return Gatekeeper()


@pytest.mark.unit
class TestGatekeeperEquityIsWired:
    def test_drawdown_checks_see_real_equity(self):
        """Feeding equity must move the drawdown the checks read (S2-02)."""
        gk = _gatekeeper()
        gk.update_equity(100_000.0)
        gk.update_equity(88_000.0)  # 12% down

        m = gk.metrics()
        assert m["max_dd_pct"] > 0.0, (
            "Gatekeeper drawdown is still 0.0 after a 12% equity fall — the "
            "checks are reading a tracker nothing updates (S2-02)."
        )

    def test_startup_starts_the_breach_listener(self):
        """The factory must start the listener that feeds those checks."""
        import inspect

        from core import startup_factories

        src = inspect.getsource(startup_factories)
        assert "start_breach_listener" in src or "gatekeeper.start" in src, (
            "startup_factories must start the Gatekeeper's breach listener, or "
            "its kill-switch and drawdown checks can never fire (S2-02)."
        )

    def test_breach_listener_can_be_started_without_consuming_signals(self):
        """start() awaits the signal consumer forever, so it cannot be awaited.

        There must be a way to run only the breach listener.
        """
        from risk.gatekeeper import Gatekeeper

        assert hasattr(Gatekeeper, "start_breach_listener"), (
            "Gatekeeper needs a way to start the breach listener independently of the event-bus consumer loop (S2-02)."
        )


@pytest.mark.unit
class TestSpreadGateFires:
    def test_spread_gate_blocks_a_wide_spread(self):
        """Check 11 must actually be reachable (S2-03)."""
        from risk import gatekeeper as gk_mod

        failures = gk_mod.Gatekeeper._run_checks_params(
            kill_active=False,
            paused_until=0.0,
            daily_dd=0.0,
            max_dd=0.0,
            data_quality=1.0,
            is_blackout=False,
            impact_score=0.0,
            sentiment_score=0.0,
            daily_trades=0,
            confidence=0.99,
            spread=gk_mod._MAX_SPREAD_USD + 1.0,
        )
        assert any(f["reason"] == "spread_too_wide" for f in failures)

    def test_spread_is_sourced_from_the_orchestrator(self):
        """The gate must not read an attribute the live signal lacks.

        strategies.base.Signal has no tick_spread, so sourcing it from the
        signal meant the gate always saw 0.0.
        """
        import inspect

        from risk.gatekeeper import Gatekeeper

        src = inspect.getsource(Gatekeeper._run_checks_on_signal)
        assert 'getattr(signal, "tick_spread"' not in src, (
            "Spread must come from the orchestrator tick, not from a signal "
            "attribute the decision-engine path never populates (S2-03)."
        )

    def test_orchestrator_spread_reaches_the_gate(self):
        """With an orchestrator wired, a wide tick must block the signal."""
        from risk.gatekeeper import Gatekeeper

        tick = MagicMock()
        tick.confidence = 1.0
        tick.spread = 99.0  # absurdly wide

        orch = MagicMock()
        orch.get_latest_tick = MagicMock(return_value=tick)
        orch.get_ml_features = MagicMock(return_value={})

        gk = Gatekeeper(orchestrator=orch)
        signal = MagicMock()
        signal.confidence = 0.99

        failures = gk._run_checks_on_signal(signal)
        assert any(f["reason"] == "spread_too_wide" for f in failures), (
            f"wide orchestrator spread did not block; failures={failures}"
        )


@pytest.mark.unit
class TestFIAInputsAreReal:
    def test_fia_order_size_is_not_hardcoded(self):
        """FIA size limits must see the real order size (S2-04)."""
        import inspect

        from risk.gatekeeper import Gatekeeper

        src = inspect.getsource(Gatekeeper._run_fia_checks)
        assert 'getattr(signal, "size", 1.0)' not in src, (
            "FIA controls must not validate a hardcoded order size of 1.0 (S2-04)."
        )

    def test_fia_daily_pnl_is_not_hardcoded_zero(self):
        """The FIA daily-loss control must have a real input (S2-04)."""
        import inspect

        from risk.gatekeeper import Gatekeeper

        src = inspect.getsource(Gatekeeper._run_fia_checks)
        assert 'getattr(signal, "daily_pnl", 0.0)' not in src, (
            "FIA daily-loss control had a constant 0.0 as its input, so it could never trigger (S2-04)."
        )
