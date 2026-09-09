# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`trader_full.py` built a RiskManager with nothing to measure.

    self._rm = _RM(config=RiskConfig(), initial_balance=self._balance)

No orchestrator, so `_measured_data_quality()` returns None for every signal
and `size_order()` refuses every trade with `data_quality:unmeasured`. Before
§E12 that was invisible — the missing orchestrator scored a perfect 1.0 and the
gate passed everything. Afterwards it is visible and inverted: this entry point
cannot size a single position.

Both states are wrong, and the second is the one worth fixing rather than
tolerating. A gate that refuses everything is indistinguishable from a broken
component, and an operator who sees `data_quality:unmeasured` on every decision
learns to ignore the reason.

The construction site is `trader_full.RiskManager.setup()`, not the
`RiskManager(initial_balance=...)` line in `_main()` — that name is a local
wrapper class in the same module, which builds the real one inside `setup()`.
Worth stating because reading the call in `_main()` points at the wrong object.

`trader_full.py` is not a deployed entry point — the container runs `app.py`,
and `run.py` uses `HopeFXEngine` (falling back to `core.main_loop`) — but it
carries `if __name__ == "__main__":` and is reachable by hand, which is exactly
how someone ends up debugging a dead gate at the wrong layer.

Every other construction site already resolves the orchestrator the same way:
`risk/manager.py::_make_risk_manager`, `core/startup_factories.py::init_risk_manager`
and `hopefx_engine.py`. This one did not, and the seam is extracted so the
wiring can be asserted rather than read.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Cfg:
    initial_balance = 100_000.0


class TestTheRiskManagerGetsSomethingToMeasure:
    def test_setup_wires_the_data_layer_orchestrator(self) -> None:
        import trader_full

        wrapper = trader_full.RiskManager(initial_balance=100_000.0)
        wrapper.setup()
        assert wrapper._rm is not None, "setup() did not build the real RiskManager"
        assert getattr(wrapper._rm, "_orch", None) is not None, (
            "trader_full builds its RiskManager with no orchestrator, so every trade is "
            "refused with data_quality:unmeasured"
        )

    def test_it_honours_the_configured_balance(self) -> None:
        import trader_full

        wrapper = trader_full.RiskManager(initial_balance=100_000.0)
        wrapper.setup()
        assert wrapper._rm._state.account_equity == pytest.approx(100_000.0)

    def test_an_unavailable_orchestrator_is_loud_not_silent(self, monkeypatch, caplog) -> None:
        """A RiskManager that cannot measure must say so at build time.

        The alternative is discovering it one refused trade at a time. It must
        also still start — this is a standalone trader, and failing to boot is
        worse than booting and refusing.
        """
        import logging

        import trader_full

        monkeypatch.setattr(trader_full, "_resolve_orchestrator", lambda: None)
        wrapper = trader_full.RiskManager(initial_balance=100_000.0)
        with caplog.at_level(logging.WARNING):
            wrapper.setup()

        assert wrapper._rm is not None, "a missing data layer must not stop the trader from starting"
        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "the RiskManager was built unable to measure anything and nothing was logged"
        )


class TestTheGateBehavesAsWired:
    def test_with_an_orchestrator_that_has_a_tick_sizing_is_possible(self) -> None:
        import trader_full
        from risk.manager import RiskManager

        class _Tick:
            confidence = 0.9

        class _Orch:
            def get_latest_tick(self, symbol: str = "XAU_USD"):
                return _Tick()

            def get_ml_features(self) -> dict:
                return {}

        manager = RiskManager(orchestrator=_Orch(), initial_balance=100_000.0)
        result = manager.calculate_position_size(
            symbol="XAU_USD",
            signal_strength=0.9,
            probability=0.62,
            direction="long",
            entry_price=3300.0,
            stop_loss_price=3280.0,
            take_profit_price=3360.0,
            account_equity=100_000.0,
        )
        assert result.quantity > 0
        assert trader_full is not None  # the module imports cleanly alongside this

    def test_without_one_every_trade_is_refused(self) -> None:
        # The state trader_full was in. Kept as the counter-example.
        from risk.manager import RiskManager

        manager = RiskManager(initial_balance=100_000.0)
        result = manager.calculate_position_size(
            symbol="XAU_USD",
            signal_strength=0.9,
            probability=0.62,
            direction="long",
            entry_price=3300.0,
            stop_loss_price=3280.0,
            take_profit_price=3360.0,
            account_equity=100_000.0,
        )
        assert result.quantity == 0
        assert result.reason == "data_quality:unmeasured"
