# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0
"""
tests/unit/test_risk_manager_shim.py
Coverage tests for risk/risk_manager.py — the backwards-compat shim.
"""
from __future__ import annotations


from risk.risk_manager import RiskManager


class TestRiskManagerShim:
    def test_instantiation(self):
        rm = RiskManager()
        assert rm is not None

    def test_activate_kill_switch(self):
        rm = RiskManager()
        # Should not raise; logs and calls _halt_trading
        rm.activate_kill_switch("test reason")

    def test_activate_kill_switch_default_reason(self):
        rm = RiskManager()
        rm.activate_kill_switch()

    def test_deactivate_kill_switch(self):
        rm = RiskManager()
        rm.activate_kill_switch("halt")
        rm.deactivate_kill_switch("reset")

    def test_deactivate_default_reason(self):
        rm = RiskManager()
        rm.deactivate_kill_switch()

    def test_activate_propagates_to_app_module(self, monkeypatch):
        """Covers the sys.modules app propagation branch."""
        import sys

        class FakeKS:
            activated = False

            def activate(self, reason=""):
                self.activated = True

        class FakeApp:
            kill_switch = FakeKS()

        monkeypatch.setitem(sys.modules, "app", FakeApp())
        rm = RiskManager()
        rm.activate_kill_switch("propagate test")
        assert FakeApp.kill_switch.activated

    def test_activate_no_app_module(self, monkeypatch):
        """Covers the branch where app module is not in sys.modules."""
        import sys
        monkeypatch.delitem(sys.modules, "app", raising=False)
        monkeypatch.delitem(sys.modules, "run", raising=False)
        rm = RiskManager()
        rm.activate_kill_switch("no app")  # should not raise

    def test_is_subclass_of_base(self):
        from risk.manager import RiskManager as Base
        assert issubclass(RiskManager, Base)
